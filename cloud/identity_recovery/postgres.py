"""Tenant-RLS PostgreSQL persistence for immutable recovery cases."""

from __future__ import annotations

from uuid import UUID, uuid4

from cloud.api.errors import IdempotencyConflict, ResourceNotFound, TenantAccessDenied
from cloud.api.postgres import tenant_transaction
from shared.contracts.identity_recovery import RecoveryCaseCreateRequest

from .models import RecoveryCaseRecord


def _record(row) -> RecoveryCaseRecord:
    request = RecoveryCaseCreateRequest(
        session_id=row["session_id"],
        original_subject_uuid=row["original_subject_uuid"],
        cloud_subject_uuid=row["cloud_subject_uuid"],
        envelope_sha256=row["envelope_sha256"],
        identifier_issuer=row["identifier_issuer"],
        identifier_type=row["identifier_type"],
        terminal_id=row["terminal_id"],
    )
    return RecoveryCaseRecord(
        case_id=row["case_id"], tenant_id=row["tenant_id"],
        terminal_id=row["terminal_id"], request=request,
        request_sha256=row["request_sha256"], key_sha256=row["key_sha256"],
        masked_clue=row["masked_clue"], status=row["status"],
        created_at=row["created_at"],
    )


class PostgresRecoveryCaseRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def create_case(
        self, tenant_id: UUID, terminal_id: UUID, request: RecoveryCaseCreateRequest,
        key_sha256: str, request_sha256: str,
    ) -> RecoveryCaseRecord:
        async with tenant_transaction(self._pool, tenant_id) as connection:
            # Stable order closes both a reused-key race across sessions and a
            # distinct-key race on one session without a uniqueness exception.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('recovery-key:' || $1::uuid::text || ':' || $2::text, 0))",
                tenant_id, key_sha256,
            )
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('recovery-session:' || $1::uuid::text || ':' || $2::uuid::text, 0))",
                tenant_id, request.session_id,
            )
            terminal_active = await connection.fetchval(
                """SELECT EXISTS(
                     SELECT 1 FROM device.terminals WHERE tenant_id=$1 AND terminal_id=$2 AND status='ACTIVE'
                     UNION ALL
                     SELECT 1 FROM device.client_installations
                     WHERE tenant_id=$1 AND client_installation_id=$2 AND status='ACTIVE')""",
                tenant_id, terminal_id,
            )
            if not terminal_active:
                raise TenantAccessDenied("terminal is not active for tenant")
            keyed = await connection.fetchrow(
                "SELECT * FROM ops.identity_recovery_cases WHERE tenant_id=$1 AND key_sha256=$2",
                tenant_id, key_sha256,
            )
            if keyed is not None:
                if keyed["request_sha256"] != request_sha256:
                    raise IdempotencyConflict("recovery case idempotency key conflict")
                return _record(keyed)
            subject = await connection.fetchrow(
                """SELECT s.subject_uuid,
                          (SELECT e.masked_value FROM subject.external_identifiers e
                           WHERE e.tenant_id=s.tenant_id AND e.subject_uuid=s.subject_uuid
                             AND e.issuer=$3 AND e.id_type=$4 AND e.status='ACTIVE'
                           ORDER BY e.created_at DESC LIMIT 1) AS masked_clue
                   FROM subject.subjects s
                   WHERE s.tenant_id=$1 AND s.subject_uuid=$2 AND s.status='ACTIVE'""",
                tenant_id, request.cloud_subject_uuid,
                request.identifier_issuer, request.identifier_type,
            )
            if subject is None:
                raise ResourceNotFound("cloud subject not found")
            existing = await connection.fetchrow(
                "SELECT * FROM ops.identity_recovery_cases WHERE tenant_id=$1 AND session_id=$2",
                tenant_id, request.session_id,
            )
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise IdempotencyConflict("recovery case binding conflict")
                return _record(existing)
            case_id = uuid4()
            row = await connection.fetchrow(
                """INSERT INTO ops.identity_recovery_cases
                   (case_id, tenant_id, terminal_id, session_id, original_subject_uuid,
                    cloud_subject_uuid, envelope_sha256, identifier_issuer, identifier_type,
                    key_sha256, request_sha256, masked_clue, status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'PENDING')
                   RETURNING *""",
                case_id, tenant_id, terminal_id, request.session_id,
                request.original_subject_uuid, request.cloud_subject_uuid,
                request.envelope_sha256, request.identifier_issuer, request.identifier_type,
                key_sha256, request_sha256, subject["masked_clue"],
            )
            await connection.execute(
                """INSERT INTO ops.audit_logs
                   (audit_log_id, tenant_id, actor_type, actor_id, action,
                    resource_type, resource_id, outcome, safe_context)
                   VALUES ($1,$2,'TERMINAL',$3,'identity-recovery.case-create',
                           'RECOVERY_CASE',$4,'ALLOWED',
                           jsonb_build_object('session_id',$5::uuid::text))""",
                uuid4(), tenant_id, terminal_id, case_id, request.session_id,
            )
            return _record(row)

    async def get_case(self, tenant_id: UUID, terminal_id: UUID, case_id: UUID) -> RecoveryCaseRecord:
        async with tenant_transaction(self._pool, tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT * FROM ops.identity_recovery_cases
                   WHERE tenant_id=$1 AND terminal_id=$2 AND case_id=$3""",
                tenant_id, terminal_id, case_id,
            )
            if row is None:
                raise ResourceNotFound("recovery case not found")
            return _record(row)
