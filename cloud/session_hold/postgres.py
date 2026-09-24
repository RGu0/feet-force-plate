from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from cloud.api.errors import IdempotencyConflict, ResourceNotFound
from cloud.api.postgres import tenant_transaction

from .models import HoldApplyRequest, SessionHoldRecord, SessionHoldStatus


def _record(row) -> SessionHoldRecord:
    return SessionHoldRecord(
        hold_id=row["hold_id"], tenant_id=row["tenant_id"],
        session_id=row["session_id"], state=row["state"],
        reason_code=row["reason_code"], applied_at=row["applied_at"],
    )


class PostgresSessionHoldRepository:
    """All reads and transitions use transaction-local tenant RLS context."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def status(self, tenant_id: UUID, session_id: UUID) -> SessionHoldStatus:
        async with tenant_transaction(self._pool, tenant_id) as connection:
            session_exists = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM screening.sessions WHERE tenant_id=$1 AND session_id=$2)",
                tenant_id, session_id,
            )
            if not session_exists:
                raise ResourceNotFound("session not found")
            row = await connection.fetchrow(
                "SELECT hold_id, state FROM ops.session_holds WHERE tenant_id=$1 AND session_id=$2",
                tenant_id, session_id,
            )
            if row is None:
                return SessionHoldStatus(held=False)
            return SessionHoldStatus(row["state"] == "HELD", row["hold_id"], row["state"])

    async def is_held(self, tenant_id: UUID, session_id: UUID) -> bool:
        status = await self.status(tenant_id, session_id)
        return status.held

    async def apply(self, request: HoldApplyRequest, *, actor_id: UUID,
                    idempotency_key: str, request_sha256: str) -> SessionHoldRecord:
        tenant_id, session_id = request.tenant_id, request.session_id
        key_sha256 = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        ticket_sha256 = hashlib.sha256(request.ticket_reference.strip().encode("utf-8")).hexdigest()
        async with tenant_transaction(self._pool, tenant_id) as connection:
            # Session-scoped advisory lock serializes distinct-key requests without
            # granting the platform role UPDATE on screening.sessions.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1::text || ':' || $2::text, 0))",
                tenant_id, session_id,
            )
            exists = await connection.fetchval(
                "SELECT 1 FROM screening.sessions WHERE tenant_id=$1 AND session_id=$2",
                tenant_id, session_id,
            )
            if not exists:
                raise ResourceNotFound("session not found")
            prior = await connection.fetchrow(
                """SELECT request_sha256, h.hold_id, h.tenant_id, h.session_id,
                          h.state, h.reason_code, h.applied_at
                   FROM ops.session_hold_idempotency i
                   JOIN ops.session_holds h ON h.tenant_id=i.tenant_id AND h.hold_id=i.hold_id
                   WHERE i.tenant_id=$1 AND i.key_sha256=$2""",
                tenant_id, key_sha256,
            )
            if prior is not None:
                if prior["request_sha256"] != request_sha256:
                    raise IdempotencyConflict("idempotency key conflict")
                return _record(prior)
            held = await connection.fetchval(
                "SELECT 1 FROM ops.session_holds WHERE tenant_id=$1 AND session_id=$2",
                tenant_id, session_id,
            )
            if held:
                raise IdempotencyConflict("session already held")
            hold_id, event_id = uuid4(), uuid4()
            row = await connection.fetchrow(
                """INSERT INTO ops.session_holds
                   (hold_id, tenant_id, session_id, state, reason_code)
                   VALUES ($1,$2,$3,'HELD',$4)
                   RETURNING hold_id, tenant_id, session_id, state, reason_code, applied_at""",
                hold_id, tenant_id, session_id, request.reason_code,
            )
            await connection.execute(
                """INSERT INTO ops.session_hold_idempotency
                   (tenant_id, key_sha256, request_sha256, hold_id)
                   VALUES ($1,$2,$3,$4)""",
                tenant_id, key_sha256, request_sha256, hold_id,
            )
            await connection.execute(
                """INSERT INTO ops.session_hold_events
                   (event_id, tenant_id, hold_id, session_id, action, actor_id, ticket_sha256)
                   VALUES ($1,$2,$3,$4,'APPLY',$5,$6)""",
                event_id, tenant_id, hold_id, session_id, actor_id, ticket_sha256,
            )
            await connection.execute(
                """INSERT INTO ops.audit_logs
                   (audit_log_id, tenant_id, actor_type, actor_id, action, resource_type,
                    resource_id, outcome, safe_context)
                   VALUES ($1,$2,'PLATFORM_IDENTITY',$3,'session-hold.apply','SESSION',$4,
                           'ALLOWED',jsonb_build_object('reason_code',$5,'hold_id',$6::text))""",
                uuid4(), tenant_id, actor_id, session_id, request.reason_code, hold_id,
            )
            return _record(row)
