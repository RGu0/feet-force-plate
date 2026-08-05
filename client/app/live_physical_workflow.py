"""Institution-owned real-hardware capture and local BASIC report boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import time
from uuid import uuid4

from cloud.analysis.feature_parameters import FeatureParameters
from client.app.institution_store import InstitutionLocalStore
from client.app.live_baseline import LiveBaselinePreflight
from client.app.live_hardware_demo import (
    build_operator_attested_protocol,
    is_basic_report_eligible,
    operator_attestations_from_completion_flags,
    static_balance_stage_plan,
)
from client.device.stage_windows import (
    CapturedStageWindow,
    validate_captured_stage_windows,
)
from client.device.acquisition import ConnectionStateMachine
from client.device.session_runtime import HardwareSessionRuntime
from client.hardware_standardization.quality import DoP4864HardwareQualityGate
from client.local_analysis.service import (
    ProcessingOutcome,
    ProcessingStatus,
    process_committed_physical_session,
)
from client.spool.session_commit import ValidSessionStager
from client.spool.state_store import KeyProvider, StateStore
from client.workflow.models import ScreeningParticipantContext
from client.workflow.protocol import ProtocolSnapshot


@dataclass(frozen=True, slots=True)
class LiveSessionMetadata:
    subject_uuid: str
    consent_record_id: str
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class LiveAnalysisInputs:
    completed: tuple[bool, ...]
    captured_windows: tuple[CapturedStageWindow, ...]


class InstitutionLiveSessions:
    """One local workflow session maps to one physical encrypted capture."""

    def __init__(self, store: InstitutionLocalStore) -> None:
        self._store = store
        self._metadata: dict[str, LiveSessionMetadata] = {}

    def create_session(
        self, context: ScreeningParticipantContext, protocol: ProtocolSnapshot
    ) -> str:
        session_id = self._store.create_session(context, protocol)
        self._metadata[session_id] = LiveSessionMetadata(
            context.subject_uuid, context.consent_record_id, datetime.now(UTC)
        )
        return session_id

    def metadata(self, session_id: str) -> LiveSessionMetadata:
        try:
            return self._metadata[session_id]
        except KeyError as exc:
            raise KeyError("institution session metadata is unavailable") from exc

    def mark_incomplete(self, session_id: str) -> None:
        self._store.mark_incomplete(session_id)

    def mark_stage_complete(self, session_id: str, stage_id: str) -> None:
        self._store.mark_stage_complete(session_id, stage_id)

    def finalize(self, session_id: str) -> None:
        self._store.finalize(session_id)


class LivePhysicalCapture:
    """Create one encrypted physical session using the P-05 empty-board reference."""

    def __init__(
        self,
        *,
        hardware,
        sessions: InstitutionLiveSessions,
        baseline: LiveBaselinePreflight,
        physical_store: StateStore,
        key_provider: KeyProvider,
        spool_root: Path,
        latest_frames,
        stage_seconds: int = 20,
    ) -> None:
        self._hardware = hardware
        self._sessions = sessions
        self._baseline = baseline
        self._physical_store = physical_store
        self._key_provider = key_provider
        self._spool_root = spool_root
        self._latest_frames = latest_frames
        self._stage_seconds = stage_seconds

    def capture(self, session_id: str):
        reference = self._baseline.reference
        if reference is None:
            raise RuntimeError("P-05 empty-board baseline is required before capture")
        metadata = self._sessions.metadata(session_id)
        self._physical_store.put_subject_ref(session_id, metadata.subject_uuid.encode())
        self._physical_store.put_consent_record(
            metadata.consent_record_id,
            session_id,
            metadata.consent_record_id.encode(),
            recorded_at_ns=time.time_ns(),
        )
        stager = ValidSessionStager(
            self._spool_root,
            session_id=session_id,
            key_provider=self._key_provider,
            store=self._physical_store,
            subject_uuid=session_id,
            consent_id=metadata.consent_record_id,
            versions={
                "institution_live": "institution-live-ui/1",
                "protocol": "static-balance/live-ui/1",
            },
            started_at_ns=time.time_ns(),
        )
        connection = self._hardware.connect_startup()
        state = ConnectionStateMachine()
        state.start_connecting()
        state.mark_ready()
        try:
            return HardwareSessionRuntime(
                transport=connection.transport,
                parser=connection.parser,
                connection=state,
                mailbox=self._latest_frames,
                stager=stager,
                quality_gate=DoP4864HardwareQualityGate(baseline_reference=reference),
            ).capture(
                session_id=session_id,
                minimum_duration_ns=self._stage_seconds * 4 * 1_000_000_000,
            )
        finally:
            connection.transport.close()


class LivePhysicalProcessor:
    """Generate a local BASIC report only after explicit four-stage attestation."""

    def __init__(
        self,
        *,
        sessions: InstitutionLiveSessions,
        physical_store: StateStore,
        key_provider: KeyProvider,
        spool_root: Path,
        reports: InstitutionLocalStore,
        stage_seconds: int = 20,
    ) -> None:
        self._sessions = sessions
        self._physical_store = physical_store
        self._key_provider = key_provider
        self._spool_root = spool_root
        self._reports = reports
        self._stage_seconds = stage_seconds
        self._attestations: dict[str, LiveAnalysisInputs] = {}

    def record_attestations(
        self,
        session_id: str,
        completed: tuple[bool, ...],
        *,
        captured_windows: tuple[CapturedStageWindow, ...] = (),
    ) -> None:
        if len(completed) != 4:
            raise ValueError("all four live stages require an operator attestation")
        plan = static_balance_stage_plan(stage_seconds=self._stage_seconds)
        if captured_windows:
            captured_windows = validate_captured_stage_windows(
                captured_windows,
                expected_stage_ids=tuple(stage.stage_id.value for stage in plan),
                minimum_duration_s=self._stage_seconds,
            )
        self._attestations[session_id] = LiveAnalysisInputs(completed, captured_windows)

    def process(self, session_id: str) -> ProcessingOutcome:
        inputs = self._attestations.get(session_id)
        if (
            inputs is None
            or len(inputs.completed) != 4
            or len(inputs.captured_windows) != 4
        ):
            return ProcessingOutcome(ProcessingStatus.RETRY_REQUIRED, None, None)
        plan = static_balance_stage_plan(stage_seconds=self._stage_seconds)
        try:
            captured_windows = validate_captured_stage_windows(
                inputs.captured_windows,
                expected_stage_ids=tuple(stage.stage_id.value for stage in plan),
                minimum_duration_s=self._stage_seconds,
            )
        except ValueError:
            return ProcessingOutcome(ProcessingStatus.RETRY_REQUIRED, None, None)
        context = build_operator_attested_protocol(
            session_id=session_id,
            stage_seconds=self._stage_seconds,
            attestations=operator_attestations_from_completion_flags(
                plan, inputs.completed
            ),
            captured_windows=captured_windows,
        )
        if not is_basic_report_eligible(context):
            return ProcessingOutcome(ProcessingStatus.RETRY_REQUIRED, None, None)
        metadata = self._sessions.metadata(session_id)
        outcome = process_committed_physical_session(
            self._spool_root,
            session_id=session_id,
            store=self._physical_store,
            key_provider=self._key_provider,
            protocol_context=context,
            parameters=FeatureParameters(version="physical-features/institution-live-ui/1"),
            report_id=f"basic-{uuid4().hex[:12]}",
            report_version=1,
            analysis_result_id=f"local-{uuid4().hex[:12]}",
            subject_display_id=f"匿名 {metadata.subject_uuid[-6:]}",
            captured_at=metadata.captured_at,
            generated_at=datetime.now(UTC),
        )
        self._reports.save_report(outcome.report)
        return ProcessingOutcome(ProcessingStatus.BASIC_READY, None, outcome.report)
