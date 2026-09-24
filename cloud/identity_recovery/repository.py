"""In-memory reference transaction for immutable recovery cases."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cloud.api.errors import IdempotencyConflict, ResourceNotFound
from shared.contracts.identity_recovery import RecoveryCaseCreateRequest

from .models import RecoveryCaseRecord
from shared.contracts.identity_recovery import RecoveryComparisonResult


class InMemoryRecoveryCaseRepository:
    def __init__(self) -> None:
        self._subjects: dict[tuple[UUID, UUID], str | None] = {}
        self._cases: dict[tuple[UUID, UUID], RecoveryCaseRecord] = {}
        self._by_id: dict[tuple[UUID, UUID], RecoveryCaseRecord] = {}
        self._keys: dict[tuple[UUID, str], RecoveryCaseRecord] = {}
        self._lock = asyncio.Lock()

    def add_subject(self, tenant_id: UUID, subject_id: UUID, *, masked_clue: str | None = None) -> None:
        self._subjects[(tenant_id, subject_id)] = masked_clue

    def deactivate_subject(self, tenant_id: UUID, subject_id: UUID) -> None:
        self._subjects.pop((tenant_id, subject_id), None)

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

    async def get_platform_case(self, tenant_id: UUID, case_id: UUID) -> RecoveryCaseRecord:
        record = self._by_id.get((tenant_id, case_id))
        if record is None:
            raise ResourceNotFound("recovery case not found")
        return record

    async def record_comparison(
        self, tenant_id: UUID, case_id: UUID, *, matched: bool,
        actor_id: UUID, grant_id: UUID, ticket_sha256: str,
    ) -> RecoveryComparisonResult:
        async with self._lock:
            case = await self.get_platform_case(tenant_id, case_id)
            if case.status == "MATCHED" and case.receipt_expires_at is not None and case.receipt_expires_at > datetime.now(UTC):
                return RecoveryComparisonResult(
                    case_id=case_id, decision="MATCHED", receipt_id=case.receipt_id,
                    receipt_expires_at=case.receipt_expires_at,
                )
            if case.attempts >= 3:
                return RecoveryComparisonResult(case_id=case_id, decision="NOT_VERIFIED")
            if (tenant_id, case.request.cloud_subject_uuid) not in self._subjects:
                raise ResourceNotFound("cloud subject is no longer active")
            receipt_id = uuid4() if matched else None
            expires_at = datetime.now(UTC) + timedelta(minutes=15) if matched else None
            updated = replace(
                case, attempts=case.attempts + 1,
                status="MATCHED" if matched else ("DENIED" if case.attempts >= 2 else "PENDING"),
                receipt_id=receipt_id, receipt_expires_at=expires_at,
            )
            self._by_id[(tenant_id, case_id)] = updated
            self._cases[(tenant_id, case.request.session_id)] = updated
            self._keys[(tenant_id, case.key_sha256)] = updated
            return RecoveryComparisonResult(
                case_id=case_id, decision="MATCHED" if matched else "NOT_VERIFIED",
                receipt_id=receipt_id, receipt_expires_at=expires_at,
            )
