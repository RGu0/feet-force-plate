"""Institution-owned real-hardware capture and local BASIC report boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import threading
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
    StageRecordingGate,
    validate_captured_stage_windows,
)
from client.device.acquisition import (
    AcquisitionIntegrityEvent,
    AcquisitionOutcome,
    AcquisitionResult,
    AcquisitionRunner,
    default_maximum_no_valid_signal_ns,
)
from client.device.protocol import FRAME_LENGTH, ProtocolIntegrityEvent, RawFrame
from client.device.session_runtime import HardwareSessionResult, SessionValidity
from client.device.session_ui import (
    finalization_failed,
    from_quality_reasons,
    processing_failed,
)
from client.device.transport import TransportDisconnected
from client.hardware_standardization.quality import DoP4864HardwareQualityGate
from client.local_analysis.service import (
    ProcessingOutcome,
    ProcessingStatus,
    process_committed_physical_session,
)
from client.spool.session_commit import FinalSessionStorageError, ValidSessionStager
from client.spool.stage_attempt import StageAttemptSpool
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


@dataclass(frozen=True, slots=True)
class LiveHardwareSessionResult(HardwareSessionResult):
    stage_windows: tuple[CapturedStageWindow, ...] = ()


class RetryableStageCaptureError(RuntimeError):
    """The current stage was discarded while earlier verified stages remain."""


@dataclass(slots=True)
class _LiveCaptureState:
    gate: StageRecordingGate
    stager: ValidSessionStager
    quality_gate: DoP4864HardwareQualityGate
    attempt_versions: dict[str, str]
    integrity_events: list[AcquisitionIntegrityEvent]
    reconstructed_frames: list[RawFrame]


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
        maximum_no_valid_signal_ns: int | None = None,
        storage_append_timeout_s: float | None = None,
        read_size: int = FRAME_LENGTH,
        monotonic_ns=time.monotonic_ns,
        wall_time_ns=time.time_ns,
    ) -> None:
        if stage_seconds <= 0:
            raise ValueError("stage_seconds must be positive")
        if read_size <= 0:
            raise ValueError("read_size must be positive")
        if storage_append_timeout_s is not None and storage_append_timeout_s < 0:
            raise ValueError("storage append timeout must not be negative")
        self._hardware = hardware
        self._sessions = sessions
        self._baseline = baseline
        self._physical_store = physical_store
        self._key_provider = key_provider
        self._spool_root = spool_root
        self._latest_frames = latest_frames
        self._stage_seconds = stage_seconds
        self._maximum_no_valid_signal_ns = (
            default_maximum_no_valid_signal_ns()
            if maximum_no_valid_signal_ns is None
            else maximum_no_valid_signal_ns
        )
        if self._maximum_no_valid_signal_ns <= 0:
            raise ValueError("maximum no-valid-signal interval must be positive")
        self._storage_append_timeout_s = storage_append_timeout_s
        self._read_size = read_size
        self._monotonic_ns = monotonic_ns
        self._wall_time_ns = wall_time_ns
        self._states: dict[str, _LiveCaptureState] = {}
        self._active_workers: set[str] = set()
        self._state_lock = threading.Lock()

    def capture(
        self, session_id: str, gate: StageRecordingGate
    ) -> HardwareSessionResult:
        reference = self._baseline.reference
        if reference is None:
            raise RuntimeError("P-05 empty-board baseline is required before capture")
        gate.bind_session(session_id)
        self._claim_worker(session_id, gate)
        connection = None
        try:
            try:
                connection = self._hardware.connect_startup()
                state = self._state_for_connection(
                    session_id,
                    gate=gate,
                    parser=connection.parser,
                    reference=reference,
                )
            except Exception as exc:
                gate.cancel_current_stage()
                raise RetryableStageCaptureError(
                    f"device startup failed: {type(exc).__name__}: {exc}"
                ) from exc
            return self._capture_connection(
                session_id,
                gate=gate,
                state=state,
                transport=connection.transport,
                parser=connection.parser,
            )
        finally:
            try:
                if connection is not None:
                    try:
                        connection.transport.close()
                    except Exception:
                        pass
            finally:
                with self._state_lock:
                    self._active_workers.discard(session_id)

    def _claim_worker(self, session_id: str, gate: StageRecordingGate) -> None:
        with self._state_lock:
            state = self._states.get(session_id)
            if state is not None and state.gate is not gate:
                raise RuntimeError("a live session cannot replace its recording gate")
            if session_id in self._active_workers:
                raise RuntimeError("a live session already has an active device worker")
            self._active_workers.add(session_id)

    def _state_for_connection(
        self,
        session_id: str,
        *,
        gate: StageRecordingGate,
        parser,
        reference,
    ) -> _LiveCaptureState:
        with self._state_lock:
            existing = self._states.get(session_id)
            if existing is not None:
                expected_profile = existing.attempt_versions["protocol_profile"]
                if parser.profile.version != expected_profile:
                    raise RuntimeError("reconnected parser profile changed during the session")
                return existing

            metadata = self._sessions.metadata(session_id)
            self._physical_store.put_subject_ref(
                session_id, metadata.subject_uuid.encode()
            )
            self._physical_store.put_consent_record(
                metadata.consent_record_id,
                session_id,
                metadata.consent_record_id.encode(),
                recorded_at_ns=self._wall_time_ns(),
            )
            quality_gate = DoP4864HardwareQualityGate(
                baseline_reference=reference
            )
            versions = {
                "institution_live": "institution-live-ui/1",
                "protocol": "static-balance/live-ui/1",
                "protocol_profile": parser.profile.version,
                "maximum_no_valid_signal_ns": str(
                    self._maximum_no_valid_signal_ns
                ),
                "reconstruction_policy": "interpolate-adjacent-valid-frames/1",
                "storage_append_timeout_ms": str(
                    None
                    if self._storage_append_timeout_s is None
                    else round(self._storage_append_timeout_s * 1_000)
                ),
                **quality_gate.frozen_configuration_versions(),
            }
            stager = ValidSessionStager(
                self._spool_root,
                session_id=session_id,
                key_provider=self._key_provider,
                store=self._physical_store,
                subject_uuid=session_id,
                consent_id=metadata.consent_record_id,
                versions={
                    "institution_live": versions["institution_live"],
                    "protocol": versions["protocol"],
                },
                started_at_ns=self._wall_time_ns(),
                expected_stage_ids=gate.expected_stage_ids,
            )
            stager.freeze_versions(
                {
                    key: value
                    for key, value in versions.items()
                    if key not in {"institution_live", "protocol"}
                }
            )
            state = _LiveCaptureState(
                gate=gate,
                stager=stager,
                quality_gate=quality_gate,
                attempt_versions=versions,
                integrity_events=[],
                reconstructed_frames=[],
            )
            self._states[session_id] = state
            return state

    def _capture_connection(
        self,
        session_id: str,
        *,
        gate: StageRecordingGate,
        state: _LiveCaptureState,
        transport,
        parser,
    ) -> LiveHardwareSessionResult:
        attempt: StageAttemptSpool | None = None
        current_stage_id: str | None = None
        previous_frame: RawFrame | None = None
        last_valid_observed_ns: int | None = None
        pending_events: list[ProtocolIntegrityEvent] = []
        stage_integrity_events: list[AcquisitionIntegrityEvent] = []
        stage_reconstructed_frames: list[RawFrame] = []

        def reset_stage_continuity_state() -> None:
            nonlocal previous_frame, last_valid_observed_ns, pending_events
            previous_frame = None
            last_valid_observed_ns = None
            pending_events = []

        try:
            while True:
                snapshot = gate.snapshot()
                if snapshot.cancelled:
                    raise RetryableStageCaptureError("current stage capture was cancelled")
                active = (
                    snapshot.stage_id is not None
                    and not snapshot.stage_complete
                    and not snapshot.cancelled
                    and not snapshot.session_complete
                )
                if active and current_stage_id is None:
                    current_stage_id = snapshot.stage_id
                    last_valid_observed_ns = self._monotonic_ns()
                elif not active and current_stage_id is None:
                    reset_stage_continuity_state()

                chunk = transport.read(self._read_size)
                now_ns = self._monotonic_ns()
                if not chunk:
                    if (
                        current_stage_id is not None
                        and last_valid_observed_ns is not None
                        and now_ns - last_valid_observed_ns
                        >= self._maximum_no_valid_signal_ns
                    ):
                        raise RetryableStageCaptureError(
                            "no valid decoded signal for five seconds"
                        )
                    continue
                if (
                    current_stage_id is not None
                    and last_valid_observed_ns is not None
                    and now_ns - last_valid_observed_ns
                    >= self._maximum_no_valid_signal_ns
                ):
                    raise RetryableStageCaptureError(
                        "no valid decoded signal for five seconds"
                    )

                decoded = parser.feed(chunk)
                pending_events.extend(parser.take_integrity_events())
                if not decoded and current_stage_id is None:
                    pending_events = []
                for frame in decoded:
                    decision = gate.observe(frame)
                    self._latest_frames.publish(frame)
                    if not decision.record:
                        if gate.snapshot().cancelled:
                            raise RetryableStageCaptureError(
                                "current stage capture was cancelled"
                            )
                        current_stage_id = None
                        reset_stage_continuity_state()
                        continue
                    if decision.stage_id is None:
                        raise RuntimeError("recorded frame is missing its stage identity")
                    if current_stage_id is None:
                        current_stage_id = decision.stage_id
                        last_valid_observed_ns = now_ns
                    if current_stage_id != decision.stage_id:
                        raise RuntimeError("recording gate changed stages mid-frame")
                    if attempt is None:
                        attempt = StageAttemptSpool(
                            self._spool_root,
                            session_id=session_id,
                            stage_id=decision.stage_id,
                            key_provider=self._key_provider,
                            versions=state.attempt_versions,
                        )
                    if previous_frame is not None and (
                        frame.host_monotonic_ns - previous_frame.host_monotonic_ns
                        >= self._maximum_no_valid_signal_ns
                    ):
                        raise RetryableStageCaptureError(
                            "no valid decoded signal for five seconds"
                        )
                    resolved, reconstructed = AcquisitionRunner._resolve_events_before_frame(
                        pending_events, previous_frame, frame
                    )
                    stage_integrity_events.extend(resolved)
                    stage_reconstructed_frames.extend(reconstructed)
                    pending_events = [
                        event
                        for event in pending_events
                        if event.valid_frames_before > frame.source_index
                    ]
                    try:
                        attempt.append(frame)
                    except Exception as exc:
                        raise RetryableStageCaptureError(
                            f"storage handoff failed: {type(exc).__name__}: {exc}"
                        ) from exc
                    previous_frame = frame
                    last_valid_observed_ns = self._monotonic_ns()
                    if not decision.stage_complete:
                        continue
                    if decision.window is None:
                        raise RuntimeError("completed stage is missing its captured window")
                    sealed_attempt = attempt.seal()
                    if not gate.begin_stage_commit(decision.window):
                        raise RetryableStageCaptureError(
                            "current stage was cancelled before durable merge"
                        )
                    attempt.discard(reason="sealed for final session merge")
                    attempt = None
                    state.stager.append_verified_stage(
                        sealed_attempt, decision.window
                    )
                    gate.complete_stage_commit(decision.window)
                    state.integrity_events.extend(stage_integrity_events)
                    state.reconstructed_frames.extend(stage_reconstructed_frames)
                    stage_integrity_events = []
                    stage_reconstructed_frames = []
                    current_stage_id = None
                    reset_stage_continuity_state()
                    if decision.session_complete:
                        return self._finalize_session(session_id, state)
        except TransportDisconnected as exc:
            reason = f"transport disconnected: {exc}"
            self._discard_retryable_attempt(
                gate,
                attempt=attempt,
                current_stage_id=current_stage_id,
                reason=reason,
            )
            raise RetryableStageCaptureError(reason) from exc
        except RetryableStageCaptureError as exc:
            self._discard_retryable_attempt(
                gate,
                attempt=attempt,
                current_stage_id=current_stage_id,
                reason=str(exc),
            )
            raise
        except FinalSessionStorageError as exc:
            reason = f"non-retryable final-session storage failure: {exc}"
            if attempt is not None:
                try:
                    attempt.discard(reason=reason)
                except RuntimeError:
                    pass
            gate.fail_session()
            try:
                state.stager.discard(reason=reason)
            except Exception as cleanup_error:
                exc.add_note(
                    "final-session cleanup also failed with "
                    f"{type(cleanup_error).__name__}"
                )
            with self._state_lock:
                self._states.pop(session_id, None)
            raise
        except Exception as exc:
            reason = f"stage capture failed: {type(exc).__name__}: {exc}"
            self._discard_retryable_attempt(
                gate,
                attempt=attempt,
                current_stage_id=current_stage_id,
                reason=reason,
            )
            raise RetryableStageCaptureError(reason) from exc

    @staticmethod
    def _discard_retryable_attempt(
        gate: StageRecordingGate,
        *,
        attempt: StageAttemptSpool | None,
        current_stage_id: str | None,
        reason: str,
    ) -> None:
        if attempt is not None:
            try:
                attempt.discard(reason=reason)
            except RuntimeError:
                pass
        if current_stage_id is not None:
            gate.cancel_current_stage()

    def _finalize_session(
        self, session_id: str, state: _LiveCaptureState
    ) -> LiveHardwareSessionResult:
        acquisition = AcquisitionResult(
            session_id=session_id,
            outcome=AcquisitionOutcome.COMPLETED,
            frames_stored=sum(
                window.frame_count for window in state.stager.stage_windows
            ),
            integrity_events=tuple(state.integrity_events),
            reconstructed_frames=tuple(state.reconstructed_frames),
        )
        try:
            raw_frames = state.stager.staged_frames()
            processing_frames = tuple(
                sorted(
                    (*raw_frames, *state.reconstructed_frames),
                    key=lambda frame: frame.host_monotonic_ns,
                )
            )
        except Exception as exc:
            return self._discard_final_session(
                session_id,
                state,
                acquisition,
                reason=f"staged session read failed: {type(exc).__name__}",
                ui_failure=processing_failed(),
            )
        try:
            decision = state.quality_gate.evaluate(
                session_id=session_id, frames=processing_frames
            )
        except Exception as exc:
            return self._discard_final_session(
                session_id,
                state,
                acquisition,
                reason=f"hardware quality evaluation failed: {type(exc).__name__}",
                ui_failure=processing_failed(),
            )
        decision_value = getattr(decision.validity, "value", decision.validity)
        reason_codes = tuple(getattr(decision, "reasons", ()))
        reason = "; ".join(reason_codes) or None
        if decision_value == SessionValidity.INVALID.value:
            return self._discard_final_session(
                session_id,
                state,
                acquisition,
                reason=reason or "hardware quality gate failed",
                ui_failure=from_quality_reasons(
                    reason_codes, fallback_reason=reason
                ),
            )
        try:
            physical_session = getattr(decision, "physical_session", None)
            if physical_session is not None:
                processing_metadata = dict(
                    getattr(decision, "processing_metadata", None) or {}
                )
                processing_metadata["communication_integrity"] = {
                    "policy_version": "do-p4864-valid-signal-continuity/1",
                    "maximum_no_valid_signal_ns": self._maximum_no_valid_signal_ns,
                    "reconstructed_frame_count": len(
                        state.reconstructed_frames
                    ),
                    "events": [
                        {
                            "event_index": event.event_index,
                            "failure_kind": event.failure_kind,
                            "invalid_frame_count": event.invalid_frame_count,
                            "discarded_bytes": event.discarded_bytes,
                            "preceding_source_index": event.preceding_source_index,
                            "following_source_index": event.following_source_index,
                            "valid_signal_gap_ns": event.valid_signal_gap_ns,
                            "reconstructed_frame_count": event.reconstructed_frame_count,
                            "resolution": event.resolution,
                        }
                        for event in state.integrity_events
                    ],
                }
                state.stager.stage_derived_observation(
                    physical_session, processing_metadata=processing_metadata
                )
            state.stager.commit_valid(ended_at_ns=self._wall_time_ns())
        except Exception as exc:
            return self._discard_final_session(
                session_id,
                state,
                acquisition,
                reason=f"valid-session finalization failed: {type(exc).__name__}",
                ui_failure=finalization_failed(),
            )
        with self._state_lock:
            self._states.pop(session_id, None)
        return LiveHardwareSessionResult(
            acquisition,
            SessionValidity.VALID,
            None,
            True,
            None,
            state.stager.stage_windows,
        )

    def _discard_final_session(
        self,
        session_id: str,
        state: _LiveCaptureState,
        acquisition: AcquisitionResult,
        *,
        reason: str,
        ui_failure,
    ) -> LiveHardwareSessionResult:
        try:
            state.stager.discard(reason=reason)
        except Exception as cleanup_error:
            reason = (
                f"{reason}; temporary cleanup failed: {type(cleanup_error).__name__}"
            )
        with self._state_lock:
            self._states.pop(session_id, None)
        return LiveHardwareSessionResult(
            acquisition,
            SessionValidity.INVALID,
            reason,
            False,
            ui_failure,
            state.stager.stage_windows,
        )


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
