from __future__ import annotations

from client.app.institution_store import InstitutionLocalStore
from client.reporting.models import BasicReportDocument, ReportStatus
from client.workflow.consent import ConsentRequest
from client.workflow.participant import AnalysisProfile, CreateSubjectRequest
from client.workflow.protocol import default_standard_protocol
from client.workflow.models import ScreeningParticipantContext


class _Key:
    def get_key(self) -> bytes:
        return b"i" * 32


def test_institution_store_keeps_subject_consent_session_and_report_out_of_replay_tables(tmp_path) -> None:
    store = InstitutionLocalStore.open(tmp_path, key_provider=_Key(), query_index_key=b"q" * 32)
    subject = store.create(
        CreateSubjectRequest(tenant_id="tenant-1", analysis_profile=AnalysisProfile.unknown())
    )
    consent = store.create_consent(
        ConsentRequest(
            tenant_id="tenant-1", terminal_id="terminal-1", subject_uuid=subject.subject_uuid,
            policy_version="consent/1", purpose_codes=("SCREENING",),
            data_categories=("SCREENING",), evidence_type="OPERATOR_CONFIRMED",
        )
    )
    session_id = store.create_session(
        ScreeningParticipantContext(subject.subject_uuid, consent.consent_record_id),
        default_standard_protocol().snapshot(),
    )
    store.mark_stage_complete(session_id, "BILATERAL_EYES_OPEN")
    store.finalize(session_id)

    assert store.schema_names() == {
        "institution_consents", "institution_reports", "institution_sessions",
        "institution_stage_completions", "institution_subject_audit", "institution_subjects",
    }
    assert store.session_status(session_id) == "CLOSED"


def test_institution_report_round_trip_is_encrypted(tmp_path) -> None:
    store = InstitutionLocalStore.open(tmp_path, key_provider=_Key(), query_index_key=b"q" * 32)
    report = BasicReportDocument(
        report_id="report-1", version=1, status=ReportStatus.BASIC_READY, kind="BASIC",
        session_id="session-1", analysis_result_id="analysis-1", subject_display_id="匿名",
        captured_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        protocol_id="protocol", protocol_version="1", metrics=(), relative_heatmap=((0.0,),),
        summary="summary", disclaimer="disclaimer", provenance=("v1",),
    )

    store.save_report(report)

    assert "report-1" not in (tmp_path / "institution.sqlite3").read_text(errors="ignore")
    assert BasicReportDocument.from_json(store.load_report("report-1", 1)) == report
