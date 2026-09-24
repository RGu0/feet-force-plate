from __future__ import annotations

import hashlib

from cloud.api.access_auth import PlatformAccessContext
from cloud.api.errors import RequestContractError, TenantAccessDenied
from shared.contracts.access_control import PlatformRole

from .models import HoldApplyRequest, SessionHoldRecord, SessionHoldStatus
from .repository import SessionHoldRepository


class SessionHeld(Exception):
    """A held session cannot produce new analysis or reports."""


class SessionHoldService:
    def __init__(self, repository: SessionHoldRepository) -> None:
        self.repository = repository

    @staticmethod
    def _require_operator(context: PlatformAccessContext) -> None:
        if not context.roles.intersection({PlatformRole.OWNER, PlatformRole.SUPPORT}):
            raise TenantAccessDenied("platform hold role required")

    async def apply(self, context: PlatformAccessContext, request: HoldApplyRequest,
                    idempotency_key: str) -> SessionHoldRecord:
        self._require_operator(context)
        if not request.ticket_reference.strip():
            raise RequestContractError("incident ticket required")
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise RequestContractError("idempotency key required")
        # The ticket is retained only in the restricted audit ledger, never the response.
        digest = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
        return await self.repository.apply(
            request, actor_id=context.platform_identity_id,
            idempotency_key=idempotency_key, request_sha256=digest,
        )

    async def status(self, context: PlatformAccessContext, tenant_id, session_id) -> SessionHoldStatus:
        self._require_operator(context)
        return await self.repository.status(tenant_id, session_id)
