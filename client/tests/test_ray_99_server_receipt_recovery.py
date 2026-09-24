from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from client.sync.subject_recovery import SubjectRecoveryService
from shared.contracts.client_sync import FormalUploadEnvelope
from shared.contracts.cloud import (
    ConsentCreateRequest, ExternalIdentifierInput, SessionVersions,
    SubjectCreateRequest, SubjectSummary, TestProtocol,
)
from shared.contracts.identity_recovery import RecoveryCaseSummary


class Store:
    def __init__(self, envelope):
        self.envelope = envelope
        self.authorization = None

    def subject_recovery_candidates(self):
        return (str(self.envelope.session_id),)

    def sync_handoff_envelope(self, session_id):
        return self.envelope

    def authorize_subject_recovery(self, authorization):
        self.authorization = authorization


class Client:
    def __init__(self, cloud_subject, now):
        self.cloud_subject = cloud_subject
        self.now = now
        self.case_id = uuid4()
        self.receipt_id = uuid4()
        self.status = "PENDING"

    def resolve_subject(self, token, request):
        return SubjectSummary(
            subject_uuid=self.cloud_subject, external_id_masked="***0731", conflict=True,
        )

    def create_recovery_case(self, token, request, key):
        return self.get_recovery_case(token, self.case_id, request.session_id)

    def get_recovery_case(self, token, case_id, session_id=None):
        return RecoveryCaseSummary(
            case_id=case_id, session_id=session_id or self.session_id,
            status=self.status, masked_clue="***0731", created_at=self.now,
            receipt_id=self.receipt_id if self.status == "MATCHED" else None,
            receipt_expires_at=self.now + timedelta(minutes=15) if self.status == "MATCHED" else None,
            platform_ticket_sha256="a" * 64 if self.status == "MATCHED" else None,
        )


class Tokens:
    def current_access_token(self):
        return "access"

    def refresh(self):
        return None


class Signer:
    def __init__(self):
        self.requests = []

    def sign(self, request, *, consent_record_id, granted_at):
        self.requests.append(request)
        return "fresh-terminal-signature"


def fixture():
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    local, cloud, terminal = uuid4(), uuid4(), uuid4()
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
            consent_record_id=uuid4(), subject_uuid=local, policy_version="institution-screening/1",
            purpose_codes=("SCREENING", "ALGORITHM_RESEARCH"), data_categories=("SCREENING",),
            granted_at=now - timedelta(days=1), evidence_type="OPERATOR_CONFIRMED",
            terminal_signature="original-terminal-signature",
        ),
        client_installation_id=terminal, hardware_asset_id=uuid4(), site_id=None,
        test_protocol=TestProtocol(id="screening", version="1"),
        versions=SessionVersions(
            app="0.1", protocol_profile="1", payload_schema="raw-segment/1", calibration="1",
        ),
        started_at=now - timedelta(days=1),
    )
    store, client, signer = Store(envelope), Client(cloud, now), Signer()
    client.session_id = envelope.session_id
    service = SubjectRecoveryService(
        store=store, client=client, tokens=Tokens(), signer=signer,
        tenant_id=str(uuid4()), terminal_id=str(terminal),
        operator_account_id=str(uuid4()), now=lambda: now,
    )
    return service, store, client, signer


def test_pending_server_case_never_enables_consent():
    service, store, client, signer = fixture()
    preview = service.prepare(store.envelope.session_id)
    assert preview.status == "PENDING"
    with pytest.raises(ValueError):
        service.authorize(preview, evidence_type="SUBJECT_CONFIRMED",
                          necessary_processing_accepted=True, research_accepted=False)
    assert store.authorization is None
    assert signer.requests == []


def test_matched_receipt_requires_active_subject_consent_and_preserves_envelope():
    service, store, client, signer = fixture()
    client.status = "MATCHED"
    original = store.envelope
    preview = service.prepare(original.session_id)
    assert preview.receipt_id == client.receipt_id
    with pytest.raises(ValueError):
        service.authorize(preview, evidence_type="SUBJECT_CONFIRMED",
                          necessary_processing_accepted=False, research_accepted=False)
    authorization = service.authorize(
        preview, evidence_type="REPRESENTATIVE_CONFIRMED",
        necessary_processing_accepted=True, research_accepted=False,
    )
    assert authorization.schema_version == "subject-recovery/2"
    assert authorization.case_id == client.case_id
    assert authorization.receipt_id == client.receipt_id
    assert authorization.replacement_consent.evidence_type == "REPRESENTATIVE_CONFIRMED"
    assert authorization.replacement_consent.purpose_codes == ("SCREENING",)
    assert signer.requests[0].evidence_type == "REPRESENTATIVE_CONFIRMED"
    assert store.envelope == original
