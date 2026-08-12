from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from cloud.api.auth import TerminalContext
from cloud.api.errors import (
    ActivationCodeInvalid,
    IdempotencyConflict,
    ManifestConflict,
    ManifestIncomplete,
    ResourceNotFound,
    RepositoryUnavailable,
    SegmentDigestConflict,
    TenantAccessDenied,
)
from cloud.api.repository import EnrollmentBinding, SegmentRecord, SessionRecord
from shared.contracts.client_sync import canonical_sha256
from shared.contracts.cloud import (
    ConsentCreateRequest,
    ConsentResponse,
    ConsentRevokeRequest,
    EnrollmentRequest,
    EnrollmentStatus,
    HeartbeatRequest,
    HeartbeatResponse,
    IngestStatus,
    ManifestCompletionResponse,
    SegmentMetadata,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionManifest,
    SessionStatusResponse,
    SessionVersions,
    SubjectCreateRequest,
    SubjectSummary,
    TestProtocol,
    ValidityStatus,
)


@asynccontextmanager
async def tenant_transaction(pool, tenant_id: UUID) -> AsyncIterator[Any]:
    """Acquire a transaction-scoped connection with a non-leaking RLS context."""

    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
            )
            yield connection


@asynccontextmanager
async def pool_transaction(pool) -> AsyncIterator[Any]:
    """Acquire a role-specific transaction for non-tenant routing tables.

    Tenant-owned rows must continue to use :func:`tenant_transaction` so RLS
    context is transaction-local and cannot leak through a pooled connection.
    """

    async with pool.acquire() as connection:
        async with connection.transaction():
            yield connection


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _session_record(row: Any) -> SessionRecord:
    request = SessionCreateRequest(
        session_id=row["session_id"],
        subject_uuid=row["subject_uuid"],
        consent_record_id=row["consent_record_id"],
        site_id=row["site_id"],
        terminal_id=row["terminal_id"],
        client_installation_id=row["terminal_id"],
        device_id=row["device_id"],
        test_protocol=TestProtocol(
            id=row["test_protocol_id"], version=row["test_protocol_version"]
        ),
        versions=SessionVersions(
            app=row["app_version"],
            protocol_profile=row["protocol_profile_version"],
            payload_schema=row["payload_schema_version"],
            calibration=row["calibration_version"],
        ),
        started_at=row["started_at"],
        config_snapshot=_json_value(row["config_snapshot"]),
    )
    return SessionRecord(
        tenant_id=row["tenant_id"],
        request=request,
        request_sha256=canonical_sha256(request),
        ingest_status=IngestStatus(row["ingest_status"]),
        validity_status=ValidityStatus(row["validity_status"]),
        manifest_sha256=row["manifest_sha256"],
        manifest_object_key=row.get("manifest_object_key") if hasattr(row, "get") else None,
        aggregate_version=row["aggregate_version"],
    )


class PostgresPlatformRepository:
    """Production asyncpg adapter for tenant-scoped ingestion state."""

    def __init__(
        self,
        pool,
        *,
        enrollment_pool=None,
        idempotency_ttl: timedelta = timedelta(days=7),
    ) -> None:
        self._pool = pool
        self._enrollment_pool = enrollment_pool
        self._idempotency_ttl = idempotency_ttl

    async def _require_active_terminal(
        self, connection, context: TerminalContext
    ) -> None:
        active = await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM device.terminals
                WHERE tenant_id=$1 AND terminal_id=$2 AND status='ACTIVE'
            )
            """,
            context.tenant_id,
            context.terminal_id,
        )
        if not active:
            raise TenantAccessDenied(
                "终端未绑定到当前租户或已停用",
                terminal_id=str(context.terminal_id),
            )

    async def _idempotency(
        self, connection, tenant_id: UUID, scope: str, key: str, request_sha256: str
    ) -> dict[str, Any] | None:
        row = await connection.fetchrow(
            """
            SELECT request_sha256, response_json
            FROM ops.idempotency_keys
            WHERE tenant_id = $1 AND scope = $2 AND idempotency_key = $3
            """,
            tenant_id,
            scope,
            key,
        )
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise IdempotencyConflict("同一幂等键对应不同请求", scope=scope)
        return _json_value(row["response_json"])

    async def _store_idempotency(
        self,
        connection,
        tenant_id: UUID,
        scope: str,
        key: str,
        request_sha256: str,
        response_status: int,
        response: dict[str, Any],
        resource_type: str,
        resource_id: UUID,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO ops.idempotency_keys (
                idempotency_record_id, tenant_id, scope, idempotency_key,
                request_sha256, response_status, response_json,
                resource_type, resource_id, expires_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10)
            """,
            uuid4(),
            tenant_id,
            scope,
            key,
            request_sha256,
            response_status,
            json.dumps(response, separators=(",", ":")),
            resource_type,
            resource_id,
            datetime.now(UTC) + self._idempotency_ttl,
        )

    async def consume_activation_code(
        self,
        activation_code_hash: bytes,
        request: EnrollmentRequest,
        request_sha256: str,
        idempotency_key: str,
        accepted_at: datetime,
    ) -> EnrollmentBinding:
        if self._enrollment_pool is None:
            raise RepositoryUnavailable("终端激活数据库角色未配置")
        async with self._enrollment_pool.acquire() as connection:
            async with connection.transaction():
                code = await connection.fetchrow(
                    """
                    SELECT tenant_id, site_id, device_id, expires_at, used_at, terminal_id
                    FROM device.enrollment_codes
                    WHERE activation_code_hash=$1
                    FOR UPDATE
                    """,
                    activation_code_hash,
                )
                if code is None:
                    raise ActivationCodeInvalid("激活码无效、已使用或已过期")
                replay = await self._idempotency(
                    connection,
                    code["tenant_id"],
                    "device.enroll",
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    return EnrollmentBinding(
                        tenant_id=UUID(replay["tenant_id"]),
                        site_id=UUID(replay["site_id"]) if replay["site_id"] else None,
                        terminal_id=UUID(replay["terminal_id"]),
                        status=EnrollmentStatus(replay["status"]),
                        config_version=replay.get("config_version"),
                    )
                if code["used_at"] is not None or code["expires_at"] <= accepted_at:
                    raise ActivationCodeInvalid("激活码无效、已使用或已过期")
                installation_exists = await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM device.terminals
                        WHERE tenant_id=$1 AND installation_id=$2
                    )
                    """,
                    code["tenant_id"],
                    request.installation_id,
                )
                if installation_exists:
                    raise ActivationCodeInvalid("安装实例已经绑定，请联系支持")
                if code["device_id"] is not None:
                    device_is_active = await connection.fetchval(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM device.devices
                            WHERE tenant_id=$1 AND device_id=$2 AND status='ACTIVE'
                        )
                        """,
                        code["tenant_id"],
                        code["device_id"],
                    )
                    if not device_is_active:
                        raise ActivationCodeInvalid("激活码绑定的设备不可用")
                terminal_id = uuid4()
                await connection.execute(
                    """
                    INSERT INTO device.terminals (
                        terminal_id, tenant_id, site_id, installation_id,
                        client_public_key, status, app_version, last_seen_at
                    ) VALUES ($1,$2,$3,$4,$5,'ACTIVE',$6,$7)
                    """,
                    terminal_id,
                    code["tenant_id"],
                    code["site_id"],
                    request.installation_id,
                    request.client_public_key,
                    request.system.app_version,
                    accepted_at,
                )
                if code["device_id"] is not None:
                    await connection.execute(
                        """
                        INSERT INTO device.terminal_device_bindings (
                            terminal_device_binding_id, tenant_id, terminal_id,
                            device_id, valid_from
                        ) VALUES ($1,$2,$3,$4,$5)
                        """,
                        uuid4(),
                        code["tenant_id"],
                        terminal_id,
                        code["device_id"],
                        accepted_at,
                    )
                await connection.execute(
                    """
                    UPDATE device.enrollment_codes
                    SET used_at=$2, terminal_id=$3
                    WHERE activation_code_hash=$1 AND used_at IS NULL
                    """,
                    activation_code_hash,
                    accepted_at,
                    terminal_id,
                )
                response = {
                    "tenant_id": str(code["tenant_id"]),
                    "site_id": str(code["site_id"]) if code["site_id"] else None,
                    "terminal_id": str(terminal_id),
                    "status": EnrollmentStatus.ACTIVE.value,
                    "config_version": None,
                }
                await self._store_idempotency(
                    connection,
                    code["tenant_id"],
                    "device.enroll",
                    idempotency_key,
                    request_sha256,
                    201,
                    response,
                    "terminal",
                    terminal_id,
                )
                await connection.execute(
                    """
                    INSERT INTO ops.audit_logs (
                        audit_log_id, tenant_id, occurred_at, actor_type,
                        actor_id, action, resource_type, resource_id,
                        outcome, safe_context
                    ) VALUES ($1,$2,$3,'ACTIVATION_CODE',NULL,'terminal.enroll',
                              'terminal',$4,'ALLOWED',$5::jsonb)
                    """,
                    uuid4(),
                    code["tenant_id"],
                    accepted_at,
                    terminal_id,
                    json.dumps(
                        {
                            "site_id": str(code["site_id"]) if code["site_id"] else None,
                            "device_bound": code["device_id"] is not None,
                            "app_version": request.system.app_version,
                        },
                        separators=(",", ":"),
                    ),
                )
                return EnrollmentBinding(
                    tenant_id=code["tenant_id"],
                    site_id=code["site_id"],
                    terminal_id=terminal_id,
                    status=EnrollmentStatus.ACTIVE,
                )

    async def record_heartbeat(
        self,
        context: TerminalContext,
        request: HeartbeatRequest,
        request_sha256: str,
        idempotency_key: str,
        accepted_at: datetime,
    ) -> HeartbeatResponse:
        context.ensure_active()
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            replay = await self._idempotency(
                connection,
                context.tenant_id,
                "terminal.heartbeat",
                idempotency_key,
                request_sha256,
            )
            if replay is not None:
                return HeartbeatResponse.model_validate(replay)
            await self._require_active_terminal(connection, context)
            if request.device.device_id is not None:
                bound = await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM device.terminal_device_bindings
                        WHERE tenant_id=$1 AND terminal_id=$2 AND device_id=$3
                          AND valid_to IS NULL
                    )
                    """,
                    context.tenant_id,
                    context.terminal_id,
                    request.device.device_id,
                )
                if not bound:
                    raise TenantAccessDenied(
                        "设备未绑定到当前终端",
                        device_id=str(request.device.device_id),
                    )
            await connection.execute(
                """
                INSERT INTO device.terminal_heartbeats (
                    terminal_heartbeat_id, tenant_id, terminal_id, device_id,
                    observed_at, app_version, config_version, protocol_version,
                    connection_state, last_successful_sync_at, pending_sessions,
                    pending_bytes, disk_free_bytes, clock_skew_seconds,
                    last_error_code, received_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                """,
                uuid4(),
                context.tenant_id,
                context.terminal_id,
                request.device.device_id,
                request.observed_at,
                request.app_version,
                request.config_version,
                request.protocol_version,
                request.device.connection_state,
                request.sync.last_successful_sync,
                request.sync.pending_sessions,
                request.sync.pending_bytes,
                request.health.disk_free_bytes,
                request.health.clock_skew_seconds,
                request.health.last_error_code,
                accepted_at,
            )
            await connection.execute(
                """
                UPDATE device.terminals
                SET app_version=$3, config_version=$4, protocol_version=$5,
                    last_seen_at=$6, last_successful_sync_at=$7,
                    pending_sessions=$8, pending_bytes=$9, updated_at=$6
                WHERE tenant_id=$1 AND terminal_id=$2
                """,
                context.tenant_id,
                context.terminal_id,
                request.app_version,
                request.config_version,
                request.protocol_version,
                accepted_at,
                request.sync.last_successful_sync,
                request.sync.pending_sessions,
                request.sync.pending_bytes,
            )
            response = HeartbeatResponse(
                terminal_id=context.terminal_id,
                accepted_at=accepted_at,
                status=EnrollmentStatus.ACTIVE,
            )
            await self._store_idempotency(
                connection,
                context.tenant_id,
                "terminal.heartbeat",
                idempotency_key,
                request_sha256,
                200,
                response.model_dump(mode="json"),
                "terminal",
                context.terminal_id,
            )
            return response

    async def create_session(
        self,
        context: TerminalContext,
        request: SessionCreateRequest,
        idempotency_key: str,
    ) -> SessionCreateResponse:
        context.ensure_active()
        digest = canonical_sha256(request)
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            replay = await self._idempotency(
                connection, context.tenant_id, "session.create", idempotency_key, digest
            )
            if replay is not None:
                return SessionCreateResponse.model_validate(replay).model_copy(
                    update={"idempotent_replay": True}
                )
            validation = await connection.fetchrow(
                """
                SELECT
                    EXISTS (
                        SELECT 1
                        FROM device.client_installations i
                        JOIN device.terminals t
                          ON t.tenant_id=i.tenant_id
                         AND t.terminal_id=i.client_installation_id
                        WHERE i.tenant_id=$1 AND i.client_installation_id=$2
                          AND t.site_id IS NOT DISTINCT FROM $3
                    ) AS installation_ok,
                    EXISTS (
                        SELECT 1
                        FROM device.hardware_assets h
                        JOIN device.devices d
                          ON d.tenant_id=h.tenant_id AND d.device_id=h.hardware_id
                        WHERE h.tenant_id=$1 AND h.hardware_id=$4
                    ) AS hardware_ok,
                    EXISTS (
                        SELECT 1 FROM subject.subjects s
                        WHERE s.tenant_id=$1 AND s.subject_uuid=$5 AND s.status='ACTIVE'
                    ) AS subject_ok,
                    EXISTS (
                        SELECT 1 FROM subject.consents c
                        WHERE c.tenant_id=$1 AND c.consent_record_id=$6
                          AND c.subject_uuid=$5 AND c.revoked_at IS NULL
                    ) AS consent_ok
                """,
                context.tenant_id,
                request.client_installation_id,
                request.site_id,
                request.device_id,
                request.subject_uuid,
                request.consent_record_id,
            )
            if not all(validation.values()):
                raise TenantAccessDenied("会话引用与认证租户、采集身份或授权不一致")
            existing = await connection.fetchrow(
                "SELECT * FROM screening.sessions WHERE tenant_id=$1 AND session_id=$2 FOR UPDATE",
                context.tenant_id,
                request.session_id,
            )
            if existing is not None:
                record = _session_record(existing)
                if record.request_sha256 != digest:
                    raise IdempotencyConflict("同一会话 ID 对应不同请求")
                response = SessionCreateResponse(
                    session_id=request.session_id,
                    ingest_status=record.ingest_status,
                    idempotent_replay=True,
                )
            else:
                await connection.execute(
                    """
                    INSERT INTO screening.sessions (
                        session_id, tenant_id, site_id, terminal_id, device_id,
                        subject_uuid, consent_record_id, test_protocol_id,
                        test_protocol_version, validity_status, ingest_status,
                        started_at, app_version, protocol_profile_version,
                        payload_schema_version, calibration_version, config_snapshot
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'UNKNOWN','RECEIVING',$10,$11,$12,$13,$14,$15::jsonb)
                    """,
                    request.session_id,
                    context.tenant_id,
                    request.site_id,
                    request.client_installation_id,
                    request.device_id,
                    request.subject_uuid,
                    request.consent_record_id,
                    request.test_protocol.id,
                    request.test_protocol.version,
                    request.started_at,
                    request.versions.app,
                    request.versions.protocol_profile,
                    request.versions.payload_schema,
                    request.versions.calibration,
                    json.dumps(request.config_snapshot, separators=(",", ":")),
                )
                response = SessionCreateResponse(
                    session_id=request.session_id,
                    ingest_status=IngestStatus.RECEIVING,
                )
            await self._store_idempotency(
                connection,
                context.tenant_id,
                "session.create",
                idempotency_key,
                digest,
                201,
                response.model_copy(update={"idempotent_replay": False}).model_dump(mode="json"),
                "screening_session",
                request.session_id,
            )
            return response

    async def resolve_subject(
        self,
        context: TerminalContext,
        issuer: str,
        id_type: str,
        normalized_hmac: bytes,
    ) -> SubjectSummary | None:
        context.ensure_active()
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            await self._require_active_terminal(connection, context)
            row = await connection.fetchrow(
                """
                SELECT e.subject_uuid, e.masked_value, p.profile_json
                FROM subject.external_identifiers e
                JOIN subject.subjects s
                  ON s.tenant_id=e.tenant_id AND s.subject_uuid=e.subject_uuid
                LEFT JOIN subject.analysis_profiles p
                  ON p.tenant_id=e.tenant_id AND p.subject_uuid=e.subject_uuid
                WHERE e.tenant_id=$1 AND e.issuer=$2 AND e.id_type=$3
                  AND e.normalized_hmac=$4 AND e.status='ACTIVE' AND s.status='ACTIVE'
                """,
                context.tenant_id,
                issuer,
                id_type,
                normalized_hmac,
            )
            if row is None:
                return None
            return SubjectSummary(
                subject_uuid=row["subject_uuid"],
                external_id_masked=row["masked_value"],
                analysis_profile=_json_value(row["profile_json"]) if row["profile_json"] else {},
            )

    async def create_subject(
        self,
        context: TerminalContext,
        request: SubjectCreateRequest,
        *,
        normalized_hmac: bytes | None,
        encrypted_value: bytes | None,
        encryption_nonce: bytes | None,
        masked_value: str | None,
        key_version: str | None,
        identity_ciphertext: bytes | None,
        identity_nonce: bytes | None,
        identity_key_version: str | None,
        idempotency_key: str,
    ) -> SubjectSummary:
        context.ensure_active()
        digest = canonical_sha256(request)
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            await self._require_active_terminal(connection, context)
            replay = await self._idempotency(
                connection, context.tenant_id, "subject.create", idempotency_key, digest
            )
            if replay is not None:
                return SubjectSummary.model_validate(replay)
            external = request.external_identifier
            existing = None
            if external is not None:
                existing = await connection.fetchrow(
                    """
                    SELECT e.subject_uuid, e.masked_value, p.profile_json
                    FROM subject.external_identifiers e
                    LEFT JOIN subject.analysis_profiles p
                      ON p.tenant_id=e.tenant_id AND p.subject_uuid=e.subject_uuid
                    WHERE e.tenant_id=$1 AND e.issuer=$2 AND e.id_type=$3
                      AND e.normalized_hmac=$4 AND e.status='ACTIVE'
                    """,
                    context.tenant_id,
                    external.issuer,
                    external.id_type,
                    normalized_hmac,
                )
            if existing is not None:
                response = SubjectSummary(
                    subject_uuid=existing["subject_uuid"],
                    external_id_masked=existing["masked_value"],
                    conflict=True,
                    analysis_profile=(
                        _json_value(existing["profile_json"])
                        if existing["profile_json"]
                        else {}
                    ),
                )
            else:
                await connection.execute(
                    """
                    INSERT INTO subject.subjects (subject_uuid, tenant_id, status)
                    VALUES ($1,$2,'ACTIVE')
                    """,
                    request.subject_uuid,
                    context.tenant_id,
                )
                await connection.execute(
                    """
                    INSERT INTO subject.analysis_profiles (
                        subject_uuid, tenant_id, profile_json, schema_version, source
                    ) VALUES ($1,$2,$3::jsonb,$4,'TERMINAL')
                    """,
                    request.subject_uuid,
                    context.tenant_id,
                    json.dumps(
                        {
                            key: value.model_dump(mode="json")
                            for key, value in request.analysis_profile.items()
                        },
                        separators=(",", ":"),
                    ),
                    request.profile_schema_version,
                )
                if request.identity_profile is not None:
                    if None in (
                        identity_ciphertext,
                        identity_nonce,
                        identity_key_version,
                    ):
                        raise ValueError("protected identity profile fields are required")
                    await connection.execute(
                        """
                        INSERT INTO subject.identity_profiles (
                            subject_uuid, tenant_id, identity_ciphertext,
                            encryption_nonce, key_version
                        ) VALUES ($1,$2,$3,$4,$5)
                        """,
                        request.subject_uuid,
                        context.tenant_id,
                        identity_ciphertext,
                        identity_nonce,
                        identity_key_version,
                    )
                if external is not None:
                    if None in (
                        normalized_hmac,
                        encrypted_value,
                        encryption_nonce,
                        masked_value,
                        key_version,
                    ):
                        raise ValueError("protected external identifier fields are required")
                    await connection.execute(
                        """
                        INSERT INTO subject.external_identifiers (
                            external_identifier_id, tenant_id, subject_uuid,
                            issuer, id_type, encrypted_value, encryption_nonce,
                            normalized_hmac, masked_value, key_version, status
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'ACTIVE')
                        """,
                        uuid4(),
                        context.tenant_id,
                        request.subject_uuid,
                        external.issuer,
                        external.id_type,
                        encrypted_value,
                        encryption_nonce,
                        normalized_hmac,
                        masked_value,
                        key_version,
                    )
                response = SubjectSummary(
                    subject_uuid=request.subject_uuid,
                    external_id_masked=masked_value,
                    analysis_profile=request.analysis_profile,
                )
            await self._store_idempotency(
                connection,
                context.tenant_id,
                "subject.create",
                idempotency_key,
                digest,
                200 if response.conflict else 201,
                response.model_dump(mode="json"),
                "subject",
                response.subject_uuid,
            )
            return response

    async def create_consent(
        self,
        context: TerminalContext,
        request: ConsentCreateRequest,
        request_sha256: str,
        idempotency_key: str,
    ) -> ConsentResponse:
        context.ensure_active()
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            await self._require_active_terminal(connection, context)
            replay = await self._idempotency(
                connection,
                context.tenant_id,
                "consent.create",
                idempotency_key,
                request_sha256,
            )
            if replay is not None:
                return ConsentResponse.model_validate(replay)
            subject_exists = await connection.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM subject.subjects
                    WHERE tenant_id=$1 AND subject_uuid=$2 AND status='ACTIVE'
                )
                """,
                context.tenant_id,
                request.subject_uuid,
            )
            if not subject_exists:
                raise TenantAccessDenied("受试者不属于当前租户")
            existing = await connection.fetchrow(
                """
                SELECT * FROM subject.consents
                WHERE tenant_id=$1 AND consent_record_id=$2
                """,
                context.tenant_id,
                request.consent_record_id,
            )
            if existing is not None:
                if existing["evidence_hash"] != request_sha256:
                    raise IdempotencyConflict("同一授权 ID 对应不同内容")
                response = ConsentResponse(
                    consent_record_id=existing["consent_record_id"],
                    subject_uuid=existing["subject_uuid"],
                    policy_version=existing["policy_version"],
                    granted_at=existing["granted_at"],
                    revoked_at=existing["revoked_at"],
                )
            else:
                await connection.execute(
                    """
                    INSERT INTO subject.consents (
                        consent_record_id, tenant_id, subject_uuid, policy_version,
                        purpose_codes, data_categories, evidence_type, terminal_id,
                        evidence_hash, granted_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    """,
                    request.consent_record_id,
                    context.tenant_id,
                    request.subject_uuid,
                    request.policy_version,
                    list(request.purpose_codes),
                    list(request.data_categories),
                    request.evidence_type,
                    context.terminal_id,
                    request_sha256,
                    request.granted_at,
                )
                response = ConsentResponse(
                    consent_record_id=request.consent_record_id,
                    subject_uuid=request.subject_uuid,
                    policy_version=request.policy_version,
                    granted_at=request.granted_at,
                )
            await self._store_idempotency(
                connection,
                context.tenant_id,
                "consent.create",
                idempotency_key,
                request_sha256,
                201,
                response.model_dump(mode="json"),
                "consent",
                request.consent_record_id,
            )
            return response

    async def revoke_consent(
        self,
        context: TerminalContext,
        consent_record_id: UUID,
        request: ConsentRevokeRequest,
        request_sha256: str,
        idempotency_key: str,
    ) -> ConsentResponse:
        context.ensure_active()
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            await self._require_active_terminal(connection, context)
            replay = await self._idempotency(
                connection,
                context.tenant_id,
                "consent.revoke",
                idempotency_key,
                request_sha256,
            )
            if replay is not None:
                return ConsentResponse.model_validate(replay)
            row = await connection.fetchrow(
                """
                SELECT * FROM subject.consents
                WHERE tenant_id=$1 AND consent_record_id=$2 FOR UPDATE
                """,
                context.tenant_id,
                consent_record_id,
            )
            if row is None:
                raise ResourceNotFound("授权不存在")
            if row["revoked_at"] is not None and row["revoked_at"] != request.revoked_at:
                raise IdempotencyConflict("授权已经以不同撤回事实撤回")
            await connection.execute(
                """
                UPDATE subject.consents
                SET revoked_at=$3, revocation_reason_code=$4
                WHERE tenant_id=$1 AND consent_record_id=$2
                """,
                context.tenant_id,
                consent_record_id,
                request.revoked_at,
                request.reason_code,
            )
            response = ConsentResponse(
                consent_record_id=consent_record_id,
                subject_uuid=row["subject_uuid"],
                policy_version=row["policy_version"],
                granted_at=row["granted_at"],
                revoked_at=request.revoked_at,
            )
            await self._store_idempotency(
                connection,
                context.tenant_id,
                "consent.revoke",
                idempotency_key,
                request_sha256,
                200,
                response.model_dump(mode="json"),
                "consent",
                consent_record_id,
            )
            return response

    async def is_consent_active(self, tenant_id: UUID, consent_record_id: UUID) -> bool:
        async with tenant_transaction(self._pool, tenant_id) as connection:
            return bool(
                await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM subject.consents
                        WHERE tenant_id=$1 AND consent_record_id=$2 AND revoked_at IS NULL
                    )
                    """,
                    tenant_id,
                    consent_record_id,
                )
            )

    async def session(self, context: TerminalContext, session_id: UUID) -> SessionRecord:
        context.ensure_active()
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM screening.sessions WHERE tenant_id=$1 AND session_id=$2",
                context.tenant_id,
                session_id,
            )
            if row is None:
                raise ResourceNotFound("会话不存在", session_id=str(session_id))
            record = _session_record(row)
            return record

    @staticmethod
    def _segment_record(row: Any) -> SegmentRecord:
        return SegmentRecord(
            tenant_id=row["tenant_id"],
            session_id=row["session_id"],
            metadata=SegmentMetadata(
                segment_index=row["segment_index"],
                start_frame_index=row["start_frame_index"],
                frame_count=row["frame_count"],
                start_monotonic_ns=row["start_monotonic_ns"],
                end_monotonic_ns=row["end_monotonic_ns"],
                compression=row["compression"],
                cipher=row["cipher"],
                size_bytes=row["size_bytes"],
                sha256=row["sha256"],
                payload_schema_version=row["payload_schema_version"],
            ),
            object_key=row["object_key"],
            received_at=row["received_at"],
        )

    async def get_segment(
        self, context: TerminalContext, session_id: UUID, index: int
    ) -> SegmentRecord | None:
        await self.session(context, session_id)
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            row = await connection.fetchrow(
                """
                SELECT * FROM screening.session_segments
                WHERE tenant_id=$1 AND session_id=$2 AND segment_index=$3
                """,
                context.tenant_id,
                session_id,
                index,
            )
            return None if row is None else self._segment_record(row)

    async def register_segment(
        self,
        context: TerminalContext,
        session_id: UUID,
        metadata: SegmentMetadata,
        object_key: str,
    ) -> SegmentRecord:
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            session = await connection.fetchrow(
                """
                SELECT terminal_id, ingest_status FROM screening.sessions
                WHERE tenant_id=$1 AND session_id=$2 FOR UPDATE
                """,
                context.tenant_id,
                session_id,
            )
            if session is None:
                raise ResourceNotFound("会话不存在", session_id=str(session_id))
            if session["ingest_status"] in ("INGESTED", "CONFLICT"):
                raise SegmentDigestConflict("会话不再接受分段")
            row = await connection.fetchrow(
                """
                INSERT INTO screening.session_segments (
                    session_segment_id, tenant_id, session_id, segment_index,
                    object_key, sha256, size_bytes, start_frame_index, frame_count,
                    start_monotonic_ns, end_monotonic_ns, payload_schema_version,
                    compression, cipher, status, verified_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'VERIFIED',now())
                ON CONFLICT (tenant_id, session_id, segment_index) DO NOTHING
                RETURNING *
                """,
                uuid4(),
                context.tenant_id,
                session_id,
                metadata.segment_index,
                object_key,
                metadata.sha256,
                metadata.size_bytes,
                metadata.start_frame_index,
                metadata.frame_count,
                metadata.start_monotonic_ns,
                metadata.end_monotonic_ns,
                metadata.payload_schema_version,
                metadata.compression,
                metadata.cipher,
            )
            if row is None:
                row = await connection.fetchrow(
                    """
                    SELECT * FROM screening.session_segments
                    WHERE tenant_id=$1 AND session_id=$2 AND segment_index=$3
                    """,
                    context.tenant_id,
                    session_id,
                    metadata.segment_index,
                )
                if row["sha256"] != metadata.sha256:
                    raise SegmentDigestConflict("同一分段索引已存在不同摘要")
            return self._segment_record(row)

    async def mark_segment_conflict(
        self, context: TerminalContext, session_id: UUID, index: int
    ) -> None:
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            result = await connection.execute(
                """
                UPDATE screening.sessions SET ingest_status='CONFLICT', updated_at=now()
                WHERE tenant_id=$1 AND session_id=$2
                """,
                context.tenant_id,
                session_id,
            )
            if result == "UPDATE 0":
                raise ResourceNotFound("会话不存在", session_id=str(session_id))
            await connection.execute(
                """
                INSERT INTO screening.ingest_problems (
                    ingest_problem_id, tenant_id, session_id, segment_index,
                    problem_type, status
                ) VALUES ($1,$2,$3,$4,'CONTENT_CONFLICT','OPEN')
                """,
                uuid4(),
                context.tenant_id,
                session_id,
                index,
            )

    async def list_segments(
        self, context: TerminalContext, session_id: UUID
    ) -> tuple[SegmentRecord, ...]:
        await self.session(context, session_id)
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            rows = await connection.fetch(
                """
                SELECT * FROM screening.session_segments
                WHERE tenant_id=$1 AND session_id=$2 AND status='VERIFIED'
                ORDER BY segment_index
                """,
                context.tenant_id,
                session_id,
            )
            return tuple(self._segment_record(row) for row in rows)

    async def object_is_referenced(self, tenant_id: UUID, object_key: str) -> bool:
        async with tenant_transaction(self._pool, tenant_id) as connection:
            return bool(
                await connection.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM screening.session_segments
                        WHERE tenant_id=$1 AND object_key=$2
                        UNION ALL
                        SELECT 1 FROM screening.session_manifests
                        WHERE tenant_id=$1 AND object_key=$2
                    )
                    """,
                    tenant_id,
                    object_key,
                )
            )

    async def complete_manifest(
        self,
        context: TerminalContext,
        session_id: UUID,
        manifest: SessionManifest,
        manifest_sha256: str,
        object_key: str,
        idempotency_key: str,
    ) -> ManifestCompletionResponse:
        failure: Exception | None = None
        response: ManifestCompletionResponse | None = None
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            replay = await self._idempotency(
                connection,
                context.tenant_id,
                "session.complete",
                idempotency_key,
                manifest_sha256,
            )
            if replay is not None:
                return ManifestCompletionResponse.model_validate(replay).model_copy(
                    update={"idempotent_replay": True}
                )
            session = await connection.fetchrow(
                """
                SELECT * FROM screening.sessions
                WHERE tenant_id=$1 AND session_id=$2 FOR UPDATE
                """,
                context.tenant_id,
                session_id,
            )
            if session is None:
                raise ResourceNotFound("会话不存在", session_id=str(session_id))
            existing = await connection.fetchrow(
                """
                SELECT * FROM screening.session_manifests
                WHERE tenant_id=$1 AND session_id=$2
                """,
                context.tenant_id,
                session_id,
            )
            if existing is not None:
                if existing["manifest_sha256"] != manifest_sha256:
                    raise ManifestConflict("同一会话已存在不同最终清单")
                if existing["verification_status"] == "VERIFIED":
                    response = ManifestCompletionResponse(
                        session_id=session_id,
                        ingest_status=IngestStatus.INGESTED,
                        manifest_sha256=manifest_sha256,
                        idempotent_replay=True,
                    )
            if response is None:
                rows = await connection.fetch(
                    """
                    SELECT segment_index, sha256, size_bytes, frame_count
                    FROM screening.session_segments
                    WHERE tenant_id=$1 AND session_id=$2 AND status='VERIFIED'
                    ORDER BY segment_index
                    """,
                    context.tenant_id,
                    session_id,
                )
                accepted = {
                    row["segment_index"]: (
                        row["sha256"], row["size_bytes"], row["frame_count"]
                    )
                    for row in rows
                }
                declared = {
                    item.index: (item.sha256, item.size_bytes, item.frame_count)
                    for item in manifest.segments
                }
                if accepted != declared:
                    if existing is None:
                        await connection.execute(
                            """
                            INSERT INTO screening.session_manifests (
                                manifest_id, tenant_id, session_id, schema_version,
                                manifest_sha256, object_key, segment_count, total_frames,
                                total_bytes, manifest_json, verification_status
                            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,'PENDING')
                            """,
                            uuid4(),
                            context.tenant_id,
                            session_id,
                            manifest.schema_version,
                            manifest_sha256,
                            object_key,
                            manifest.segment_count,
                            manifest.total_frames,
                            manifest.total_bytes,
                            json.dumps(
                                manifest.model_dump(mode="json"), separators=(",", ":")
                            ),
                        )
                    await connection.execute(
                        """
                        INSERT INTO screening.ingest_problems (
                            ingest_problem_id, tenant_id, session_id,
                            problem_type, safe_evidence, status
                        ) VALUES ($1,$2,$3,'MISSING_SEGMENT',$4::jsonb,'OPEN')
                        """,
                        uuid4(),
                        context.tenant_id,
                        session_id,
                        json.dumps(
                            {
                                "accepted_indices": sorted(accepted),
                                "declared_indices": sorted(declared),
                            },
                            separators=(",", ":"),
                        ),
                    )
                    failure = ManifestIncomplete("最终清单与已接收分段集合不一致")
                else:
                    next_version = session["aggregate_version"] + 1
                    now = datetime.now(UTC)
                    if existing is None:
                        await connection.execute(
                            """
                            INSERT INTO screening.session_manifests (
                                manifest_id, tenant_id, session_id, schema_version,
                                manifest_sha256, object_key, segment_count, total_frames,
                                total_bytes, manifest_json, verification_status, verified_at
                            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,'VERIFIED',$11)
                            """,
                            uuid4(),
                            context.tenant_id,
                            session_id,
                            manifest.schema_version,
                            manifest_sha256,
                            object_key,
                            manifest.segment_count,
                            manifest.total_frames,
                            manifest.total_bytes,
                            json.dumps(
                                manifest.model_dump(mode="json"), separators=(",", ":")
                            ),
                            now,
                        )
                    else:
                        await connection.execute(
                            """
                            UPDATE screening.session_manifests
                            SET verification_status='VERIFIED', verified_at=$3
                            WHERE tenant_id=$1 AND session_id=$2
                            """,
                            context.tenant_id,
                            session_id,
                            now,
                        )
                    await connection.execute(
                        """
                        UPDATE screening.sessions
                        SET validity_status='VALID', ingest_status='INGESTED',
                            ended_at=$3, manifest_sha256=$4,
                            aggregate_version=$5, updated_at=$6
                        WHERE tenant_id=$1 AND session_id=$2
                        """,
                        context.tenant_id,
                        session_id,
                        manifest.ended_at,
                        manifest_sha256,
                        next_version,
                        now,
                    )
                    await connection.execute(
                        """
                        INSERT INTO ops.outbox_events (
                            event_id, event_type, tenant_id, aggregate_type,
                            aggregate_id, aggregate_version, payload
                        ) VALUES ($1,'session.ingested.v1',$2,'screening_session',$3,$4,$5::jsonb)
                        """,
                        uuid4(),
                        context.tenant_id,
                        session_id,
                        next_version,
                        json.dumps(
                            {
                                "session_id": str(session_id),
                                "manifest_sha256": manifest_sha256,
                                "segment_count": manifest.segment_count,
                            },
                            separators=(",", ":"),
                        ),
                    )
                    response = ManifestCompletionResponse(
                        session_id=session_id,
                        ingest_status=IngestStatus.INGESTED,
                        manifest_sha256=manifest_sha256,
                    )
            if response is not None:
                await self._store_idempotency(
                    connection,
                    context.tenant_id,
                    "session.complete",
                    idempotency_key,
                    manifest_sha256,
                    200,
                    response.model_copy(update={"idempotent_replay": False}).model_dump(mode="json"),
                    "screening_session",
                    session_id,
                )
        if failure is not None:
            raise failure
        if response is None:
            raise RuntimeError("manifest completion produced no result")
        return response

    async def expected_segment_count(
        self, context: TerminalContext, session_id: UUID
    ) -> int | None:
        await self.session(context, session_id)
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            return await connection.fetchval(
                """
                SELECT segment_count FROM screening.session_manifests
                WHERE tenant_id=$1 AND session_id=$2
                """,
                context.tenant_id,
                session_id,
            )

    async def status(
        self, context: TerminalContext, session_id: UUID
    ) -> SessionStatusResponse:
        # Authorization rule (commit f7fb6a4): session status is shared within a
        # tenant so a replacement installation can recover a workflow started on
        # a retired terminal. Tenant scope is enforced; terminal ownership is
        # intentionally not checked here, unlike session/segment read methods.
        context.ensure_active()
        async with tenant_transaction(self._pool, context.tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM screening.sessions WHERE tenant_id=$1 AND session_id=$2",
                context.tenant_id,
                session_id,
            )
        if row is None:
            raise ResourceNotFound("会话不存在", session_id=str(session_id))
        record = _session_record(row)
        return SessionStatusResponse(
            session_id=session_id,
            validity_status=record.validity_status,
            ingest_status=record.ingest_status,
        )
    SubjectCreateRequest,
    SubjectSummary,
