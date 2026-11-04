from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from client.sync.subject_recovery import RecoveryLookupError, SubjectRecoveryService
from shared.contracts.client_sync import FormalUploadEnvelope
from shared.contracts.cloud import (
    ConsentCreateRequest, ExternalIdentifierInput, SessionVersions,
    SubjectCreateRequest, SubjectSummary, TestProtocol,
)
from shared.contracts.identity_recovery import RecoveryCaseSummary


class _Store:
    def __init__(self, envelope):
        self.envelope = envelope
        self.authorization = None

    def subject_recovery_candidates(self):
        return (str(self.envelope.session_id),) if self.authorization is None else ()

    def sync_handoff_envelope(self, session_id):
        assert session_id == str(self.envelope.session_id)
        return self.envelope

    def authorize_subject_recovery(self, authorization):
        self.authorization = authorization


class _Client:
    def __init__(self, cloud_uuid):
        self.cloud_uuid = cloud_uuid
        self.status = "PENDING"
        self.case_id = uuid4()
        self.identifier_id = uuid4()
        self.receipt_id = uuid4()
        self.session_id = None

    def resolve_subject(self, token, request):
        assert token == "access"
        assert request.external_id == "2024-0731"
        if self.cloud_uuid is None:
            return None
        return SubjectSummary(
            subject_uuid=self.cloud_uuid, external_id_masked="***0731", conflict=True,
            external_identifier_id=self.identifier_id,
        )

    def create_recovery_case(self, token, request, key):
        self.session_id = request.session_id
        return RecoveryCaseSummary(
            case_id=self.case_id, session_id=request.session_id,
            status=self.status, masked_clue="***0731",
            created_at=datetime(2026, 9, 23, 12, tzinfo=UTC),
            receipt_id=self.receipt_id if self.status == "MATCHED" else None,
            receipt_expires_at=(datetime(2026, 9, 23, 12, tzinfo=UTC) + timedelta(minutes=15))
            if self.status == "MATCHED" else None,
            platform_ticket_sha256="a" * 64 if self.status == "MATCHED" else None,
        )


class _Tokens:
    def current_access_token(self):
        return "access"


class _Signer:
    def __init__(self):
        self.requests = []

    def sign(self, request, *, consent_record_id, granted_at):
        self.requests.append(request)
        assert consent_record_id
        assert granted_at.tzinfo is not None
        return "fresh-terminal-signature"


def _service(*, verified_identity=True):
    local = uuid4()
    cloud = uuid4()
    envelope = FormalUploadEnvelope(
        session_id=uuid4(),
        subject=SubjectCreateRequest(
            subject_uuid=local,
            external_identifier=ExternalIdentifierInput(
                issuer="institution-ui", id_type="institution_record",
                external_id="2024-0731",
            ),
        ),
        consent=ConsentCreateRequest(
            consent_record_id=uuid4(), subject_uuid=local,
            policy_version="institution-screening/1",
            purpose_codes=("SCREENING", "ALGORITHM_RESEARCH"),
            data_categories=("SCREENING",),
            granted_at=datetime(2026, 9, 22, tzinfo=UTC),
            evidence_type="OPERATOR_CONFIRMED",
            terminal_signature="original-terminal-signature",
        ),
        client_installation_id=uuid4(), hardware_asset_id=uuid4(), site_id=None,
        test_protocol=TestProtocol(id="screening", version="1"),
        versions=SessionVersions(
            app="0.1.0", protocol_profile="1", payload_schema="raw-segment/1",
            calibration="1",
        ),
        started_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    store = _Store(envelope)
    client = _Client(cloud)
    client.status = "MATCHED" if verified_identity else "PENDING"
    signer = _Signer()
    service = SubjectRecoveryService(
        store=store, client=client, tokens=_Tokens(), signer=signer,
        tenant_id=str(uuid4()), terminal_id=str(envelope.client_installation_id),
        operator_account_id=str(uuid4()),
        now=lambda: datetime(2026, 9, 23, 12, tzinfo=UTC),
    )
    return service, store, client, signer


def test_masked_identifier_without_independent_identity_evidence_fails_closed():
    service, store, _, signer = _service(verified_identity=False)
    preview = service.prepare(store.envelope.session_id)
    assert preview.status == "PENDING"
    with pytest.raises(ValueError):
        service.authorize(
            preview, evidence_type="SUBJECT_CONFIRMED",
            necessary_processing_accepted=True, research_accepted=False,
        )
    assert store.authorization is None
    assert signer.requests == []


def test_operator_must_reconfirm_identity_and_necessary_processing():
    service, store, _, signer = _service()
    preview = service.prepare(store.envelope.session_id)
    for evidence_type, necessary in (("OPERATOR_CONFIRMED", True), ("SUBJECT_CONFIRMED", False)):
        with pytest.raises(ValueError):
            service.authorize(
                preview, evidence_type=evidence_type,
                necessary_processing_accepted=necessary, research_accepted=False,
            )
    assert store.authorization is None
    assert signer.requests == []


def test_new_signed_consent_targets_cloud_subject_and_keeps_original():
    service, store, _, signer = _service()
    original = store.envelope
    preview = service.prepare(original.session_id)
    assert preview.local_identifier_masked == "***0731"
    authorization = service.authorize(
        preview, evidence_type="SUBJECT_CONFIRMED",
        necessary_processing_accepted=True, research_accepted=False,
    )
    assert authorization.cloud_subject_uuid == preview.cloud_subject_uuid
    assert authorization.replacement_consent.subject_uuid == preview.cloud_subject_uuid
    assert authorization.replacement_consent.purpose_codes == ("SCREENING",)
    assert authorization.receipt_id == preview.receipt_id
    assert signer.requests[0].subject_uuid == str(preview.cloud_subject_uuid)
    assert store.envelope == original


def test_remote_subject_change_requires_new_preview():
    service, store, client, signer = _service()
    preview = service.prepare(store.envelope.session_id)
    client.cloud_uuid = uuid4()
    with pytest.raises(ValueError, match="changed"):
        service.authorize(
            preview, evidence_type="SUBJECT_CONFIRMED",
            necessary_processing_accepted=True, research_accepted=False,
        )
    assert store.authorization is None
    assert signer.requests == []


def test_lookup_distinguishes_missing_cloud_subject_from_existing_local_mapping():
    service, store, client, _ = _service()
    client.cloud_uuid = None
    with pytest.raises(RecoveryLookupError) as missing:
        service.prepare(store.envelope.session_id)
    assert missing.value.error_code == "cloud-not-found"

    client.cloud_uuid = store.envelope.subject.subject_uuid
    with pytest.raises(RecoveryLookupError) as matching:
        service.prepare(store.envelope.session_id)
    assert matching.value.error_code == "cloud-already-matches-local"
