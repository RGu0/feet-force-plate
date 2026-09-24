"""Operator-controlled recovery of a cloud subject UUID collision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from client.spool.state_store import StateStore
from client.workflow.consent import ConsentEvidenceSigner, ConsentRequest
from shared.contracts.client_sync import (
    SubjectRecoveryAuthorization,
    canonical_sha256,
)
from shared.contracts.cloud import SubjectResolveRequest, SubjectSummary
from shared.contracts.identity_recovery import (
    RecoveryCaseCreateRequest, RecoveryCaseSummary,
)

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
    case_id: UUID
    status: str
    receipt_id: UUID | None
    receipt_expires_at: datetime | None
    original_envelope_sha256: str
    platform_ticket_sha256: str | None


class RecoveryLookupError(ValueError):
    """Safe reason for a failed operator-side cloud identity lookup."""

    def __init__(self, reason: str) -> None:
        super().__init__("cloud subject is not recoverable")
        self.error_code = reason


def _mask_identifier(value: str) -> str:
    return "***" + value[-4:] if value else "***"


class SubjectRecoveryService:
    """Use a server-issued match before fresh subject consent releases a handoff."""

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
        now=lambda: datetime.now(UTC),
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

    def now(self) -> datetime:
        """Current time used for a displayed receipt's expiry gate."""
        return self._now()

    def prepare(self, session_id: UUID) -> RecoveryPreview:
        if not any(
            UUID(stored_id) == session_id
            for stored_id in self._store.subject_recovery_candidates()
        ):
            raise ValueError("session is not awaiting controlled recovery")
        envelope = self._store.sync_handoff_envelope(str(session_id))
        external = envelope.subject.external_identifier
        if external is None:
            raise ValueError("session has no institution identifier for verification")
        summary = self._resolve_subject(envelope)
        if summary is None:
            raise RecoveryLookupError("cloud-not-found")
        if summary.subject_uuid == envelope.subject.subject_uuid:
            raise RecoveryLookupError("cloud-already-matches-local")
        if summary.external_identifier_id is None:
            raise RecoveryLookupError("cloud-identifier-binding-unavailable")
        request = RecoveryCaseCreateRequest(
            session_id=session_id,
            original_subject_uuid=envelope.subject.subject_uuid,
            cloud_subject_uuid=summary.subject_uuid,
            envelope_sha256=canonical_sha256(envelope),
            identifier_issuer=external.issuer,
            identifier_type=external.id_type,
            external_identifier_id=summary.external_identifier_id,
            terminal_id=UUID(self._terminal_id),
        )
        case = self._case(request)
        if case.session_id != session_id:
            raise RecoveryLookupError("server-case-session-mismatch")
        status = case.status
        receipt_id = case.receipt_id
        expires_at = case.receipt_expires_at
        if status == "MATCHED" and (receipt_id is None or expires_at is None or expires_at <= self._now()):
            status, receipt_id, expires_at = "EXPIRED", None, None
        return RecoveryPreview(
            session_id=session_id,
            local_subject_uuid=envelope.subject.subject_uuid,
            cloud_subject_uuid=summary.subject_uuid,
            local_identifier_masked=_mask_identifier(external.external_id),
            cloud_identifier_masked=case.masked_clue or summary.external_id_masked,
            research_available="ALGORITHM_RESEARCH" in envelope.consent.purpose_codes,
            case_id=case.case_id, status=status, receipt_id=receipt_id,
            receipt_expires_at=expires_at,
            original_envelope_sha256=request.envelope_sha256,
            platform_ticket_sha256=case.platform_ticket_sha256,
        )

    def authorize(
        self,
        preview: RecoveryPreview,
        *,
        evidence_type: str,
        necessary_processing_accepted: bool,
        research_accepted: bool,
    ) -> SubjectRecoveryAuthorization:
        if evidence_type not in {"SUBJECT_CONFIRMED", "REPRESENTATIVE_CONFIRMED"}:
            raise ValueError("subject or authorized representative confirmation is required")
        if not necessary_processing_accepted:
            raise ValueError("necessary consent is required")
        current = self.prepare(preview.session_id)
        if (
            current != preview or current.status != "MATCHED"
            or current.receipt_id is None or current.platform_ticket_sha256 is None
        ):
            raise ValueError("server identity verification changed or is incomplete")
        if current.receipt_expires_at is None or current.receipt_expires_at <= self._now():
            raise ValueError("server identity receipt expired")
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
            evidence_type=evidence_type,
        )
        from shared.contracts.cloud import ConsentCreateRequest

        consent = ConsentCreateRequest(
            consent_record_id=consent_id,
            subject_uuid=preview.cloud_subject_uuid,
            policy_version=request.policy_version,
            purpose_codes=request.purpose_codes,
            data_categories=request.data_categories,
            granted_at=confirmed_at,
            evidence_type=evidence_type,
            terminal_signature=self._signer.sign(
                request, consent_record_id=consent_id.hex, granted_at=confirmed_at,
            ),
        )
        authorization = SubjectRecoveryAuthorization(
            schema_version="subject-recovery/2",
            session_id=preview.session_id,
            original_envelope_sha256=canonical_sha256(envelope),
            original_subject_uuid=preview.local_subject_uuid,
            cloud_subject_uuid=preview.cloud_subject_uuid,
            replacement_consent=consent,
            operator_account_id=self._operator_account_id,
            confirmed_at=confirmed_at,
            cloud_external_id_masked=preview.cloud_identifier_masked,
            case_id=preview.case_id,
            receipt_id=preview.receipt_id,
            receipt_expires_at=preview.receipt_expires_at,
            platform_ticket_sha256=preview.platform_ticket_sha256,
        )
        self._store.authorize_subject_recovery(authorization)
        return authorization

    def _case(self, request: RecoveryCaseCreateRequest) -> RecoveryCaseSummary:
        key = f"recovery-case:{request.session_id}"
        try:
            return self._client.create_recovery_case(
                self._tokens.current_access_token(), request, key,
            )
        except UploadAuthenticationRequired:
            self._tokens.refresh()
            return self._client.create_recovery_case(
                self._tokens.current_access_token(), request, key,
            )

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
