"""Operator-controlled recovery of a cloud subject UUID collision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID, uuid4

from client.spool.state_store import StateStore
from client.workflow.consent import ConsentEvidenceSigner, ConsentRequest
from shared.contracts.client_sync import (
    SubjectRecoveryAuthorization,
    canonical_sha256,
)
from shared.contracts.cloud import SubjectResolveRequest, SubjectSummary

from .persistent_upload import (
    IngestionClient,
    UploadAuthenticationRequired,
    UploadTokenProvider,
)


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    session_id: UUID
    local_identifier_masked: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryPreview:
    session_id: UUID
    local_subject_uuid: UUID
    cloud_subject_uuid: UUID
    local_identifier_masked: str
    cloud_identifier_masked: str | None
    research_available: bool


def _mask_identifier(value: str) -> str:
    return "***" + value[-4:] if value else "***"


class SubjectRecoveryService:
    """Require fresh server lookup and explicit human attestation before release."""

    def __init__(
        self,
        *,
        store: StateStore,
        client: IngestionClient,
        tokens: UploadTokenProvider,
        signer: ConsentEvidenceSigner,
        tenant_id: str,
        terminal_id: str,
        operator_account_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._client = client
        self._tokens = tokens
        self._signer = signer
        self._tenant_id = tenant_id
        self._terminal_id = terminal_id
        self._operator_account_id = UUID(operator_account_id)
        self._now = now

    def candidates(self) -> tuple[RecoveryCandidate, ...]:
        result = []
        for session_id in self._store.subject_recovery_candidates():
            envelope = self._store.sync_handoff_envelope(session_id)
            external = envelope.subject.external_identifier
            if external is None:
                continue
            result.append(RecoveryCandidate(
                session_id=envelope.session_id,
                local_identifier_masked=_mask_identifier(external.external_id),
                started_at=envelope.started_at,
            ))
        return tuple(result)

    def prepare(self, session_id: UUID) -> RecoveryPreview:
        if str(session_id) not in self._store.subject_recovery_candidates():
            raise ValueError("session is not awaiting controlled recovery")
        envelope = self._store.sync_handoff_envelope(str(session_id))
        external = envelope.subject.external_identifier
        if external is None:
            raise ValueError("session has no institution identifier for verification")
        summary = self._resolve_subject(envelope)
        if summary is None or summary.subject_uuid == envelope.subject.subject_uuid:
            raise ValueError("cloud does not report a recoverable subject collision")
        return RecoveryPreview(
            session_id=session_id,
            local_subject_uuid=envelope.subject.subject_uuid,
            cloud_subject_uuid=summary.subject_uuid,
            local_identifier_masked=_mask_identifier(external.external_id),
            cloud_identifier_masked=summary.external_id_masked,
            research_available="ALGORITHM_RESEARCH" in envelope.consent.purpose_codes,
        )

    def authorize(
        self,
        preview: RecoveryPreview,
        *,
        same_person_confirmed: bool,
        necessary_processing_accepted: bool,
        research_accepted: bool,
    ) -> SubjectRecoveryAuthorization:
        if not same_person_confirmed or not necessary_processing_accepted:
            raise ValueError("identity verification and necessary consent are required")
        current = self.prepare(preview.session_id)
        if current != preview:
            raise ValueError("cloud subject changed; repeat operator verification")
        if research_accepted and not current.research_available:
            raise ValueError("research consent is not part of this local policy")
        envelope = self._store.sync_handoff_envelope(str(preview.session_id))
        original_purposes = envelope.consent.purpose_codes
        purposes = tuple(p for p in original_purposes if p != "ALGORITHM_RESEARCH")
        if research_accepted and "ALGORITHM_RESEARCH" in original_purposes:
            purposes += ("ALGORITHM_RESEARCH",)
        confirmed_at = self._now()
        consent_id = uuid4()
        request = ConsentRequest(
            tenant_id=self._tenant_id,
            terminal_id=self._terminal_id,
            subject_uuid=str(preview.cloud_subject_uuid),
            policy_version=envelope.consent.policy_version,
            purpose_codes=purposes,
            data_categories=envelope.consent.data_categories,
            evidence_type="OPERATOR_CONFIRMED",
        )
        from shared.contracts.cloud import ConsentCreateRequest

        consent = ConsentCreateRequest(
            consent_record_id=consent_id,
            subject_uuid=preview.cloud_subject_uuid,
            policy_version=request.policy_version,
            purpose_codes=request.purpose_codes,
            data_categories=request.data_categories,
            granted_at=confirmed_at,
            evidence_type="OPERATOR_CONFIRMED",
            terminal_signature=self._signer.sign(
                request, consent_record_id=consent_id.hex, granted_at=confirmed_at,
            ),
        )
        authorization = SubjectRecoveryAuthorization(
            session_id=preview.session_id,
            original_envelope_sha256=canonical_sha256(envelope),
            original_subject_uuid=preview.local_subject_uuid,
            cloud_subject_uuid=preview.cloud_subject_uuid,
            replacement_consent=consent,
            operator_account_id=self._operator_account_id,
            confirmed_at=confirmed_at,
            cloud_external_id_masked=preview.cloud_identifier_masked,
        )
        self._store.authorize_subject_recovery(authorization)
        return authorization

    def _resolve_subject(self, envelope) -> SubjectSummary | None:
        external = envelope.subject.external_identifier
        if external is None:
            raise ValueError("institution identifier is required for recovery")
        request = SubjectResolveRequest.model_validate(external.model_dump())
        try:
            return self._client.resolve_subject(
                self._tokens.current_access_token(), request
            )
        except UploadAuthenticationRequired:
            self._tokens.refresh()
            return self._client.resolve_subject(
                self._tokens.current_access_token(), request
            )
