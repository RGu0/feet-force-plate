from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from cloud.api.errors import IdempotencyConflict, ResourceNotFound

from .models import HoldApplyRequest, SessionHoldRecord, SessionHoldStatus


class SessionHoldRepository(Protocol):
    async def apply(self, request: HoldApplyRequest, *, actor_id: UUID,
                    idempotency_key: str, request_sha256: str) -> SessionHoldRecord: ...

    async def status(self, tenant_id: UUID, session_id: UUID) -> SessionHoldStatus: ...


class InMemorySessionHoldRepository:
    """Reference adapter; identity and raw session state are deliberately separate."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[UUID, UUID], tuple[str, int]] = {}
        self._holds: dict[tuple[UUID, UUID], SessionHoldRecord] = {}
        self._keys: dict[tuple[UUID, str], tuple[str, SessionHoldRecord]] = {}
        self._audit: list[tuple[str, UUID, UUID]] = []
        self._lock = asyncio.Lock()

    def add_session(self, tenant_id: UUID, session_id: UUID, *, status: str,
                    raw_object_count: int) -> None:
        self._sessions[(tenant_id, session_id)] = (status, raw_object_count)

    def session_status(self, tenant_id: UUID, session_id: UUID) -> str:
        return self._sessions[(tenant_id, session_id)][0]

    def raw_object_count(self, tenant_id: UUID, session_id: UUID) -> int:
        return self._sessions[(tenant_id, session_id)][1]

    def audit_count(self, action: str) -> int:
        return sum(1 for item in self._audit if item[0] == action)

    def is_held(self, tenant_id: UUID, session_id: UUID) -> bool:
        record = self._holds.get((tenant_id, session_id))
        return record is not None and record.state == "HELD"

    async def status(self, tenant_id: UUID, session_id: UUID) -> SessionHoldStatus:
        key = (tenant_id, session_id)
        if key not in self._sessions:
            raise ResourceNotFound("session not found")
        record = self._holds.get(key)
        if record is None:
            return SessionHoldStatus(held=False)
        return SessionHoldStatus(record.state == "HELD", record.hold_id, record.state)

    async def apply(self, request: HoldApplyRequest, *, actor_id: UUID,
                    idempotency_key: str, request_sha256: str) -> SessionHoldRecord:
        key = (request.tenant_id, request.session_id)
        async with self._lock:
            if key not in self._sessions:
                raise ResourceNotFound("session not found")
            prior = self._keys.get((request.tenant_id, idempotency_key))
            if prior is not None:
                if prior[0] != request_sha256:
                    raise IdempotencyConflict("idempotency key conflict")
                return prior[1]
            if key in self._holds:
                raise IdempotencyConflict("session already held")
            record = SessionHoldRecord(
                hold_id=uuid4(), tenant_id=request.tenant_id, session_id=request.session_id,
                state="HELD", reason_code=request.reason_code, applied_at=datetime.now(UTC),
            )
            self._holds[key] = record
            self._keys[(request.tenant_id, idempotency_key)] = (request_sha256, record)
            self._audit.append(("session-hold.apply", request.tenant_id, request.session_id))
            return record
