from __future__ import annotations

from datetime import UTC, datetime
import json
from uuid import UUID

from client.app.institution_store import InstitutionLocalStore
from client.reporting.models import BasicReportDocument, ReportStatus
from client.workflow.consent import ConsentPolicy, ConsentRequest, ConsentWorkflow
from client.workflow.participant import (
    AnalysisProfile,
    CreateSubjectRequest,
    ExternalIdType,
    ExternalSubjectIdInput,
    IdentityInput,
)
from client.workflow.protocol import default_standard_protocol
from client.workflow.models import ScreeningParticipantContext


class _Key:
    def get_key(self) -> bytes:
        return b"i" * 32


class _Signer:
    def __init__(self, value: str) -> None:
        self.value = value

    def sign(self, request, *, consent_record_id: str, granted_at: datetime) -> str:
        return self.value


def _subject_with_external_profile_and_identity() -> CreateSubjectRequest:
    return CreateSubjectRequest(
        tenant_id="tenant-1",
        analysis_profile=AnalysisProfile.unknown(),
        external_id=ExternalSubjectIdInput(
            issuer="hospital-a",
            id_type=ExternalIdType.MEDICAL_RECORD_NUMBER,
            external_id="MRN-123",
        ),
        identity=IdentityInput(
            name="受试者甲",
            contact="13800000000",
            government_id="110101199001011234",
        ),
    )


def _consent_request(subject_uuid: str) -> ConsentRequest:
    return ConsentRequest(
        tenant_id="tenant-1",
        terminal_id="terminal-1",
        subject_uuid=subject_uuid,
        policy_version="consent/1",
        purpose_codes=("SCREENING",),
        data_categories=("SCREENING",),
        evidence_type="OPERATOR_CONFIRMED",
    )


def test_institution_store_keeps_subject_consent_session_and_report_out_of_replay_tables(tmp_path) -> None:
    store = InstitutionLocalStore.open(
        tmp_path,
        key_provider=_Key(),
        query_index_key=b"q" * 32,
        consent_signer=_Signer("signed-consent-evidence"),
    )
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


def test_institution_consent_port_routes_workflow_creation_to_consent_storage(tmp_path) -> None:
    store = InstitutionLocalStore.open(
        tmp_path,
        key_provider=_Key(),
        query_index_key=b"q" * 32,
        consent_signer=_Signer("signed-consent-evidence"),
    )
    subject = store.create(
        CreateSubjectRequest(tenant_id="tenant-1", analysis_profile=AnalysisProfile.unknown())
    )
    workflow = ConsentWorkflow(
        tenant_id="tenant-1",
        terminal_id="terminal-1",
        consents=store.consent_port(),
    )
    policy = ConsentPolicy("consent/1", ("SCREENING",), ("SCREENING",))

    workflow.resolve(subject.subject_uuid, policy)
    receipt = workflow.confirm(necessary_accepted=True, research_accepted=False)

    assert receipt.subject_uuid == subject.subject_uuid
    assert store.find_valid(
        tenant_id="tenant-1",
        subject_uuid=subject.subject_uuid,
        policy=policy,
    ) == receipt


def test_upload_exports_preserve_uuid_and_exclude_government_id(tmp_path) -> None:
    store = InstitutionLocalStore.open(
        tmp_path,
        key_provider=_Key(),
        query_index_key=b"q" * 32,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        consent_signer=_Signer("signed-consent-evidence"),
    )
    subject = store.create(_subject_with_external_profile_and_identity())
    consent = store.create_consent(_consent_request(subject.subject_uuid))

    subject_request = store.subject_upload_request(subject.subject_uuid)
    consent_request = store.consent_upload_request(consent.consent_record_id)

    assert subject_request.subject_uuid == UUID(subject.subject_uuid)
    assert subject_request.identity_profile.model_dump() == {
        "display_name": "受试者甲", "contact": "13800000000"
    }
    assert "government_id" not in subject_request.model_dump_json()
    assert consent_request.granted_at == datetime(2026, 8, 11, tzinfo=UTC)
    assert consent_request.evidence_type == "OPERATOR_CONFIRMED"
    assert consent_request.terminal_signature == "signed-consent-evidence"


def test_find_valid_requires_immutable_consent_evidence(tmp_path) -> None:
    store = InstitutionLocalStore.open(
        tmp_path,
        key_provider=_Key(),
        query_index_key=b"q" * 32,
        now=lambda: datetime(2026, 8, 11, tzinfo=UTC),
        consent_signer=_Signer("signed-consent-evidence"),
    )
    subject = store.create(
        CreateSubjectRequest(tenant_id="tenant-1", analysis_profile=AnalysisProfile.unknown())
    )
    old_consent_id = "a" * 32
    old_payload = {
        "consent_record_id": old_consent_id,
        "tenant_id": "tenant-1",
        "subject_uuid": subject.subject_uuid,
        "policy_version": "consent/1",
        "purpose_codes": ["SCREENING"],
        "data_categories": ["SCREENING"],
    }
    with store.db:
        store.db.execute(
            "INSERT INTO institution_consents VALUES (?,?,?,?)",
            (
                store._lookup("consent", old_consent_id),
                "tenant-1",
                subject.subject_uuid,
                store.codec.encrypt(
                    json.dumps(old_payload).encode(),
                    context=f"consent:{subject.subject_uuid}",
                ),
            ),
        )

    policy = ConsentPolicy("consent/1", ("SCREENING",), ("SCREENING",))

    assert store.find_valid(
        tenant_id="tenant-1", subject_uuid=subject.subject_uuid, policy=policy
    ) is None

    receipt = store.create_consent(_consent_request(subject.subject_uuid))

    assert store.find_valid(
        tenant_id="tenant-1", subject_uuid=subject.subject_uuid, policy=policy
    ) == receipt


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
