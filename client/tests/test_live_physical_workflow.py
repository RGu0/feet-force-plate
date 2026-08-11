from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from client.app.institution_store import InstitutionLocalStore
from client.device.stage_windows import StageRecordingGate
from client.hardware_standardization.do_p4864 import DoP4864StandardizationAdapter
from client.hardware_standardization.models import BaselineReference
from client.hardware_integration.live_physical_workflow import (
    InstitutionLiveSessions,
    LivePhysicalCapture,
    LivePhysicalProcessor,
)
from client.local_analysis.service import ProcessingStatus
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.workflow.consent import ConsentRequest
from client.workflow.models import ScreeningParticipantContext
from client.workflow.participant import AnalysisProfile, CreateSubjectRequest
from client.workflow.protocol import default_standard_protocol


class _Key:
    def get_key(self) -> bytes:
        return b"l" * 32


def test_formal_live_capture_keeps_subject_and_session_identities_distinct(
    tmp_path,
) -> None:
    key = _Key()
    institution = InstitutionLocalStore.open(
        tmp_path / "institution", key_provider=key, query_index_key=b"q" * 32
    )
    physical_store = StateStore(
        tmp_path / "physical.sqlite3", SensitiveBlobCodec(key)
    )
    installation_id = uuid4()
    hardware_asset_id = uuid4()
    try:
        subject = institution.create(
            CreateSubjectRequest(
                tenant_id="tenant-1",
                analysis_profile=AnalysisProfile.unknown(),
            )
        )
        consent = institution.create_consent(
            ConsentRequest(
                tenant_id="tenant-1",
                terminal_id="terminal-1",
                subject_uuid=subject.subject_uuid,
                policy_version="consent/1",
                purpose_codes=("SCREENING",),
                data_categories=("SCREENING",),
                evidence_type="OPERATOR_CONFIRMED",
            )
        )
        protocol = default_standard_protocol().snapshot()
        sessions = InstitutionLiveSessions(institution)
        session_id = sessions.create_session(
            ScreeningParticipantContext(
                subject.subject_uuid, consent.consent_record_id
            ),
            protocol,
        )
        metadata = sessions.metadata(session_id)
        capture = LivePhysicalCapture(
            hardware=None,
            sessions=sessions,
            baseline=None,
            physical_store=physical_store,
            key_provider=key,
            spool_root=tmp_path / "spool",
            latest_frames=None,
            client_installation_id=str(installation_id),
            hardware_asset_id=str(hardware_asset_id),
            site_id=None,
            app_version="0.1.0",
            payload_schema="raw-segment/1",
            calibration_profile="calibration/1",
            wall_time_ns=lambda: 1_786_406_400_000_000_000,
        )
        adapter = DoP4864StandardizationAdapter.observed_compact_8bit()
        reference = BaselineReference(
            schema_version="baseline-reference/1",
            baseline_window_id="formal-live-test",
            layout_digest=adapter.layout.digest,
            zero_offset_count=(0.0,) * (48 * 64),
            noise_mad_count=(0.0,) * (48 * 64),
            rules_version="do-p4864-unloaded-baseline/1",
            threshold_version="do-p4864-quality/1",
            source_digest="a" * 64,
        )

        state = capture._state_for_connection(
            session_id,
            gate=StageRecordingGate(expected_stage_ids=protocol.stage_ids),
            parser=SimpleNamespace(
                profile=SimpleNamespace(version="do-p4864/1")
            ),
            reference=reference,
        )

        assert state.stager.subject_uuid == metadata.subject_uuid
        assert state.stager.subject_uuid != session_id
        assert state.stager.upload_envelope.subject.subject_uuid == UUID(
            metadata.subject_uuid
        )
        assert state.stager.upload_envelope.client_installation_id == installation_id
        assert state.stager.upload_envelope.hardware_asset_id == hardware_asset_id
        assert state.stager.upload_envelope.versions.protocol_profile == "do-p4864/1"
        assert state.stager.upload_envelope.versions.payload_schema == "raw-segment/1"
        assert state.stager.upload_envelope.versions.calibration == "calibration/1"
        assert state.stager.upload_envelope.config_snapshot["stage_ids"] == list(
            protocol.stage_ids
        )
    finally:
        physical_store.close()
        institution.close()


def test_live_physical_processor_refuses_to_issue_a_report_without_four_operator_attestations(tmp_path) -> None:
    key = _Key()
    institution = InstitutionLocalStore.open(
        tmp_path / "institution", key_provider=key, query_index_key=b"q" * 32
    )
    subject = institution.create(
        CreateSubjectRequest(
            tenant_id="tenant-1",
            analysis_profile=AnalysisProfile.unknown(),
        )
    )
    consent = institution.create_consent(
        ConsentRequest(
            tenant_id="tenant-1", terminal_id="terminal-1", subject_uuid=subject.subject_uuid,
            policy_version="consent/1", purpose_codes=("SCREENING",),
            data_categories=("SCREENING",), evidence_type="OPERATOR_CONFIRMED",
        )
    )
    sessions = InstitutionLiveSessions(institution)
    session_id = sessions.create_session(
        ScreeningParticipantContext(subject.subject_uuid, consent.consent_record_id),
        default_standard_protocol().snapshot(),
    )
    processor = LivePhysicalProcessor(
        sessions=sessions,
        physical_store=StateStore(tmp_path / "physical.sqlite3", SensitiveBlobCodec(key)),
        key_provider=key,
        spool_root=tmp_path / "spool",
        reports=institution,
    )

    outcome = processor.process(session_id)

    assert outcome.status is ProcessingStatus.RETRY_REQUIRED
    assert outcome.report is None


def test_live_physical_processor_requires_captured_windows_with_attestations(tmp_path) -> None:
    key = _Key()
    institution = InstitutionLocalStore.open(
        tmp_path / "institution", key_provider=key, query_index_key=b"q" * 32
    )
    subject = institution.create(
        CreateSubjectRequest(
            tenant_id="tenant-1", analysis_profile=AnalysisProfile.unknown()
        )
    )
    consent = institution.create_consent(
        ConsentRequest(
            tenant_id="tenant-1", terminal_id="terminal-1", subject_uuid=subject.subject_uuid,
            policy_version="consent/1", purpose_codes=("SCREENING",),
            data_categories=("SCREENING",), evidence_type="OPERATOR_CONFIRMED",
        )
    )
    sessions = InstitutionLiveSessions(institution)
    session_id = sessions.create_session(
        ScreeningParticipantContext(subject.subject_uuid, consent.consent_record_id),
        default_standard_protocol().snapshot(),
    )
    processor = LivePhysicalProcessor(
        sessions=sessions,
        physical_store=StateStore(tmp_path / "physical.sqlite3", SensitiveBlobCodec(key)),
        key_provider=key,
        spool_root=tmp_path / "spool",
        reports=institution,
    )

    processor.record_attestations(
        session_id,
        (True, True, True, True),
        captured_windows=(),
    )

    outcome = processor.process(session_id)

    assert outcome.status is ProcessingStatus.RETRY_REQUIRED
    assert outcome.report is None
