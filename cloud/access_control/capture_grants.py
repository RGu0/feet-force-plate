"""Issue opaque credentials for server-prebound future capture sessions."""

import secrets
from uuid import UUID, uuid4

from cloud.ingestion.principal import IngestionPrincipal
from shared.contracts.capture_grants import (
    CaptureGrant,
    CaptureGrantBatchRequest,
    CaptureGrantBatchResponse,
    RetireCaptureGrantRequest,
)


class CaptureGrantService:
    def __init__(self, repository) -> None:
        self._repository = repository

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
