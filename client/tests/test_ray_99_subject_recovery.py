from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from client.sync.subject_recovery import SubjectRecoveryService
from shared.contracts.client_sync import FormalUploadEnvelope
from shared.contracts.cloud import (
    ConsentCreateRequest, ExternalIdentifierInput, SessionVersions,
    SubjectCreateRequest, SubjectSummary, TestProtocol,
)


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

    def create_subject(self, token, request, key):
        assert token == "access"
        assert request.external_identifier.external_id == "2024-0731"
        assert key.startswith("subject-recovery:")
        return SubjectSummary(
            subject_uuid=self.cloud_uuid, external_id_masked="***0731", conflict=True
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


def _service():
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
    signer = _Signer()
    service = SubjectRecoveryService(
        store=store, client=client, tokens=_Tokens(), signer=signer,
        tenant_id=str(uuid4()), terminal_id=str(envelope.client_installation_id),
        operator_account_id=str(uuid4()),
        now=lambda: datetime(2026, 9, 23, 12, tzinfo=UTC),
    )
    return service, store, client, signer


def test_operator_must_reconfirm_identity_and_necessary_processing():
    service, store, _, signer = _service()
    preview = service.prepare(store.envelope.session_id)
    for same_person, necessary in ((False, True), (True, False)):
        with pytest.raises(ValueError):
            service.authorize(
                preview, same_person_confirmed=same_person,
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
        preview, same_person_confirmed=True,
        necessary_processing_accepted=True, research_accepted=False,
    )
    assert authorization.cloud_subject_uuid == preview.cloud_subject_uuid
    assert authorization.replacement_consent.subject_uuid == preview.cloud_subject_uuid
    assert authorization.replacement_consent.purpose_codes == ("SCREENING",)
    assert signer.requests[0].subject_uuid == str(preview.cloud_subject_uuid)
    assert store.envelope == original


def test_remote_subject_change_requires_new_preview():
    service, store, client, signer = _service()
    preview = service.prepare(store.envelope.session_id)
    client.cloud_uuid = uuid4()
    with pytest.raises(ValueError, match="changed"):
        service.authorize(
            preview, same_person_confirmed=True,
            necessary_processing_accepted=True, research_accepted=False,
        )
    assert store.authorization is None
    assert signer.requests == []
