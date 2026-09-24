"""Tenant-RLS PostgreSQL persistence for immutable recovery cases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cloud.api.errors import (
    IdempotencyConflict, RepositoryUnavailable, ResourceNotFound, TenantAccessDenied,
)
from cloud.api.postgres import tenant_transaction
from cloud.api.subject_service import IdentityProtector
from shared.contracts.identity_recovery import RecoveryCaseCreateRequest, RecoveryComparisonResult

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
        attempts=row["attempts"], receipt_id=row["receipt_id"],
        receipt_expires_at=row["receipt_expires_at"],
        receipt_consumed_at=row["receipt_consumed_at"],
    )


_CASE_SELECT = """SELECT c.*, r.receipt_id, r.expires_at AS receipt_expires_at,
                         r.consumed_at AS receipt_consumed_at
                  FROM ops.identity_recovery_cases c
                  LEFT JOIN ops.identity_recovery_receipts r
                    ON r.tenant_id=c.tenant_id AND r.case_id=c.case_id"""


class PostgresRecoveryIdentityReader:
    """Decrypt inside the tenant service only after the sensitive grant is used."""

    def __init__(self, tenant_pool, protector: IdentityProtector) -> None:
        self._pool = tenant_pool
        self._protector = protector

    async def read_identity(self, tenant_id: UUID, subject_id: UUID) -> tuple[str | None, str | None]:
        async with tenant_transaction(self._pool, tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT p.identity_ciphertext, p.encryption_nonce, p.key_version
                   FROM subject.identity_profiles p JOIN subject.subjects s
                     ON s.tenant_id=p.tenant_id AND s.subject_uuid=p.subject_uuid
                   WHERE p.tenant_id=$1 AND p.subject_uuid=$2 AND s.status='ACTIVE'""",
                tenant_id, subject_id,
            )
        if row is None:
            return None, None
        try:
            profile = self._protector.unprotect_identity_profile(
                row["identity_ciphertext"], row["encryption_nonce"], row["key_version"],
                tenant_id=str(tenant_id), subject_uuid=str(subject_id),
            )
        except Exception:
            raise RepositoryUnavailable("cloud identity profile unavailable") from None
        return profile.display_name, profile.contact


class PostgresRecoveryCaseRepository:
    def __init__(self, tenant_pool, platform_pool) -> None:
        self._tenant_pool = tenant_pool
        self._platform_pool = platform_pool

    async def create_case(
        self, tenant_id: UUID, terminal_id: UUID, request: RecoveryCaseCreateRequest,
        key_sha256: str, request_sha256: str,
    ) -> RecoveryCaseRecord:
        async with tenant_transaction(self._tenant_pool, tenant_id) as connection:
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
                _CASE_SELECT + " WHERE c.tenant_id=$1 AND c.key_sha256=$2",
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
                _CASE_SELECT + " WHERE c.tenant_id=$1 AND c.session_id=$2",
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
                   RETURNING case_id""",
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
            created = await connection.fetchrow(
                _CASE_SELECT + " WHERE c.tenant_id=$1 AND c.case_id=$2",
                tenant_id, row["case_id"],
            )
            return _record(created)

    async def get_case(self, tenant_id: UUID, terminal_id: UUID, case_id: UUID) -> RecoveryCaseRecord:
        async with tenant_transaction(self._tenant_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                _CASE_SELECT + " WHERE c.tenant_id=$1 AND c.terminal_id=$2 AND c.case_id=$3",
                tenant_id, terminal_id, case_id,
            )
            if row is None:
                raise ResourceNotFound("recovery case not found")
            return _record(row)

    async def get_platform_case(self, tenant_id: UUID, case_id: UUID) -> RecoveryCaseRecord:
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                _CASE_SELECT + " WHERE c.tenant_id=$1 AND c.case_id=$2",
                tenant_id, case_id,
            )
            if row is None:
                raise ResourceNotFound("recovery case not found")
            return _record(row)

    async def record_comparison(
        self, tenant_id: UUID, case_id: UUID, *, matched: bool,
        actor_id: UUID, grant_id: UUID, ticket_sha256: str,
    ) -> RecoveryComparisonResult:
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            case = await connection.fetchrow(
                """SELECT * FROM ops.identity_recovery_cases
                   WHERE tenant_id=$1 AND case_id=$2 FOR UPDATE""",
                tenant_id, case_id,
            )
            if case is None:
                raise ResourceNotFound("recovery case not found")
            prior = await connection.fetchrow(
                """SELECT receipt_id, expires_at, consumed_at FROM ops.identity_recovery_receipts
                   WHERE tenant_id=$1 AND case_id=$2""",
                tenant_id, case_id,
            )
            if prior is not None and prior["consumed_at"] is not None:
                raise IdempotencyConflict("recovery receipt already consumed")
            if prior is not None and prior["expires_at"] > datetime.now(UTC):
                return RecoveryComparisonResult(
                    case_id=case_id, decision="MATCHED", receipt_id=prior["receipt_id"],
                    receipt_expires_at=prior["expires_at"],
                )
            if case["attempts"] >= 3 or case["status"] in {"DENIED", "EXPIRED"}:
                return RecoveryComparisonResult(case_id=case_id, decision="NOT_VERIFIED")
            active_subject = await connection.fetchval(
                """SELECT EXISTS(SELECT 1 FROM subject.subjects s
                   JOIN subject.external_identifiers e
                     ON e.tenant_id=s.tenant_id AND e.subject_uuid=s.subject_uuid
                   WHERE s.tenant_id=$1 AND s.subject_uuid=$2 AND s.status='ACTIVE'
                     AND e.issuer=$3 AND e.id_type=$4 AND e.status='ACTIVE')""",
                tenant_id, case["cloud_subject_uuid"],
                case["identifier_issuer"], case["identifier_type"],
            )
            if not active_subject:
                raise ResourceNotFound("cloud subject is no longer active")
            attempt = case["attempts"] + 1
            status = "MATCHED" if matched else ("DENIED" if attempt >= 3 else "PENDING")
            await connection.execute(
                """UPDATE ops.identity_recovery_cases SET attempts=$3, status=$4
                   WHERE tenant_id=$1 AND case_id=$2""",
                tenant_id, case_id, attempt, status,
            )
            receipt_id, expires_at = None, None
            if matched:
                receipt_id, expires_at = uuid4(), datetime.now(UTC) + timedelta(minutes=15)
                if prior is None:
                    await connection.execute(
                        """INSERT INTO ops.identity_recovery_receipts
                           (receipt_id, tenant_id, case_id, terminal_id, session_id,
                            original_subject_uuid, cloud_subject_uuid, envelope_sha256, expires_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                        receipt_id, tenant_id, case_id, case["terminal_id"], case["session_id"],
                        case["original_subject_uuid"], case["cloud_subject_uuid"],
                        case["envelope_sha256"], expires_at,
                    )
                else:
                    await connection.execute(
                        """UPDATE ops.identity_recovery_receipts
                           SET receipt_id=$3, expires_at=$4, consumed_at=NULL
                           WHERE tenant_id=$1 AND case_id=$2 AND consumed_at IS NULL""",
                        tenant_id, case_id, receipt_id, expires_at,
                    )
            await connection.execute(
                """INSERT INTO ops.identity_recovery_comparisons
                   (comparison_id, tenant_id, case_id, actor_id, grant_id,
                    ticket_sha256, decision, compared_fields)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,ARRAY['name','contact']::text[])""",
                uuid4(), tenant_id, case_id, actor_id, grant_id, ticket_sha256,
                "MATCHED" if matched else "NOT_VERIFIED",
            )
            return RecoveryComparisonResult(
                case_id=case_id, decision="MATCHED" if matched else "NOT_VERIFIED",
                receipt_id=receipt_id, receipt_expires_at=expires_at,
            )
