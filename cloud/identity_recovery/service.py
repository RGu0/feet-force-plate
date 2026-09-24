"""Terminal-authorized immutable case entrypoint."""

from __future__ import annotations

import hashlib
from uuid import UUID

from cloud.api.errors import RequestContractError, TenantAccessDenied
from cloud.ingestion.principal import IngestionPrincipal
from shared.contracts.client_sync import canonical_sha256
from shared.contracts.identity_recovery import RecoveryCaseCreateRequest, RecoveryCaseSummary

from .models import RecoveryCaseRecord


class IdentityRecoveryService:
    def __init__(self, repository) -> None:
        self._repository = repository

    @staticmethod
    def _summary(record: RecoveryCaseRecord) -> RecoveryCaseSummary:
        return RecoveryCaseSummary(
            case_id=record.case_id, session_id=record.request.session_id,
            status=record.status, masked_clue=record.masked_clue, created_at=record.created_at,
        )

    async def create_case(
        self, context: IngestionPrincipal, request: RecoveryCaseCreateRequest, idempotency_key: str,
    ) -> RecoveryCaseSummary:
        context.ensure_can_upload()
        if request.terminal_id != context.terminal_id:
            raise TenantAccessDenied("terminal does not own recovery case")
        if not idempotency_key or len(idempotency_key) > 128:
            raise RequestContractError("invalid recovery idempotency key")
        key_sha256 = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        request_sha256 = canonical_sha256(request)
        record = await self._repository.create_case(
            context.tenant_id, context.terminal_id, request, key_sha256, request_sha256,
        )
        return self._summary(record)

    async def get_case(self, context: IngestionPrincipal, case_id: UUID) -> RecoveryCaseSummary:
        context.ensure_can_upload()
        return self._summary(
            await self._repository.get_case(context.tenant_id, context.terminal_id, case_id)
        )
