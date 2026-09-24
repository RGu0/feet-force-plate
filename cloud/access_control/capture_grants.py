"""Issue opaque credentials for server-prebound future capture sessions."""

import secrets
import hashlib
from uuid import UUID, uuid4

from cloud.ingestion.principal import IngestionPrincipal
from cloud.api.access_auth import PlatformAccessContext
from cloud.api.errors import TenantAccessDenied
from shared.contracts.access_control import PlatformRole
from shared.contracts.capture_grants import (
    CaptureGrant,
    CaptureGrantBatchRequest,
    CaptureGrantBatchResponse,
    RetireCaptureGrantRequest,
    UploadMigrationPermitRequest,
    MigrationPermitResponse,
)


class CaptureGrantService:
    def __init__(self, repository) -> None:
        self._repository = repository

    async def approve_migration(
        self, context: PlatformAccessContext, request: UploadMigrationPermitRequest,
    ) -> MigrationPermitResponse:
        # Revalidate at the service boundary as internal callers can construct
        # models without validation. Never forward their unvalidated text to audit.
        request = UploadMigrationPermitRequest.model_validate(request.model_dump())
        decision = None
        if PlatformRole.OWNER not in context.roles:
            decision = "OWNER_REQUIRED"
        elif request.identity_conflict:
            # RAY-99 has no persisted, independently verifiable mapping source
            # here yet. A caller-provided reference is not reconciliation proof.
            decision = "RECONCILIATION_UNVERIFIABLE"
        elif not all((request.local_valid_reviewed, request.immutable_manifest_reviewed,
                      request.original_consent_reviewed, request.historical_authorization_reviewed)):
            decision = "REVIEW_INCOMPLETE"
        if decision is not None:
            await self._repository.audit_migration_denial(context, request, decision)
            raise TenantAccessDenied("migration approval requirements not satisfied")
        token = secrets.token_urlsafe(32)
        try:
            await self._repository.insert_migration_permit(
                context, request, hashlib.sha256(token.encode()).digest(),
            )
        except TenantAccessDenied:
            # Separate transaction survives rollback of rejected issuance.
            await self._repository.audit_migration_denial(context, request, "BINDING_OR_OWNER_REJECTED")
            raise
        return MigrationPermitResponse(session_id=request.session_id, token=token)

    async def issue(self, context: IngestionPrincipal, count: int) -> CaptureGrantBatchResponse:
        context.ensure_can_start_new()
        count = CaptureGrantBatchRequest(count=count).count
        grants = tuple(
            CaptureGrant(session_id=uuid4(), token=secrets.token_urlsafe(32))
            for _ in range(count)
        )
        return await self._repository.issue_capture_grants(context, grants)

    async def retire(self, context: IngestionPrincipal, session_id: UUID, reason: str) -> None:
        context.ensure_can_start_new()
        request = RetireCaptureGrantRequest(session_id=session_id, reason=reason)
        await self._repository.retire_capture_grant(context, request.session_id, request.reason)
