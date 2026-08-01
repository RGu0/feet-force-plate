"""PostgreSQL persistence for seed-MVP tenant and Platform access control."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from cloud.api.postgres import tenant_transaction
from shared.contracts.access_control import AccountState, LicenseState, PlatformRole

from .repository import (
    AccessActivationRejected,
    AccessGroupHistoryRecord,
    AccessGroupSeed,
    AccessRepositoryConflict,
    AccessRepositoryError,
    ActivatedAccess,
    ActivationCodeRecord,
    AuthenticationAttemptRecord,
    AuditEventRecord,
    ClientInstallationRecord,
    HardwareAssetRecord,
    HardwareLeaseRecord,
    LicenseEntitlementRecord,
    PlatformIdentityRecord,
    PlatformRoleBindingRecord,
    RefreshSessionRecord,
    SensitiveAccessGrantRecord,
    TenantAccountRecord,
    TenantRecord,
    TenantSeed,
)


def _account(row: Any) -> TenantAccountRecord:
    return TenantAccountRecord(
        tenant_id=row["tenant_id"], account_id=row["account_id"],
        login_name_hmac=bytes(row["login_name_hmac"]), display_name=row["display_name"],
        password_hash=row["password_hash"], status=AccountState(row["status"]),
        token_version=row["token_version"], activated_at=row["activated_at"],
        created_at=row["created_at"],
    )


def _hardware(row: Any) -> HardwareAssetRecord:
    return HardwareAssetRecord(
        tenant_id=row["tenant_id"], hardware_id=row["hardware_id"],
        stable_identity=row["stable_identity"], model=row["model"],
        status=row["status"], created_at=row["created_at"],
    )


def _license(row: Any) -> LicenseEntitlementRecord:
    document = row["document_json"]
    if document is not None and not isinstance(document, str):
        document = json.dumps(document, separators=(",", ":"), sort_keys=True)
    key_id = row["key_id"]
    return LicenseEntitlementRecord(
        tenant_id=row["tenant_id"], license_id=row["license_id"],
        status=LicenseState(row["status"]), enabled_features=tuple(row["enabled_features"]),
        issued_at=row["issued_at"], valid_from=row["valid_from"],
        valid_until=row["valid_until"], version=row["license_version"],
        key_id=None if key_id == "pending" else key_id,
        document_json=document, signature=row["signature"],
    )


def _activation(row: Any) -> ActivationCodeRecord:
    return ActivationCodeRecord(
        tenant_id=row["tenant_id"], activation_code_id=row["activation_code_id"],
        account_id=row["account_id"], license_id=row["license_id"],
        hardware_id=row["hardware_id"], activation_code_hash=bytes(row["activation_code_hash"]),
        expires_at=row["expires_at"], consumed_at=row["consumed_at"],
        created_at=row["created_at"],
    )


def _installation(row: Any) -> ClientInstallationRecord:
    return ClientInstallationRecord(
        tenant_id=row["tenant_id"], client_installation_id=row["client_installation_id"],
        account_id=row["account_id"], first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"], status=row["status"],
    )


def _refresh(row: Any) -> RefreshSessionRecord:
    return RefreshSessionRecord(
        refresh_session_id=row["refresh_session_id"], tenant_id=row["tenant_id"],
        account_id=row["account_id"], client_installation_id=row["client_installation_id"],
        refresh_token_hash=bytes(row["refresh_token_hash"]), issued_at=row["issued_at"],
        last_used_at=row["last_used_at"], idle_expires_at=row["idle_expires_at"],
        absolute_expires_at=row["absolute_expires_at"], rotated_at=row["rotated_at"],
        revoked_at=row["revoked_at"], replaced_by_session_id=row["replaced_by_session_id"],
    )


def _lease(row: Any) -> HardwareLeaseRecord:
    return HardwareLeaseRecord(
        lease_id=row["lease_id"], tenant_id=row["tenant_id"],
        license_id=row["license_id"], account_id=row["account_id"],
        hardware_id=row["hardware_id"], client_installation_id=row["client_installation_id"],
        acquired_at=row["acquired_at"], renewed_at=row["renewed_at"],
        expires_at=row["expires_at"], released_at=row["released_at"],
        release_reason=row["release_reason"],
    )


def _platform_identity(row: Any) -> PlatformIdentityRecord:
    return PlatformIdentityRecord(
        platform_identity_id=row["platform_identity_id"],
        login_name_hmac=bytes(row["login_name_hmac"]), display_name=row["display_name"],
        password_hash=row["password_hash"], status=row["status"],
        token_version=row["token_version"], created_at=row["created_at"],
    )


def _grant(row: Any) -> SensitiveAccessGrantRecord:
    return SensitiveAccessGrantRecord(
        grant_id=row["sensitive_access_grant_id"], tenant_id=row["tenant_id"],
        platform_identity_id=row["platform_identity_id"], purpose_code=row["purpose_code"],
        ticket_reference=row["ticket_reference"], issued_at=row["issued_at"],
        expires_at=row["expires_at"], revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
    )


class PostgresAccessRepository:
    """Pool-separated asyncpg repository; no role silently falls back to another."""

    def __init__(self, *, tenant_pool: Any, activation_pool: Any, platform_pool: Any) -> None:
        if tenant_pool is None or activation_pool is None or platform_pool is None:
            raise ValueError("tenant_pool, activation_pool, and platform_pool are required")
        self._tenant_pool = tenant_pool
        self._activation_pool = activation_pool
        self._platform_pool = platform_pool

    @asynccontextmanager
    async def _plain_transaction(self, pool: Any) -> AsyncIterator[Any]:
        async with pool.acquire() as connection:
            async with connection.transaction():
                yield connection

    async def _tenant_for_resource(self, resource_type: str, resource_id: UUID) -> UUID:
        async with self._plain_transaction(self._activation_pool) as connection:
            tenant_id = await connection.fetchval(
                "SELECT tenant_id FROM ops.access_resource_directory "
                "WHERE resource_type=$1 AND resource_id=$2",
                resource_type, resource_id,
            )
        if tenant_id is None:
            raise AccessRepositoryError(f"{resource_type.lower()} does not exist")
        return tenant_id

    async def _insert_group(
        self, connection: Any, tenant_id: UUID, group: AccessGroupSeed, created_at: datetime
    ) -> None:
        if len(group.login_name_hmac) != 32:
            raise ValueError("account lookup hash must contain 32 bytes")
        if group.license_valid_until <= group.license_valid_from:
            raise ValueError("license validity window is invalid")
        if not group.enabled_features or len(set(group.enabled_features)) != len(group.enabled_features):
            raise ValueError("enabled features must be non-empty and unique")
        await connection.execute(
            """INSERT INTO iam.tenant_accounts
               (account_id,tenant_id,login_name_hmac,display_name,password_hash,status,
                token_version,activated_at,created_at,updated_at)
               VALUES ($1,$2,$3,$4,NULL,'PENDING_ACTIVATION',1,NULL,$5,$5)""",
            group.account_id, tenant_id, group.login_name_hmac,
            group.account_display_name, created_at,
        )
        await connection.execute(
            """INSERT INTO iam.account_login_directory
               (login_name_hmac,tenant_id,account_id,status,created_at)
               VALUES ($1,$2,$3,'PENDING_ACTIVATION',$4)""",
            group.login_name_hmac, tenant_id, group.account_id, created_at,
        )
        await connection.execute(
            """INSERT INTO device.hardware_assets
               (hardware_id,tenant_id,stable_identity,model,status,created_at,updated_at)
               VALUES ($1,$2,$3,$4,'ACTIVE',$5,$5)""",
            group.hardware_id, tenant_id, group.hardware_identity, group.hardware_model, created_at,
        )
        await connection.execute(
            """INSERT INTO device.hardware_identity_directory
               (stable_identity,tenant_id,hardware_id,created_at) VALUES ($1,$2,$3,$4)""",
            group.hardware_identity, tenant_id, group.hardware_id, created_at,
        )
        await connection.execute(
            """INSERT INTO device.license_entitlements
               (license_id,tenant_id,status,enabled_features,issued_at,valid_from,valid_until,
                license_version,key_id,document_json,signature,created_at,updated_at)
               VALUES ($1,$2,'PENDING_ACTIVATION',$3,$4,$5,$6,1,'pending',NULL,NULL,$4,$4)""",
            group.license_id, tenant_id, list(sorted(group.enabled_features)), created_at,
            group.license_valid_from, group.license_valid_until,
        )
        await connection.execute(
            """INSERT INTO device.license_assignments
               (license_assignment_id,tenant_id,license_id,account_id,assigned_at,created_at)
               VALUES ($1,$2,$3,$4,$5,$5)""",
            uuid4(), tenant_id, group.license_id, group.account_id, created_at,
        )
        await connection.execute(
            """INSERT INTO device.hardware_bindings
               (hardware_binding_id,tenant_id,license_id,hardware_id,bound_at,created_at)
               VALUES ($1,$2,$3,$4,$5,$5)""",
            uuid4(), tenant_id, group.license_id, group.hardware_id, created_at,
        )
        await connection.execute(
            """INSERT INTO iam.account_activation_codes
               (activation_code_id,tenant_id,account_id,license_id,hardware_id,
                activation_code_hash,expires_at,created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            group.activation_code_id, tenant_id, group.account_id, group.license_id,
            group.hardware_id, group.activation_code_hash, group.activation_expires_at, created_at,
        )
        for resource_type, resource_id in (
            ("ACCOUNT", group.account_id), ("LICENSE", group.license_id),
            ("HARDWARE", group.hardware_id), ("ACTIVATION_CODE", group.activation_code_id),
        ):
            await connection.execute(
                "INSERT INTO ops.access_resource_directory "
                "(resource_type,resource_id,tenant_id,created_at) VALUES ($1,$2,$3,$4)",
                resource_type, resource_id, tenant_id, created_at,
            )

    async def _ensure_data_plane_projection(
        self,
        connection: Any,
        *,
        tenant_id: UUID,
        account_id: UUID,
        installation_id: UUID,
        projected_at: datetime,
    ) -> None:
        hardware = await connection.fetchrow(
            """SELECT h.hardware_id,h.model
               FROM device.license_assignments la
               JOIN device.hardware_bindings hb
                 ON hb.tenant_id=la.tenant_id AND hb.license_id=la.license_id
                AND hb.unbound_at IS NULL
               JOIN device.hardware_assets h
                 ON h.tenant_id=hb.tenant_id AND h.hardware_id=hb.hardware_id
               WHERE la.tenant_id=$1 AND la.account_id=$2 AND la.unassigned_at IS NULL""",
            tenant_id,
            account_id,
        )
        if hardware is None:
            raise AccessRepositoryConflict("active hardware binding does not exist")
        await connection.execute(
            """INSERT INTO device.devices
               (device_id,tenant_id,model,capabilities,status,created_at,updated_at)
               VALUES ($1,$2,$3,'{}'::jsonb,'ACTIVE',$4,$4)
               ON CONFLICT (device_id) DO NOTHING""",
            hardware["hardware_id"],
            tenant_id,
            hardware["model"],
            projected_at,
        )
        await connection.execute(
            """INSERT INTO device.terminals
               (terminal_id,tenant_id,site_id,installation_id,client_public_key,status,
                last_seen_at,created_at,updated_at)
               VALUES ($1,$2,NULL,$1,'tenant-access-v1','ACTIVE',$3,$3,$3)
               ON CONFLICT (terminal_id) DO UPDATE
               SET status='ACTIVE',last_seen_at=GREATEST(device.terminals.last_seen_at,$3),
                   updated_at=GREATEST(device.terminals.updated_at,$3)""",
            installation_id,
            tenant_id,
            projected_at,
        )
        await connection.execute(
            """INSERT INTO device.terminal_device_bindings
               (terminal_device_binding_id,tenant_id,terminal_id,device_id,valid_from,created_at)
               SELECT $1,$2,$3,$4,$5,$5
               WHERE NOT EXISTS (
                   SELECT 1 FROM device.terminal_device_bindings
                   WHERE tenant_id=$2 AND terminal_id=$3 AND device_id=$4 AND valid_to IS NULL
               )""",
            uuid4(),
            tenant_id,
            installation_id,
            hardware["hardware_id"],
            projected_at,
        )

    async def provision_tenant(
        self, tenant: TenantSeed, group: AccessGroupSeed, *, created_at: datetime
    ) -> None:
        if not tenant.name.strip():
            raise ValueError("tenant name is required")
        try:
            async with self._plain_transaction(self._platform_pool) as connection:
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant.tenant_id)
                )
                await connection.execute(
                    "INSERT INTO iam.tenants (tenant_id,name,status,created_at,updated_at) "
                    "VALUES ($1,$2,'ACTIVE',$3,$3)",
                    tenant.tenant_id, tenant.name.strip(), created_at,
                )
                await self._insert_group(connection, tenant.tenant_id, group, created_at)
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise ValueError("tenant or access group already exists") from exc
            raise

    async def add_access_group(
        self, tenant_id: UUID, group: AccessGroupSeed, *, created_at: datetime
    ) -> None:
        try:
            async with tenant_transaction(self._platform_pool, tenant_id) as connection:
                exists = await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM iam.tenants WHERE tenant_id=$1)", tenant_id
                )
                if not exists:
                    raise ValueError("tenant does not exist")
                await self._insert_group(connection, tenant_id, group, created_at)
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise ValueError("account, hardware, License, or activation code already exists") from exc
            raise

    async def activate_account_atomically(
        self, *, login_name_hmac: bytes, activation_code_hash: bytes,
        hardware_identity: str, password_hash: str, installation_id: UUID,
        activated_at: datetime, license_key_id: str | None = None,
        license_document_json: str | None = None, license_signature: str | None = None,
    ) -> ActivatedAccess:
        signed = (license_key_id, license_document_json, license_signature)
        if any(value is not None for value in signed) and not all(value is not None for value in signed):
            raise ValueError("signed License fields must be stored together")
        async with self._plain_transaction(self._activation_pool) as directory_connection:
            directory = await directory_connection.fetchrow(
                "SELECT tenant_id,account_id FROM iam.account_login_directory "
                "WHERE login_name_hmac=$1", login_name_hmac,
            )
        if directory is None:
            raise AccessActivationRejected("activation credentials do not match")
        tenant_id = directory["tenant_id"]
        try:
            async with tenant_transaction(self._activation_pool, tenant_id) as connection:
                row = await connection.fetchrow(
                    """SELECT a.*, c.activation_code_id,c.license_id,c.hardware_id,
                              c.activation_code_hash,c.expires_at,c.consumed_at,
                              c.created_at AS activation_created_at,
                              h.stable_identity,h.model,h.status AS hardware_status,
                              h.created_at AS hardware_created_at,
                              l.status AS license_status,l.enabled_features,l.issued_at,
                              l.valid_from,l.valid_until,l.license_version,l.key_id,
                              l.document_json,l.signature,l.created_at AS license_created_at
                       FROM iam.tenant_accounts a
                       JOIN iam.account_activation_codes c
                         ON c.tenant_id=a.tenant_id AND c.account_id=a.account_id
                       JOIN device.hardware_assets h
                         ON h.tenant_id=c.tenant_id AND h.hardware_id=c.hardware_id
                       JOIN device.license_entitlements l
                         ON l.tenant_id=c.tenant_id AND l.license_id=c.license_id
                       WHERE a.account_id=$1 AND c.activation_code_hash=$2
                       FOR UPDATE OF a,c,l""",
                    directory["account_id"], activation_code_hash,
                )
                if (
                    row is None or row["stable_identity"] != hardware_identity
                    or row["consumed_at"] is not None or row["expires_at"] <= activated_at
                    or row["status"] != "PENDING_ACTIVATION"
                    or row["license_status"] != "PENDING_ACTIVATION" or not password_hash
                ):
                    raise AccessActivationRejected("activation credentials do not match")
                duplicate = await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM device.client_installations "
                    "WHERE client_installation_id=$1)", installation_id,
                )
                if duplicate:
                    raise AccessActivationRejected("activation credentials do not match")
                await connection.execute(
                    "UPDATE iam.tenant_accounts SET password_hash=$2,status='ACTIVE',"
                    "activated_at=$3,updated_at=$3 WHERE tenant_id=$1 AND account_id=$4",
                    tenant_id, password_hash, activated_at, row["account_id"],
                )
                await connection.execute(
                    "UPDATE iam.account_login_directory SET status='ACTIVE' "
                    "WHERE login_name_hmac=$1", login_name_hmac,
                )
                await connection.execute(
                    "UPDATE iam.account_activation_codes SET consumed_at=$3 "
                    "WHERE tenant_id=$1 AND activation_code_id=$2",
                    tenant_id, row["activation_code_id"], activated_at,
                )
                await connection.execute(
                    """UPDATE device.license_entitlements
                       SET status='ACTIVE',issued_at=$3,key_id=$4,document_json=$5::jsonb,
                           signature=$6,updated_at=$3
                       WHERE tenant_id=$1 AND license_id=$2""",
                    tenant_id, row["license_id"], activated_at,
                    license_key_id or "pending", license_document_json, license_signature,
                )
                await connection.execute(
                    """INSERT INTO device.client_installations
                       (client_installation_id,tenant_id,account_id,first_seen_at,last_seen_at,
                        status,created_at,updated_at)
                       VALUES ($1,$2,$3,$4,$4,'ACTIVE',$4,$4)""",
                    installation_id, tenant_id, row["account_id"], activated_at,
                )
                await connection.execute(
                    "INSERT INTO ops.access_resource_directory "
                    "(resource_type,resource_id,tenant_id,created_at) "
                    "VALUES ('INSTALLATION',$1,$2,$3)", installation_id, tenant_id, activated_at,
                )
                await self._ensure_data_plane_projection(
                    connection,
                    tenant_id=tenant_id,
                    account_id=row["account_id"],
                    installation_id=installation_id,
                    projected_at=activated_at,
                )
                account_row = await connection.fetchrow(
                    "SELECT * FROM iam.tenant_accounts WHERE account_id=$1", row["account_id"]
                )
                license_row = await connection.fetchrow(
                    "SELECT * FROM device.license_entitlements WHERE license_id=$1", row["license_id"]
                )
                installation_row = await connection.fetchrow(
                    "SELECT * FROM device.client_installations WHERE client_installation_id=$1",
                    installation_id,
                )
                tenant_row = await connection.fetchrow(
                    "SELECT * FROM iam.tenants WHERE tenant_id=$1", tenant_id
                )
                hardware_row = {
                    "tenant_id": tenant_id, "hardware_id": row["hardware_id"],
                    "stable_identity": row["stable_identity"], "model": row["model"],
                    "status": row["hardware_status"], "created_at": row["hardware_created_at"],
                }
                activation_row = {
                    "tenant_id": tenant_id, "activation_code_id": row["activation_code_id"],
                    "account_id": row["account_id"], "license_id": row["license_id"],
                    "hardware_id": row["hardware_id"],
                    "activation_code_hash": row["activation_code_hash"],
                    "expires_at": row["expires_at"], "consumed_at": activated_at,
                    "created_at": row["activation_created_at"],
                }
                return ActivatedAccess(
                    tenant=TenantRecord(tenant_row["tenant_id"], tenant_row["name"],
                                        tenant_row["status"], tenant_row["created_at"]),
                    account=_account(account_row), license=_license(license_row),
                    hardware=_hardware(hardware_row), activation_code=_activation(activation_row),
                    installation=_installation(installation_row),
                )
        except AccessActivationRejected:
            raise
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23505", "23514"}:
                raise AccessActivationRejected("activation credentials do not match") from exc
            raise

    async def tenant(self, tenant_id: UUID) -> TenantRecord:
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            row = await connection.fetchrow("SELECT * FROM iam.tenants WHERE tenant_id=$1", tenant_id)
        if row is None:
            raise AccessRepositoryError("tenant does not exist")
        return TenantRecord(row["tenant_id"], row["name"], row["status"], row["created_at"])

    async def account(self, account_id: UUID) -> TenantAccountRecord:
        tenant_id = await self._tenant_for_resource("ACCOUNT", account_id)
        async with tenant_transaction(self._activation_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM iam.tenant_accounts WHERE account_id=$1", account_id
            )
        if row is None:
            raise AccessRepositoryError("account does not exist")
        return _account(row)

    async def account_by_login_hmac(self, login_name_hmac: bytes) -> TenantAccountRecord | None:
        async with self._plain_transaction(self._activation_pool) as connection:
            route = await connection.fetchrow(
                "SELECT tenant_id,account_id FROM iam.account_login_directory "
                "WHERE login_name_hmac=$1", login_name_hmac,
            )
        if route is None:
            return None
        async with tenant_transaction(self._activation_pool, route["tenant_id"]) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM iam.tenant_accounts WHERE account_id=$1", route["account_id"]
            )
        return None if row is None else _account(row)

    async def activation_code(self, activation_code_id: UUID) -> ActivationCodeRecord | None:
        try:
            tenant_id = await self._tenant_for_resource("ACTIVATION_CODE", activation_code_id)
        except AccessRepositoryError:
            return None
        async with tenant_transaction(self._activation_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM iam.account_activation_codes WHERE activation_code_id=$1",
                activation_code_id,
            )
        return None if row is None else _activation(row)

    async def license(self, license_id: UUID) -> LicenseEntitlementRecord:
        tenant_id = await self._tenant_for_resource("LICENSE", license_id)
        async with tenant_transaction(self._activation_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM device.license_entitlements WHERE license_id=$1", license_id
            )
        if row is None:
            raise AccessRepositoryError("license does not exist")
        return _license(row)

    async def hardware(self, hardware_id: UUID) -> HardwareAssetRecord:
        tenant_id = await self._tenant_for_resource("HARDWARE", hardware_id)
        async with tenant_transaction(self._activation_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM device.hardware_assets WHERE hardware_id=$1", hardware_id
            )
        if row is None:
            raise AccessRepositoryError("hardware does not exist")
        return _hardware(row)

    async def hardware_by_identity(self, stable_identity: str) -> HardwareAssetRecord | None:
        async with self._plain_transaction(self._activation_pool) as connection:
            route = await connection.fetchrow(
                "SELECT tenant_id,hardware_id FROM device.hardware_identity_directory "
                "WHERE stable_identity=$1", stable_identity,
            )
        if route is None:
            return None
        async with tenant_transaction(self._activation_pool, route["tenant_id"]) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM device.hardware_assets WHERE hardware_id=$1", route["hardware_id"]
            )
        return None if row is None else _hardware(row)

    @staticmethod
    def _history(row: Any) -> AccessGroupHistoryRecord:
        return AccessGroupHistoryRecord(
            tenant_id=row["tenant_id"], account_id=row["account_id"],
            license_id=row["license_id"], hardware_id=row["hardware_id"],
            assigned_at=row["assigned_at"], closed_at=row["unassigned_at"],
            close_reason_code=row["reason_code"],
        )

    async def _history_rows(self, tenant_id: UUID, *, active_only: bool) -> tuple[AccessGroupHistoryRecord, ...]:
        where = "AND la.unassigned_at IS NULL" if active_only else ""
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            rows = await connection.fetch(
                f"""SELECT la.tenant_id,la.account_id,la.license_id,hb.hardware_id,
                           la.assigned_at,la.unassigned_at,la.reason_code
                    FROM device.license_assignments la
                    JOIN device.hardware_bindings hb
                      ON hb.tenant_id=la.tenant_id AND hb.license_id=la.license_id
                     AND hb.bound_at=la.assigned_at
                    WHERE la.tenant_id=$1 {where}
                    ORDER BY la.assigned_at,la.license_id""",
                tenant_id,
            )
        return tuple(self._history(row) for row in rows)

    async def active_access_groups(self, tenant_id: UUID) -> tuple[AccessGroupHistoryRecord, ...]:
        return await self._history_rows(tenant_id, active_only=True)

    async def access_group_history(self, tenant_id: UUID) -> tuple[AccessGroupHistoryRecord, ...]:
        return await self._history_rows(tenant_id, active_only=False)

    async def active_group_for_account(self, account_id: UUID) -> AccessGroupHistoryRecord:
        tenant_id = await self._tenant_for_resource("ACCOUNT", account_id)
        async with tenant_transaction(self._activation_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT la.tenant_id,la.account_id,la.license_id,hb.hardware_id,
                          la.assigned_at,la.unassigned_at,la.reason_code
                   FROM device.license_assignments la
                   JOIN device.hardware_bindings hb
                     ON hb.tenant_id=la.tenant_id AND hb.license_id=la.license_id
                    AND hb.unbound_at IS NULL
                   WHERE la.account_id=$1 AND la.unassigned_at IS NULL
                   ORDER BY la.assigned_at DESC LIMIT 1""",
                account_id,
            )
        if row is None:
            raise AccessRepositoryError("active account access group does not exist")
        return self._history(row)

    async def access_group_for_license(self, license_id: UUID) -> AccessGroupHistoryRecord:
        tenant_id = await self._tenant_for_resource("LICENSE", license_id)
        async with tenant_transaction(self._activation_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT la.tenant_id,la.account_id,la.license_id,hb.hardware_id,
                          la.assigned_at,la.unassigned_at,la.reason_code
                   FROM device.license_assignments la
                   JOIN device.hardware_bindings hb
                     ON hb.tenant_id=la.tenant_id AND hb.license_id=la.license_id
                    AND hb.unbound_at IS NULL
                   WHERE la.license_id=$1 AND la.unassigned_at IS NULL
                   ORDER BY la.assigned_at DESC LIMIT 1""",
                license_id,
            )
        if row is None:
            raise AccessRepositoryError("active access group does not exist")
        return self._history(row)

    async def close_access_group(
        self, *, tenant_id: UUID, license_id: UUID, closed_at: datetime, reason_code: str
    ) -> UUID:
        if not reason_code.strip():
            raise ValueError("close reason is required")
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT license_assignment_id,assigned_at FROM device.license_assignments
                   WHERE tenant_id=$1 AND license_id=$2 AND unassigned_at IS NULL FOR UPDATE""",
                tenant_id, license_id,
            )
            if row is None:
                raise AccessRepositoryConflict("active access group does not exist")
            if closed_at <= row["assigned_at"]:
                raise ValueError("closed_at must follow assigned_at")
            await connection.execute(
                "UPDATE device.license_assignments SET unassigned_at=$3,reason_code=$4 "
                "WHERE tenant_id=$1 AND license_id=$2 AND unassigned_at IS NULL",
                tenant_id, license_id, closed_at, reason_code.strip(),
            )
            await connection.execute(
                "UPDATE device.hardware_bindings SET unbound_at=$3,reason_code=$4 "
                "WHERE tenant_id=$1 AND license_id=$2 AND unbound_at IS NULL",
                tenant_id, license_id, closed_at, reason_code.strip(),
            )
            await connection.execute(
                "UPDATE device.license_entitlements SET status='SUSPENDED',"
                "license_version=license_version+1,updated_at=$3 "
                "WHERE tenant_id=$1 AND license_id=$2", tenant_id, license_id, closed_at,
            )
        return license_id

    async def register_or_touch_installation(
        self, *, tenant_id: UUID, account_id: UUID, installation_id: UUID, seen_at: datetime
    ) -> ClientInstallationRecord:
        async with tenant_transaction(self._activation_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM device.client_installations WHERE client_installation_id=$1 FOR UPDATE",
                installation_id,
            )
            if row is not None:
                if row["tenant_id"] != tenant_id or row["account_id"] != account_id:
                    raise AccessRepositoryConflict("installation belongs to another account")
                if row["status"] != "ACTIVE":
                    raise AccessRepositoryConflict("installation is revoked")
                row = await connection.fetchrow(
                    """UPDATE device.client_installations
                       SET last_seen_at=GREATEST(last_seen_at,$2),updated_at=GREATEST(updated_at,$2)
                       WHERE client_installation_id=$1 RETURNING *""",
                    installation_id, seen_at,
                )
            else:
                row = await connection.fetchrow(
                    """INSERT INTO device.client_installations
                       (client_installation_id,tenant_id,account_id,first_seen_at,last_seen_at,
                        status,created_at,updated_at)
                       VALUES ($1,$2,$3,$4,$4,'ACTIVE',$4,$4) RETURNING *""",
                    installation_id, tenant_id, account_id, seen_at,
                )
                await connection.execute(
                    "INSERT INTO ops.access_resource_directory "
                    "(resource_type,resource_id,tenant_id,created_at) "
                    "VALUES ('INSTALLATION',$1,$2,$3)", installation_id, tenant_id, seen_at,
                )
            await self._ensure_data_plane_projection(
                connection,
                tenant_id=tenant_id,
                account_id=account_id,
                installation_id=installation_id,
                projected_at=seen_at,
            )
        return _installation(row)

    async def create_refresh_session(self, session: RefreshSessionRecord) -> RefreshSessionRecord:
        try:
            async with tenant_transaction(self._activation_pool, session.tenant_id) as connection:
                await connection.execute(
                    """INSERT INTO iam.tenant_refresh_sessions
                       (refresh_session_id,tenant_id,account_id,client_installation_id,
                        refresh_token_hash,issued_at,last_used_at,idle_expires_at,
                        absolute_expires_at,rotated_at,revoked_at,replaced_by_session_id,created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$6)""",
                    session.refresh_session_id, session.tenant_id, session.account_id,
                    session.client_installation_id, session.refresh_token_hash, session.issued_at,
                    session.last_used_at, session.idle_expires_at, session.absolute_expires_at,
                    session.rotated_at, session.revoked_at, session.replaced_by_session_id,
                )
                await connection.execute(
                    "INSERT INTO iam.refresh_session_directory "
                    "(refresh_token_hash,tenant_id,refresh_session_id,created_at) VALUES ($1,$2,$3,$4)",
                    session.refresh_token_hash, session.tenant_id,
                    session.refresh_session_id, session.issued_at,
                )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505"}:
                raise AccessRepositoryConflict("refresh session already exists or is invalid") from exc
            raise
        return session

    async def refresh_session_by_hash(self, token_hash: bytes) -> RefreshSessionRecord | None:
        async with self._plain_transaction(self._activation_pool) as connection:
            route = await connection.fetchrow(
                "SELECT tenant_id,refresh_session_id FROM iam.refresh_session_directory "
                "WHERE refresh_token_hash=$1", token_hash,
            )
        if route is None:
            return None
        async with tenant_transaction(self._activation_pool, route["tenant_id"]) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM iam.tenant_refresh_sessions WHERE refresh_session_id=$1",
                route["refresh_session_id"],
            )
        return None if row is None else _refresh(row)

    async def rotate_refresh_session(
        self, *, current_token_hash: bytes, expected_installation_id: UUID,
        replacement: RefreshSessionRecord, rotated_at: datetime,
    ) -> RefreshSessionRecord:
        async with self._plain_transaction(self._activation_pool) as connection:
            route = await connection.fetchrow(
                "SELECT tenant_id,refresh_session_id FROM iam.refresh_session_directory "
                "WHERE refresh_token_hash=$1", current_token_hash,
            )
        if route is None:
            raise AccessActivationRejected("refresh credential is invalid")
        try:
            async with tenant_transaction(self._activation_pool, route["tenant_id"]) as connection:
                current_row = await connection.fetchrow(
                    "SELECT * FROM iam.tenant_refresh_sessions "
                    "WHERE refresh_session_id=$1 FOR UPDATE", route["refresh_session_id"],
                )
                if current_row is None:
                    raise AccessActivationRejected("refresh credential is invalid")
                current = _refresh(current_row)
                if (
                    current.client_installation_id != expected_installation_id
                    or current.rotated_at is not None or current.revoked_at is not None
                    or current.idle_expires_at <= rotated_at
                    or current.absolute_expires_at <= rotated_at
                    or replacement.tenant_id != current.tenant_id
                    or replacement.account_id != current.account_id
                    or replacement.client_installation_id != current.client_installation_id
                    or replacement.absolute_expires_at != current.absolute_expires_at
                ):
                    raise AccessActivationRejected("refresh credential is invalid")
                await connection.execute(
                    """INSERT INTO iam.tenant_refresh_sessions
                       (refresh_session_id,tenant_id,account_id,client_installation_id,
                        refresh_token_hash,issued_at,last_used_at,idle_expires_at,
                        absolute_expires_at,created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$6)""",
                    replacement.refresh_session_id, replacement.tenant_id,
                    replacement.account_id, replacement.client_installation_id,
                    replacement.refresh_token_hash, replacement.issued_at,
                    replacement.last_used_at, replacement.idle_expires_at,
                    replacement.absolute_expires_at,
                )
                await connection.execute(
                    "INSERT INTO iam.refresh_session_directory "
                    "(refresh_token_hash,tenant_id,refresh_session_id,created_at) "
                    "VALUES ($1,$2,$3,$4)", replacement.refresh_token_hash,
                    replacement.tenant_id, replacement.refresh_session_id, replacement.issued_at,
                )
                await connection.execute(
                    """UPDATE iam.tenant_refresh_sessions
                       SET rotated_at=$2,last_used_at=$2,replaced_by_session_id=$3
                       WHERE refresh_session_id=$1""",
                    current.refresh_session_id, rotated_at, replacement.refresh_session_id,
                )
        except AccessActivationRejected:
            raise
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505"}:
                raise AccessActivationRejected("refresh credential is invalid") from exc
            raise
        return replacement

    async def revoke_refresh_session(self, token_hash: bytes, *, revoked_at: datetime) -> None:
        async with self._plain_transaction(self._activation_pool) as connection:
            route = await connection.fetchrow(
                "SELECT tenant_id,refresh_session_id FROM iam.refresh_session_directory "
                "WHERE refresh_token_hash=$1", token_hash,
            )
        if route is None:
            return
        async with tenant_transaction(self._activation_pool, route["tenant_id"]) as connection:
            await connection.execute(
                "UPDATE iam.tenant_refresh_sessions SET revoked_at=COALESCE(revoked_at,$2) "
                "WHERE refresh_session_id=$1", route["refresh_session_id"], revoked_at,
            )

    async def record_authentication_attempt(self, attempt: AuthenticationAttemptRecord) -> None:
        async with self._plain_transaction(self._activation_pool) as connection:
            await connection.execute(
                """INSERT INTO ops.authentication_attempts
                   (authentication_attempt_id,login_name_hmac,source_fingerprint,
                    attempt_kind,succeeded,attempted_at,created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$6)""",
                attempt.authentication_attempt_id, attempt.login_name_hmac,
                attempt.source_fingerprint, attempt.attempt_kind, attempt.succeeded,
                attempt.attempted_at,
            )

    async def failed_authentication_attempts(
        self, *, login_name_hmac: bytes, source_fingerprint: bytes, since: datetime
    ) -> int:
        async with self._plain_transaction(self._activation_pool) as connection:
            count = await connection.fetchval(
                """SELECT count(*) FROM ops.authentication_attempts
                   WHERE login_name_hmac=$1 AND source_fingerprint=$2
                     AND succeeded=false AND attempted_at >= $3""",
                login_name_hmac, source_fingerprint, since,
            )
        return int(count)

    async def replace_license(
        self, *, license_id: UUID, expected_version: int, status: LicenseState,
        issued_at: datetime, valid_until: datetime, key_id: str,
        document_json: str, signature: str,
    ) -> LicenseEntitlementRecord:
        tenant_id = await self._tenant_for_resource("LICENSE", license_id)
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            current = await connection.fetchrow(
                "SELECT * FROM device.license_entitlements WHERE license_id=$1 FOR UPDATE",
                license_id,
            )
            if current is None:
                raise AccessRepositoryError("license does not exist")
            if current["license_version"] != expected_version:
                raise AccessRepositoryConflict("license version changed concurrently")
            if valid_until <= current["valid_from"]:
                raise ValueError("license validity window is invalid")
            row = await connection.fetchrow(
                """UPDATE device.license_entitlements
                   SET status=$2,issued_at=$3,valid_until=$4,license_version=license_version+1,
                       key_id=$5,document_json=$6::jsonb,signature=$7,updated_at=$3
                   WHERE license_id=$1 RETURNING *""",
                license_id, status.value, issued_at, valid_until, key_id,
                document_json, signature,
            )
        return _license(row)

    async def acquire_hardware_lease(
        self, lease: HardwareLeaseRecord, *, acquired_at: datetime
    ) -> HardwareLeaseRecord:
        try:
            async with tenant_transaction(self._tenant_pool, lease.tenant_id) as connection:
                current_row = await connection.fetchrow(
                    "SELECT * FROM device.hardware_leases "
                    "WHERE hardware_id=$1 AND released_at IS NULL FOR UPDATE",
                    lease.hardware_id,
                )
                if current_row is not None:
                    current = _lease(current_row)
                    if current.expires_at > acquired_at:
                        if (
                            current.tenant_id == lease.tenant_id
                            and current.license_id == lease.license_id
                            and current.account_id == lease.account_id
                            and current.client_installation_id == lease.client_installation_id
                        ):
                            return current
                        raise AccessRepositoryConflict("hardware already has an active lease")
                    await connection.execute(
                        "UPDATE device.hardware_leases SET released_at=$2,"
                        "release_reason='TTL_EXPIRED' WHERE lease_id=$1",
                        current.lease_id, max(current.expires_at, acquired_at),
                    )
                valid = await connection.fetchval(
                    """SELECT EXISTS (
                         SELECT 1 FROM device.license_assignments la
                         JOIN device.hardware_bindings hb
                           ON hb.tenant_id=la.tenant_id AND hb.license_id=la.license_id
                         JOIN device.client_installations ci
                           ON ci.tenant_id=la.tenant_id AND ci.account_id=la.account_id
                         WHERE la.tenant_id=$1 AND la.license_id=$2 AND la.account_id=$3
                           AND hb.hardware_id=$4 AND ci.client_installation_id=$5
                           AND la.unassigned_at IS NULL AND hb.unbound_at IS NULL
                           AND ci.status='ACTIVE')""",
                    lease.tenant_id, lease.license_id, lease.account_id,
                    lease.hardware_id, lease.client_installation_id,
                )
                if not valid or lease.expires_at <= acquired_at:
                    raise AccessRepositoryConflict("hardware lease binding is invalid")
                row = await connection.fetchrow(
                    """INSERT INTO device.hardware_leases
                       (lease_id,tenant_id,license_id,account_id,hardware_id,
                        client_installation_id,acquired_at,renewed_at,expires_at,
                        released_at,release_reason,created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$7) RETURNING *""",
                    lease.lease_id, lease.tenant_id, lease.license_id, lease.account_id,
                    lease.hardware_id, lease.client_installation_id, lease.acquired_at,
                    lease.renewed_at, lease.expires_at, lease.released_at, lease.release_reason,
                )
                return _lease(row)
        except AccessRepositoryConflict:
            raise
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514"}:
                raise AccessRepositoryConflict("hardware lease binding is invalid") from exc
            raise

    async def renew_hardware_lease(
        self, *, lease_id: UUID, tenant_id: UUID, account_id: UUID,
        license_id: UUID, installation_id: UUID, renewed_at: datetime, expires_at: datetime,
    ) -> HardwareLeaseRecord:
        async with tenant_transaction(self._tenant_pool, tenant_id) as connection:
            current_row = await connection.fetchrow(
                "SELECT * FROM device.hardware_leases WHERE lease_id=$1 FOR UPDATE", lease_id
            )
            if current_row is None:
                raise AccessRepositoryConflict("hardware lease cannot be renewed")
            current = _lease(current_row)
            if (
                current.tenant_id != tenant_id or current.account_id != account_id
                or current.license_id != license_id
                or current.client_installation_id != installation_id
                or current.released_at is not None or current.expires_at <= renewed_at
                or expires_at <= renewed_at
            ):
                raise AccessRepositoryConflict("hardware lease cannot be renewed")
            row = await connection.fetchrow(
                "UPDATE device.hardware_leases SET renewed_at=$2,expires_at=$3 "
                "WHERE lease_id=$1 RETURNING *", lease_id, renewed_at, expires_at,
            )
        return _lease(row)

    async def release_hardware_lease(
        self, *, lease_id: UUID, tenant_id: UUID, account_id: UUID,
        license_id: UUID, installation_id: UUID, released_at: datetime, reason: str,
    ) -> None:
        async with tenant_transaction(self._tenant_pool, tenant_id) as connection:
            current_row = await connection.fetchrow(
                "SELECT * FROM device.hardware_leases WHERE lease_id=$1 FOR UPDATE", lease_id
            )
            if current_row is None:
                raise AccessRepositoryConflict("hardware lease cannot be released")
            current = _lease(current_row)
            if (
                current.tenant_id != tenant_id or current.account_id != account_id
                or current.license_id != license_id
                or current.client_installation_id != installation_id
            ):
                raise AccessRepositoryConflict("hardware lease cannot be released")
            if current.released_at is None:
                await connection.execute(
                    "UPDATE device.hardware_leases SET released_at=$2,release_reason=$3 "
                    "WHERE lease_id=$1", lease_id,
                    max(released_at, current.acquired_at), reason,
                )

    async def append_audit(self, event: AuditEventRecord) -> None:
        details = json.dumps(dict(event.details), separators=(",", ":"), sort_keys=True)
        async with self._plain_transaction(self._platform_pool) as connection:
            await connection.execute(
                """INSERT INTO ops.access_audit_events
                   (access_audit_event_id,actor_id,action,tenant_id,resource_id,occurred_at,details)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)""",
                event.event_id, event.actor_id, event.action, event.tenant_id,
                event.resource_id, event.occurred_at, details,
            )

    async def audit_events(self, *, tenant_id: UUID | None = None) -> tuple[AuditEventRecord, ...]:
        query = "SELECT * FROM ops.access_audit_events"
        args: tuple[Any, ...] = ()
        if tenant_id is not None:
            query += " WHERE tenant_id=$1"
            args = (tenant_id,)
        query += " ORDER BY occurred_at,access_audit_event_id"
        async with self._plain_transaction(self._platform_pool) as connection:
            rows = await connection.fetch(query, *args)
        return tuple(
            AuditEventRecord(
                event_id=row["access_audit_event_id"], actor_id=row["actor_id"],
                action=row["action"], tenant_id=row["tenant_id"],
                resource_id=row["resource_id"], occurred_at=row["occurred_at"],
                details=tuple(sorted(dict(row["details"]).items())),
            )
            for row in rows
        )

    async def activation_storage_contains(self, raw_code: str) -> bool:
        # PostgreSQL stores only keyed digests. Raw activation codes are never
        # accepted as lookup values or persisted by this adapter.
        return False

    async def platform_identity_count(self) -> int:
        async with self._plain_transaction(self._platform_pool) as connection:
            count = await connection.fetchval("SELECT count(*) FROM iam.platform_identities")
        return int(count)

    async def create_platform_identity(
        self, identity: PlatformIdentityRecord,
        roles: tuple[PlatformRoleBindingRecord, ...],
    ) -> PlatformIdentityRecord:
        if (
            not roles
            or any(row.platform_identity_id != identity.platform_identity_id for row in roles)
            or len({row.role for row in roles}) != len(roles)
        ):
            raise ValueError("platform roles must be non-empty and unique")
        try:
            async with self._plain_transaction(self._platform_pool) as connection:
                await connection.execute(
                    """INSERT INTO iam.platform_identities
                       (platform_identity_id,login_name_hmac,display_name,password_hash,
                        status,token_version,created_at,updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$7)""",
                    identity.platform_identity_id, identity.login_name_hmac,
                    identity.display_name, identity.password_hash, identity.status,
                    identity.token_version, identity.created_at,
                )
                for binding in roles:
                    await connection.execute(
                        """INSERT INTO iam.platform_identity_role_bindings
                           (platform_identity_role_binding_id,platform_identity_id,
                            platform_role_id,valid_from,valid_to,created_at)
                           SELECT $1,$2,platform_role_id,$4,$5,$4
                           FROM iam.platform_roles WHERE role_name=$3""",
                        binding.binding_id, binding.platform_identity_id,
                        binding.role.value, binding.valid_from, binding.valid_to,
                    )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise AccessRepositoryConflict("platform identity already exists") from exc
            raise
        return identity

    async def platform_identity_by_login_hmac(
        self, login_name_hmac: bytes
    ) -> PlatformIdentityRecord | None:
        async with self._plain_transaction(self._platform_pool) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM iam.platform_identities WHERE login_name_hmac=$1",
                login_name_hmac,
            )
        return None if row is None else _platform_identity(row)

    async def platform_roles(
        self, platform_identity_id: UUID, *, at: datetime
    ) -> tuple[PlatformRole, ...]:
        async with self._plain_transaction(self._platform_pool) as connection:
            rows = await connection.fetch(
                """SELECT r.role_name FROM iam.platform_identity_role_bindings b
                   JOIN iam.platform_roles r ON r.platform_role_id=b.platform_role_id
                   WHERE b.platform_identity_id=$1 AND b.valid_from <= $2
                     AND (b.valid_to IS NULL OR $2 < b.valid_to)
                   ORDER BY r.role_name""",
                platform_identity_id, at,
            )
        return tuple(PlatformRole(row["role_name"]) for row in rows)

    async def list_tenants(self) -> tuple[TenantRecord, ...]:
        async with self._plain_transaction(self._platform_pool) as connection:
            rows = await connection.fetch("SELECT * FROM iam.tenants ORDER BY tenant_id")
        return tuple(
            TenantRecord(row["tenant_id"], row["name"], row["status"], row["created_at"])
            for row in rows
        )

    async def tenant_access_counts(self, tenant_id: UUID) -> tuple[int, int]:
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                """SELECT count(DISTINCT account_id) AS account_count,
                          count(DISTINCT license_id) AS license_count
                   FROM device.license_assignments
                   WHERE tenant_id=$1 AND unassigned_at IS NULL""", tenant_id,
            )
        return int(row["account_count"]), int(row["license_count"])

    async def create_sensitive_grant(
        self, grant: SensitiveAccessGrantRecord
    ) -> SensitiveAccessGrantRecord:
        if grant.expires_at <= grant.issued_at or grant.expires_at - grant.issued_at > timedelta(minutes=15):
            raise ValueError("sensitive grant duration is invalid")
        try:
            async with tenant_transaction(self._platform_pool, grant.tenant_id) as connection:
                await connection.execute(
                    """INSERT INTO ops.sensitive_access_grants
                       (sensitive_access_grant_id,tenant_id,platform_identity_id,purpose_code,
                        ticket_reference,issued_at,expires_at,revoked_at,last_used_at,created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$6)""",
                    grant.grant_id, grant.tenant_id, grant.platform_identity_id,
                    grant.purpose_code, grant.ticket_reference, grant.issued_at,
                    grant.expires_at, grant.revoked_at, grant.last_used_at,
                )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise AccessRepositoryConflict("sensitive grant already exists") from exc
            if getattr(exc, "sqlstate", None) == "23503":
                raise AccessRepositoryError("tenant or Platform identity does not exist") from exc
            raise
        return grant

    async def use_sensitive_grant(
        self, *, grant_id: UUID, tenant_id: UUID,
        platform_identity_id: UUID, used_at: datetime,
    ) -> SensitiveAccessGrantRecord:
        async with tenant_transaction(self._platform_pool, tenant_id) as connection:
            row = await connection.fetchrow(
                "SELECT * FROM ops.sensitive_access_grants "
                "WHERE sensitive_access_grant_id=$1 FOR UPDATE", grant_id,
            )
            if (
                row is None or row["tenant_id"] != tenant_id
                or row["platform_identity_id"] != platform_identity_id
                or row["revoked_at"] is not None or row["expires_at"] <= used_at
            ):
                raise AccessRepositoryConflict("sensitive grant is invalid")
            row = await connection.fetchrow(
                "UPDATE ops.sensitive_access_grants SET last_used_at=$2 "
                "WHERE sensitive_access_grant_id=$1 RETURNING *", grant_id, used_at,
            )
        return _grant(row)


__all__ = ["PostgresAccessRepository"]
