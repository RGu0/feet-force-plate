"""In-memory reference transaction for immutable recovery cases."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from cloud.api.errors import IdempotencyConflict, ResourceNotFound
from shared.contracts.identity_recovery import RecoveryCaseCreateRequest

from .models import RecoveryCaseRecord


class InMemoryRecoveryCaseRepository:
    def __init__(self) -> None:
        self._subjects: dict[tuple[UUID, UUID], str | None] = {}
        self._cases: dict[tuple[UUID, UUID], RecoveryCaseRecord] = {}
        self._by_id: dict[tuple[UUID, UUID], RecoveryCaseRecord] = {}
        self._keys: dict[tuple[UUID, str], RecoveryCaseRecord] = {}
        self._lock = asyncio.Lock()

    def add_subject(self, tenant_id: UUID, subject_id: UUID, *, masked_clue: str | None = None) -> None:
        self._subjects[(tenant_id, subject_id)] = masked_clue

    async def create_case(
        self, tenant_id: UUID, terminal_id: UUID, request: RecoveryCaseCreateRequest,
        key_sha256: str, request_sha256: str,
    ) -> RecoveryCaseRecord:
        async with self._lock:
            keyed = self._keys.get((tenant_id, key_sha256))
            if keyed is not None:
                if keyed.request_sha256 != request_sha256:
                    raise IdempotencyConflict("recovery case idempotency key conflict")
                return keyed
            if (tenant_id, request.cloud_subject_uuid) not in self._subjects:
                raise ResourceNotFound("cloud subject not found")
            existing = self._cases.get((tenant_id, request.session_id))
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise IdempotencyConflict("recovery case binding conflict")
                self._keys[(tenant_id, key_sha256)] = existing
                return existing
            record = RecoveryCaseRecord(
                case_id=uuid4(), tenant_id=tenant_id, terminal_id=terminal_id,
                request=request, request_sha256=request_sha256, key_sha256=key_sha256,
                masked_clue=self._subjects[(tenant_id, request.cloud_subject_uuid)],
                status="PENDING", created_at=datetime.now(UTC),
            )
            self._cases[(tenant_id, request.session_id)] = record
            self._by_id[(tenant_id, record.case_id)] = record
            self._keys[(tenant_id, key_sha256)] = record
            return record

    async def get_case(self, tenant_id: UUID, terminal_id: UUID, case_id: UUID) -> RecoveryCaseRecord:
        record = self._by_id.get((tenant_id, case_id))
        if record is None or record.terminal_id != terminal_id:
            raise ResourceNotFound("recovery case not found")
        return record
