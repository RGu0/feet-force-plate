from __future__ import annotations

from client.app.institution_store import InstitutionLocalStore
from client.app.live_physical_workflow import InstitutionLiveSessions, LivePhysicalProcessor
from client.local_analysis.service import ProcessingStatus
from client.spool.state_store import SensitiveBlobCodec, StateStore
from client.workflow.consent import ConsentRequest
from client.workflow.models import ScreeningParticipantContext
from client.workflow.participant import AnalysisProfile, CreateSubjectRequest
from client.workflow.protocol import default_standard_protocol


class _Key:
    def get_key(self) -> bytes:
        return b"l" * 32


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
