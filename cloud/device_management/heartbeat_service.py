"""Authenticated heartbeat service shared by legacy and License access tokens."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from cloud.api.auth import TerminalContext
from cloud.api.errors import TenantAccessDenied
from cloud.ingestion.principal import IngestionPrincipal
from shared.contracts.client_sync import canonical_sha256
from shared.contracts.cloud import HeartbeatRequest, HeartbeatResponse


class DeviceHeartbeatService:
    def __init__(self, repository, *, now: Callable[[], datetime] | None = None) -> None:
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    async def record_heartbeat(
        self,
        context: IngestionPrincipal | TerminalContext,
        terminal_id: UUID,
        request: HeartbeatRequest,
        idempotency_key: str,
    ) -> HeartbeatResponse:
        context.ensure_active(self._now())
        if context.terminal_id != terminal_id:
            raise TenantAccessDenied(
                "心跳路由终端与凭据不一致",
                terminal_id=str(terminal_id),
            )
        return await self._repository.record_heartbeat(
            context,
            request,
            canonical_sha256(request),
            idempotency_key,
            self._now(),
        )


__all__ = ["DeviceHeartbeatService"]
