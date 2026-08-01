"""Repository boundary and deterministic in-memory seed access adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hmac
from typing import Protocol
from uuid import UUID

from shared.contracts.access_control import AccountState, LicenseState, PlatformRole


class AccessRepositoryError(RuntimeError):
    """Base error for repository decisions safe to translate at a service edge."""


class AccessActivationRejected(AccessRepositoryError):
    """Activation did not match one pre-provisioned account/License/hardware set."""


class AccessRepositoryConflict(AccessRepositoryError):
    """A uniqueness or concurrent state transition conflicted."""


@dataclass(frozen=True, slots=True)
class TenantSeed:
    tenant_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class AccessGroupSeed:
    account_id: UUID
    login_name_hmac: bytes
    account_display_name: str
    license_id: UUID
    hardware_id: UUID
    hardware_identity: str
    hardware_model: str
    activation_code_id: UUID
    activation_code_hash: bytes
    activation_expires_at: datetime
    license_valid_from: datetime
    license_valid_until: datetime
    enabled_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TenantRecord:
    tenant_id: UUID
    name: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TenantAccountRecord:
    tenant_id: UUID
    account_id: UUID
    login_name_hmac: bytes
    display_name: str
    password_hash: str | None
    status: AccountState
    token_version: int
    activated_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class HardwareAssetRecord:
    tenant_id: UUID
    hardware_id: UUID
    stable_identity: str
    model: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LicenseEntitlementRecord:
    tenant_id: UUID
    license_id: UUID
    status: LicenseState
    enabled_features: tuple[str, ...]
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    version: int
    key_id: str | None = None
    document_json: str | None = None
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class ActivationCodeRecord:
    tenant_id: UUID
    activation_code_id: UUID
    account_id: UUID
    license_id: UUID
    hardware_id: UUID
    activation_code_hash: bytes
    expires_at: datetime
    consumed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClientInstallationRecord:
    tenant_id: UUID
    client_installation_id: UUID
    account_id: UUID
    first_seen_at: datetime
    last_seen_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class AccessGroupHistoryRecord:
    tenant_id: UUID
    account_id: UUID
    license_id: UUID
    hardware_id: UUID
    assigned_at: datetime
    closed_at: datetime | None
    close_reason_code: str | None


@dataclass(frozen=True, slots=True)
class ActivatedAccess:
    tenant: TenantRecord
    account: TenantAccountRecord
    license: LicenseEntitlementRecord
    hardware: HardwareAssetRecord
    activation_code: ActivationCodeRecord
    installation: ClientInstallationRecord


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    event_id: UUID
    actor_id: UUID
    action: str
    tenant_id: UUID | None
    resource_id: UUID | None
    occurred_at: datetime
    details: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RefreshSessionRecord:
    refresh_session_id: UUID
    tenant_id: UUID
    account_id: UUID
    client_installation_id: UUID
    refresh_token_hash: bytes
    issued_at: datetime
    last_used_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by_session_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AuthenticationAttemptRecord:
    authentication_attempt_id: UUID
    login_name_hmac: bytes
    source_fingerprint: bytes
    attempt_kind: str
    succeeded: bool
    attempted_at: datetime


@dataclass(frozen=True, slots=True)
class HardwareLeaseRecord:
    lease_id: UUID
    tenant_id: UUID
    license_id: UUID
    account_id: UUID
    hardware_id: UUID
    client_installation_id: UUID
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime
    released_at: datetime | None = None
    release_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlatformIdentityRecord:
    platform_identity_id: UUID
    login_name_hmac: bytes
    display_name: str
    password_hash: str
    status: str
    token_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformRoleBindingRecord:
    binding_id: UUID
    platform_identity_id: UUID
    role: PlatformRole
    valid_from: datetime
    valid_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class SensitiveAccessGrantRecord:
    grant_id: UUID
    tenant_id: UUID
    platform_identity_id: UUID
    purpose_code: str
    ticket_reference: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class AccessRepository(Protocol):
    async def provision_tenant(
        self,
        tenant: TenantSeed,
        group: AccessGroupSeed,
        *,
        created_at: datetime,
    ) -> None: ...

    async def add_access_group(
        self,
        tenant_id: UUID,
        group: AccessGroupSeed,
        *,
        created_at: datetime,
    ) -> None: ...

    async def activate_account_atomically(
        self,
        *,
        login_name_hmac: bytes,
        activation_code_hash: bytes,
        hardware_identity: str,
        password_hash: str,
        installation_id: UUID,
        activated_at: datetime,
        license_key_id: str | None = None,
        license_document_json: str | None = None,
        license_signature: str | None = None,
    ) -> ActivatedAccess: ...

    async def close_access_group(
        self, *, tenant_id: UUID, license_id: UUID, closed_at: datetime, reason_code: str
    ) -> UUID: ...

    async def active_access_groups(
        self, tenant_id: UUID
    ) -> tuple[AccessGroupHistoryRecord, ...]: ...

    async def access_group_history(
        self, tenant_id: UUID
    ) -> tuple[AccessGroupHistoryRecord, ...]: ...

    async def active_group_for_account(self, account_id: UUID) -> AccessGroupHistoryRecord: ...

    async def register_or_touch_installation(
        self, *, tenant_id: UUID, account_id: UUID, installation_id: UUID, seen_at: datetime
    ) -> ClientInstallationRecord: ...

    async def create_refresh_session(self, session: RefreshSessionRecord) -> RefreshSessionRecord: ...

    async def refresh_session_by_hash(self, token_hash: bytes) -> RefreshSessionRecord | None: ...

    async def rotate_refresh_session(
        self, *, current_token_hash: bytes, expected_installation_id: UUID,
        replacement: RefreshSessionRecord, rotated_at: datetime
    ) -> RefreshSessionRecord: ...

    async def revoke_refresh_session(self, token_hash: bytes, *, revoked_at: datetime) -> None: ...

    async def record_authentication_attempt(self, attempt: AuthenticationAttemptRecord) -> None: ...

    async def failed_authentication_attempts(
        self, *, login_name_hmac: bytes, source_fingerprint: bytes, since: datetime
    ) -> int: ...

    async def acquire_hardware_lease(
        self, lease: HardwareLeaseRecord, *, acquired_at: datetime
    ) -> HardwareLeaseRecord: ...

    async def renew_hardware_lease(
        self, *, lease_id: UUID, tenant_id: UUID, account_id: UUID,
        license_id: UUID, installation_id: UUID, renewed_at: datetime,
        expires_at: datetime
    ) -> HardwareLeaseRecord: ...

    async def release_hardware_lease(
        self, *, lease_id: UUID, tenant_id: UUID, account_id: UUID,
        license_id: UUID, installation_id: UUID, released_at: datetime, reason: str
    ) -> None: ...

    async def account_by_login_hmac(self, login_name_hmac: bytes) -> TenantAccountRecord | None: ...
    async def activation_code(self, activation_code_id: UUID) -> ActivationCodeRecord | None: ...
    async def license(self, license_id: UUID) -> LicenseEntitlementRecord: ...
    async def tenant(self, tenant_id: UUID) -> TenantRecord: ...
    async def account(self, account_id: UUID) -> TenantAccountRecord: ...
    async def hardware(self, hardware_id: UUID) -> HardwareAssetRecord: ...
    async def hardware_by_identity(self, stable_identity: str) -> HardwareAssetRecord | None: ...
    async def access_group_for_license(self, license_id: UUID) -> AccessGroupHistoryRecord: ...

    async def replace_license(
        self, *, license_id: UUID, expected_version: int, status: LicenseState,
        issued_at: datetime, valid_until: datetime, key_id: str,
        document_json: str, signature: str
    ) -> LicenseEntitlementRecord: ...

    async def append_audit(self, event: AuditEventRecord) -> None: ...
    async def audit_events(
        self, *, tenant_id: UUID | None = None
    ) -> tuple[AuditEventRecord, ...]: ...
    async def activation_storage_contains(self, raw_code: str) -> bool: ...
    async def platform_identity_count(self) -> int: ...

    async def create_platform_identity(
        self, identity: PlatformIdentityRecord,
        roles: tuple[PlatformRoleBindingRecord, ...]
    ) -> PlatformIdentityRecord: ...

    async def platform_identity_by_login_hmac(
        self, login_name_hmac: bytes
    ) -> PlatformIdentityRecord | None: ...

    async def platform_roles(
        self, platform_identity_id: UUID, *, at: datetime
    ) -> tuple[PlatformRole, ...]: ...

    async def list_tenants(self) -> tuple[TenantRecord, ...]: ...
    async def tenant_access_counts(self, tenant_id: UUID) -> tuple[int, int]: ...

    async def create_sensitive_grant(
        self, grant: SensitiveAccessGrantRecord
    ) -> SensitiveAccessGrantRecord: ...

    async def use_sensitive_grant(
        self, *, grant_id: UUID, tenant_id: UUID,
        platform_identity_id: UUID, used_at: datetime
    ) -> SensitiveAccessGrantRecord: ...


class InMemoryAccessRepository:
    """Immutable-returning repository with explicit atomic transition methods."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tenants: dict[UUID, TenantRecord] = {}
        self._accounts: dict[UUID, TenantAccountRecord] = {}
        self._account_by_login: dict[bytes, UUID] = {}
        self._hardware: dict[UUID, HardwareAssetRecord] = {}
        self._hardware_by_identity: dict[str, UUID] = {}
        self._licenses: dict[UUID, LicenseEntitlementRecord] = {}
        self._activation_codes: dict[UUID, ActivationCodeRecord] = {}
        self._activation_by_hash: dict[bytes, UUID] = {}
        self._installations: dict[UUID, ClientInstallationRecord] = {}
        self._group_history: list[AccessGroupHistoryRecord] = []
        self._audit_events: list[AuditEventRecord] = []
        self._refresh_sessions: dict[UUID, RefreshSessionRecord] = {}
        self._refresh_by_hash: dict[bytes, UUID] = {}
        self._authentication_attempts: list[AuthenticationAttemptRecord] = []
        self._hardware_leases: dict[UUID, HardwareLeaseRecord] = {}
        self._open_lease_by_hardware: dict[UUID, UUID] = {}
        self._platform_identities: dict[UUID, PlatformIdentityRecord] = {}
        self._platform_identity_by_login: dict[bytes, UUID] = {}
        self._platform_role_bindings: list[PlatformRoleBindingRecord] = []
        self._sensitive_grants: dict[UUID, SensitiveAccessGrantRecord] = {}

    async def provision_tenant(
        self,
        tenant: TenantSeed,
        group: AccessGroupSeed,
        *,
        created_at: datetime,
    ) -> None:
        async with self._lock:
            if tenant.tenant_id in self._tenants:
                raise ValueError("tenant already exists")
            if not tenant.name.strip():
                raise ValueError("tenant name is required")
            self._ensure_group_available(group)
            record = TenantRecord(tenant.tenant_id, tenant.name.strip(), "ACTIVE", created_at)
            self._tenants[tenant.tenant_id] = record
            try:
                self._insert_group(tenant.tenant_id, group, created_at)
            except Exception:
                self._tenants.pop(tenant.tenant_id, None)
                raise

    async def add_access_group(
        self,
        tenant_id: UUID,
        group: AccessGroupSeed,
        *,
        created_at: datetime,
    ) -> None:
        async with self._lock:
            if tenant_id not in self._tenants:
                raise ValueError("tenant does not exist")
            self._ensure_group_available(group)
            self._insert_group(tenant_id, group, created_at)

    def _ensure_group_available(self, group: AccessGroupSeed) -> None:
        if len(group.login_name_hmac) != 32:
            raise ValueError("account lookup hash must contain 32 bytes")
        if group.login_name_hmac in self._account_by_login or group.account_id in self._accounts:
            raise ValueError("account already exists")
        if (
            group.hardware_identity in self._hardware_by_identity
            or group.hardware_id in self._hardware
        ):
            raise ValueError("hardware already exists")
        if group.license_id in self._licenses:
            raise ValueError("license already exists")
        if (
            group.activation_code_hash in self._activation_by_hash
            or group.activation_code_id in self._activation_codes
        ):
            raise ValueError("activation code already exists")
        if group.license_valid_until <= group.license_valid_from:
            raise ValueError("license validity window is invalid")
        if not group.enabled_features or len(set(group.enabled_features)) != len(
            group.enabled_features
        ):
            raise ValueError("enabled features must be non-empty and unique")

    def _insert_group(
        self,
        tenant_id: UUID,
        group: AccessGroupSeed,
        created_at: datetime,
    ) -> None:
        account = TenantAccountRecord(
            tenant_id=tenant_id,
            account_id=group.account_id,
            login_name_hmac=group.login_name_hmac,
            display_name=group.account_display_name,
            password_hash=None,
            status=AccountState.PENDING_ACTIVATION,
            token_version=1,
            activated_at=None,
            created_at=created_at,
        )
        hardware = HardwareAssetRecord(
            tenant_id=tenant_id,
            hardware_id=group.hardware_id,
            stable_identity=group.hardware_identity,
            model=group.hardware_model,
            status="ACTIVE",
            created_at=created_at,
        )
        license_record = LicenseEntitlementRecord(
            tenant_id=tenant_id,
            license_id=group.license_id,
            status=LicenseState.PENDING_ACTIVATION,
            enabled_features=tuple(sorted(group.enabled_features)),
            issued_at=created_at,
            valid_from=group.license_valid_from,
            valid_until=group.license_valid_until,
            version=1,
        )
        activation = ActivationCodeRecord(
            tenant_id=tenant_id,
            activation_code_id=group.activation_code_id,
            account_id=group.account_id,
            license_id=group.license_id,
            hardware_id=group.hardware_id,
            activation_code_hash=group.activation_code_hash,
            expires_at=group.activation_expires_at,
            consumed_at=None,
            created_at=created_at,
        )
        history = AccessGroupHistoryRecord(
            tenant_id=tenant_id,
            account_id=group.account_id,
            license_id=group.license_id,
            hardware_id=group.hardware_id,
            assigned_at=created_at,
            closed_at=None,
            close_reason_code=None,
        )
        self._accounts[account.account_id] = account
        self._account_by_login[account.login_name_hmac] = account.account_id
        self._hardware[hardware.hardware_id] = hardware
        self._hardware_by_identity[hardware.stable_identity] = hardware.hardware_id
        self._licenses[license_record.license_id] = license_record
        self._activation_codes[activation.activation_code_id] = activation
        self._activation_by_hash[activation.activation_code_hash] = activation.activation_code_id
        self._group_history.append(history)

    async def close_access_group(
        self,
        *,
        tenant_id: UUID,
        license_id: UUID,
        closed_at: datetime,
        reason_code: str,
    ) -> UUID:
        async with self._lock:
            if not reason_code.strip():
                raise ValueError("close reason is required")
            for index, row in enumerate(self._group_history):
                if (
                    row.tenant_id == tenant_id
                    and row.license_id == license_id
                    and row.closed_at is None
                ):
                    if closed_at <= row.assigned_at:
                        raise ValueError("closed_at must follow assigned_at")
                    self._group_history[index] = replace(
                        row,
                        closed_at=closed_at,
                        close_reason_code=reason_code.strip(),
                    )
                    license_record = self._licenses[license_id]
                    self._licenses[license_id] = replace(
                        license_record,
                        status=LicenseState.REVOKED,
                        version=license_record.version + 1,
                    )
                    return license_id
            raise AccessRepositoryConflict("active access group does not exist")

    async def active_access_groups(
        self, tenant_id: UUID
    ) -> tuple[AccessGroupHistoryRecord, ...]:
        async with self._lock:
            return tuple(
                row
                for row in self._group_history
                if row.tenant_id == tenant_id and row.closed_at is None
            )

    async def access_group_history(
        self, tenant_id: UUID
    ) -> tuple[AccessGroupHistoryRecord, ...]:
        async with self._lock:
            return tuple(row for row in self._group_history if row.tenant_id == tenant_id)

    async def activate_account_atomically(
        self,
        *,
        login_name_hmac: bytes,
        activation_code_hash: bytes,
        hardware_identity: str,
        password_hash: str,
        installation_id: UUID,
        activated_at: datetime,
        license_key_id: str | None = None,
        license_document_json: str | None = None,
        license_signature: str | None = None,
    ) -> ActivatedAccess:
        async with self._lock:
            signed_fields = (license_key_id, license_document_json, license_signature)
            if any(value is not None for value in signed_fields) and not all(
                value is not None for value in signed_fields
            ):
                raise ValueError("signed License fields must be stored together")
            account_id = self._account_by_login.get(login_name_hmac)
            activation_code_id = self._activation_by_hash.get(activation_code_hash)
            if account_id is None or activation_code_id is None:
                raise AccessActivationRejected("activation credentials do not match")
            account = self._accounts[account_id]
            activation = self._activation_codes[activation_code_id]
            license_record = self._licenses[activation.license_id]
            hardware = self._hardware[activation.hardware_id]
            if (
                activation.account_id != account.account_id
                or activation.tenant_id != account.tenant_id
                or hardware.tenant_id != account.tenant_id
                or license_record.tenant_id != account.tenant_id
                or hardware.stable_identity != hardware_identity
                or activation.consumed_at is not None
                or activation.expires_at <= activated_at
                or account.status is not AccountState.PENDING_ACTIVATION
                or license_record.status is not LicenseState.PENDING_ACTIVATION
                or not password_hash
                or installation_id in self._installations
            ):
                raise AccessActivationRejected("activation credentials do not match")

            activated_account = replace(
                account,
                password_hash=password_hash,
                status=AccountState.ACTIVE,
                activated_at=activated_at,
            )
            activated_license = replace(
                license_record,
                status=LicenseState.ACTIVE,
                issued_at=activated_at,
                key_id=license_key_id,
                document_json=license_document_json,
                signature=license_signature,
            )
            consumed_code = replace(activation, consumed_at=activated_at)
            installation = ClientInstallationRecord(
                tenant_id=account.tenant_id,
                client_installation_id=installation_id,
                account_id=account.account_id,
                first_seen_at=activated_at,
                last_seen_at=activated_at,
                status="ACTIVE",
            )
            self._accounts[account.account_id] = activated_account
            self._licenses[license_record.license_id] = activated_license
            self._activation_codes[activation.activation_code_id] = consumed_code
            self._installations[installation_id] = installation
            return ActivatedAccess(
                tenant=self._tenants[account.tenant_id],
                account=activated_account,
                license=activated_license,
                hardware=hardware,
                activation_code=consumed_code,
                installation=installation,
            )

    async def active_group_for_account(
        self, account_id: UUID
    ) -> AccessGroupHistoryRecord:
        async with self._lock:
            for row in reversed(self._group_history):
                if row.account_id == account_id and row.closed_at is None:
                    return row
            raise AccessRepositoryError("active account access group does not exist")

    async def register_or_touch_installation(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        installation_id: UUID,
        seen_at: datetime,
    ) -> ClientInstallationRecord:
        async with self._lock:
            existing = self._installations.get(installation_id)
            if existing is not None:
                if existing.tenant_id != tenant_id or existing.account_id != account_id:
                    raise AccessRepositoryConflict("installation belongs to another account")
                if existing.status != "ACTIVE":
                    raise AccessRepositoryConflict("installation is revoked")
                updated = replace(existing, last_seen_at=max(existing.last_seen_at, seen_at))
                self._installations[installation_id] = updated
                return updated
            installation = ClientInstallationRecord(
                tenant_id=tenant_id,
                client_installation_id=installation_id,
                account_id=account_id,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                status="ACTIVE",
            )
            self._installations[installation_id] = installation
            return installation

    async def create_refresh_session(
        self, session: RefreshSessionRecord
    ) -> RefreshSessionRecord:
        async with self._lock:
            if (
                session.refresh_session_id in self._refresh_sessions
                or session.refresh_token_hash in self._refresh_by_hash
            ):
                raise AccessRepositoryConflict("refresh session already exists")
            installation = self._installations.get(session.client_installation_id)
            if (
                installation is None
                or installation.tenant_id != session.tenant_id
                or installation.account_id != session.account_id
            ):
                raise AccessRepositoryConflict("refresh installation is invalid")
            self._refresh_sessions[session.refresh_session_id] = session
            self._refresh_by_hash[session.refresh_token_hash] = session.refresh_session_id
            return session

    async def refresh_session_by_hash(
        self, token_hash: bytes
    ) -> RefreshSessionRecord | None:
        async with self._lock:
            session_id = self._refresh_by_hash.get(token_hash)
            return None if session_id is None else self._refresh_sessions[session_id]

    async def rotate_refresh_session(
        self,
        *,
        current_token_hash: bytes,
        expected_installation_id: UUID,
        replacement: RefreshSessionRecord,
        rotated_at: datetime,
    ) -> RefreshSessionRecord:
        async with self._lock:
            current_id = self._refresh_by_hash.get(current_token_hash)
            current = None if current_id is None else self._refresh_sessions[current_id]
            if (
                current is None
                or current.client_installation_id != expected_installation_id
                or current.rotated_at is not None
                or current.revoked_at is not None
                or current.idle_expires_at <= rotated_at
                or current.absolute_expires_at <= rotated_at
                or replacement.tenant_id != current.tenant_id
                or replacement.account_id != current.account_id
                or replacement.client_installation_id != current.client_installation_id
                or replacement.absolute_expires_at != current.absolute_expires_at
                or replacement.refresh_token_hash in self._refresh_by_hash
            ):
                raise AccessActivationRejected("refresh credential is invalid")
            retired = replace(
                current,
                rotated_at=rotated_at,
                last_used_at=rotated_at,
                replaced_by_session_id=replacement.refresh_session_id,
            )
            self._refresh_sessions[current.refresh_session_id] = retired
            self._refresh_sessions[replacement.refresh_session_id] = replacement
            self._refresh_by_hash[replacement.refresh_token_hash] = replacement.refresh_session_id
            return replacement

    async def revoke_refresh_session(
        self, token_hash: bytes, *, revoked_at: datetime
    ) -> None:
        async with self._lock:
            session_id = self._refresh_by_hash.get(token_hash)
            if session_id is None:
                return
            session = self._refresh_sessions[session_id]
            if session.revoked_at is None:
                self._refresh_sessions[session_id] = replace(
                    session,
                    revoked_at=revoked_at,
                )

    async def record_authentication_attempt(
        self, attempt: AuthenticationAttemptRecord
    ) -> None:
        async with self._lock:
            self._authentication_attempts.append(attempt)

    async def failed_authentication_attempts(
        self,
        *,
        login_name_hmac: bytes,
        source_fingerprint: bytes,
        since: datetime,
    ) -> int:
        async with self._lock:
            return sum(
                not attempt.succeeded
                and attempt.login_name_hmac == login_name_hmac
                and attempt.source_fingerprint == source_fingerprint
                and attempt.attempted_at >= since
                for attempt in self._authentication_attempts
            )

    async def acquire_hardware_lease(
        self,
        lease: HardwareLeaseRecord,
        *,
        acquired_at: datetime,
    ) -> HardwareLeaseRecord:
        async with self._lock:
            open_lease_id = self._open_lease_by_hardware.get(lease.hardware_id)
            if open_lease_id is not None:
                current = self._hardware_leases[open_lease_id]
                if current.expires_at > acquired_at and current.released_at is None:
                    if (
                        current.tenant_id == lease.tenant_id
                        and current.license_id == lease.license_id
                        and current.account_id == lease.account_id
                        and current.client_installation_id == lease.client_installation_id
                    ):
                        return current
                    raise AccessRepositoryConflict("hardware already has an active lease")
                self._hardware_leases[open_lease_id] = replace(
                    current,
                    released_at=max(current.expires_at, acquired_at),
                    release_reason="TTL_EXPIRED",
                )
                self._open_lease_by_hardware.pop(lease.hardware_id, None)
            group = next(
                (
                    row
                    for row in reversed(self._group_history)
                    if row.tenant_id == lease.tenant_id
                    and row.license_id == lease.license_id
                    and row.account_id == lease.account_id
                    and row.hardware_id == lease.hardware_id
                    and row.closed_at is None
                ),
                None,
            )
            installation = self._installations.get(lease.client_installation_id)
            if (
                group is None
                or installation is None
                or installation.tenant_id != lease.tenant_id
                or installation.account_id != lease.account_id
                or lease.lease_id in self._hardware_leases
                or lease.expires_at <= acquired_at
            ):
                raise AccessRepositoryConflict("hardware lease binding is invalid")
            self._hardware_leases[lease.lease_id] = lease
            self._open_lease_by_hardware[lease.hardware_id] = lease.lease_id
            return lease

    async def renew_hardware_lease(
        self,
        *,
        lease_id: UUID,
        tenant_id: UUID,
        account_id: UUID,
        license_id: UUID,
        installation_id: UUID,
        renewed_at: datetime,
        expires_at: datetime,
    ) -> HardwareLeaseRecord:
        async with self._lock:
            current = self._hardware_leases.get(lease_id)
            if (
                current is None
                or current.tenant_id != tenant_id
                or current.account_id != account_id
                or current.license_id != license_id
                or current.client_installation_id != installation_id
                or current.released_at is not None
                or current.expires_at <= renewed_at
                or expires_at <= renewed_at
            ):
                raise AccessRepositoryConflict("hardware lease cannot be renewed")
            updated = replace(current, renewed_at=renewed_at, expires_at=expires_at)
            self._hardware_leases[lease_id] = updated
            return updated

    async def release_hardware_lease(
        self,
        *,
        lease_id: UUID,
        tenant_id: UUID,
        account_id: UUID,
        license_id: UUID,
        installation_id: UUID,
        released_at: datetime,
        reason: str,
    ) -> None:
        async with self._lock:
            current = self._hardware_leases.get(lease_id)
            if (
                current is None
                or current.tenant_id != tenant_id
                or current.account_id != account_id
                or current.license_id != license_id
                or current.client_installation_id != installation_id
            ):
                raise AccessRepositoryConflict("hardware lease cannot be released")
            if current.released_at is None:
                self._hardware_leases[lease_id] = replace(
                    current,
                    released_at=max(released_at, current.acquired_at),
                    release_reason=reason,
                )
                self._open_lease_by_hardware.pop(current.hardware_id, None)

    async def account_by_login_hmac(
        self, login_name_hmac: bytes
    ) -> TenantAccountRecord | None:
        async with self._lock:
            account_id = self._account_by_login.get(login_name_hmac)
            return None if account_id is None else self._accounts[account_id]

    async def activation_code(
        self, activation_code_id: UUID
    ) -> ActivationCodeRecord | None:
        async with self._lock:
            return self._activation_codes.get(activation_code_id)

    async def license(self, license_id: UUID) -> LicenseEntitlementRecord:
        async with self._lock:
            try:
                return self._licenses[license_id]
            except KeyError as exc:
                raise AccessRepositoryError("license does not exist") from exc

    async def tenant(self, tenant_id: UUID) -> TenantRecord:
        async with self._lock:
            try:
                return self._tenants[tenant_id]
            except KeyError as exc:
                raise AccessRepositoryError("tenant does not exist") from exc

    async def account(self, account_id: UUID) -> TenantAccountRecord:
        async with self._lock:
            try:
                return self._accounts[account_id]
            except KeyError as exc:
                raise AccessRepositoryError("account does not exist") from exc

    async def hardware(self, hardware_id: UUID) -> HardwareAssetRecord:
        async with self._lock:
            try:
                return self._hardware[hardware_id]
            except KeyError as exc:
                raise AccessRepositoryError("hardware does not exist") from exc

    async def hardware_by_identity(
        self, stable_identity: str
    ) -> HardwareAssetRecord | None:
        async with self._lock:
            hardware_id = self._hardware_by_identity.get(stable_identity)
            return None if hardware_id is None else self._hardware[hardware_id]

    async def access_group_for_license(
        self, license_id: UUID
    ) -> AccessGroupHistoryRecord:
        async with self._lock:
            for row in reversed(self._group_history):
                if row.license_id == license_id and row.closed_at is None:
                    return row
            raise AccessRepositoryError("active access group does not exist")

    async def replace_license(
        self,
        *,
        license_id: UUID,
        expected_version: int,
        status: LicenseState,
        issued_at: datetime,
        valid_until: datetime,
        key_id: str,
        document_json: str,
        signature: str,
    ) -> LicenseEntitlementRecord:
        async with self._lock:
            try:
                current = self._licenses[license_id]
            except KeyError as exc:
                raise AccessRepositoryError("license does not exist") from exc
            if current.version != expected_version:
                raise AccessRepositoryConflict("license version changed concurrently")
            if valid_until <= current.valid_from:
                raise ValueError("license validity window is invalid")
            updated = replace(
                current,
                status=status,
                issued_at=issued_at,
                valid_until=valid_until,
                version=current.version + 1,
                key_id=key_id,
                document_json=document_json,
                signature=signature,
            )
            self._licenses[license_id] = updated
            return updated

    async def append_audit(self, event: AuditEventRecord) -> None:
        async with self._lock:
            self._audit_events.append(event)

    async def audit_events(
        self,
        *,
        tenant_id: UUID | None = None,
    ) -> tuple[AuditEventRecord, ...]:
        async with self._lock:
            return tuple(
                event
                for event in self._audit_events
                if tenant_id is None or event.tenant_id == tenant_id
            )

    async def activation_storage_contains(self, raw_code: str) -> bool:
        raw = raw_code.encode("utf-8")
        async with self._lock:
            return any(
                hmac.compare_digest(raw, stored_hash)
                or raw in stored_hash
                for stored_hash in self._activation_by_hash
            )

    async def platform_identity_count(self) -> int:
        async with self._lock:
            return len(self._platform_identities)

    async def create_platform_identity(
        self,
        identity: PlatformIdentityRecord,
        roles: tuple[PlatformRoleBindingRecord, ...],
    ) -> PlatformIdentityRecord:
        async with self._lock:
            if (
                identity.platform_identity_id in self._platform_identities
                or identity.login_name_hmac in self._platform_identity_by_login
            ):
                raise AccessRepositoryConflict("platform identity already exists")
            if (
                not roles
                or any(
                    binding.platform_identity_id != identity.platform_identity_id
                    for binding in roles
                )
                or len({binding.role for binding in roles}) != len(roles)
            ):
                raise ValueError("platform roles must be non-empty and unique")
            self._platform_identities[identity.platform_identity_id] = identity
            self._platform_identity_by_login[identity.login_name_hmac] = (
                identity.platform_identity_id
            )
            self._platform_role_bindings.extend(roles)
            return identity

    async def platform_identity_by_login_hmac(
        self, login_name_hmac: bytes
    ) -> PlatformIdentityRecord | None:
        async with self._lock:
            identity_id = self._platform_identity_by_login.get(login_name_hmac)
            return (
                None if identity_id is None else self._platform_identities[identity_id]
            )

    async def platform_roles(
        self,
        platform_identity_id: UUID,
        *,
        at: datetime,
    ) -> tuple[PlatformRole, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    (
                        binding.role
                        for binding in self._platform_role_bindings
                        if binding.platform_identity_id == platform_identity_id
                        and binding.valid_from <= at
                        and (binding.valid_to is None or at < binding.valid_to)
                    ),
                    key=lambda role: role.value,
                )
            )

    async def list_tenants(self) -> tuple[TenantRecord, ...]:
        async with self._lock:
            return tuple(sorted(self._tenants.values(), key=lambda row: str(row.tenant_id)))

    async def tenant_access_counts(self, tenant_id: UUID) -> tuple[int, int]:
        async with self._lock:
            active_account_ids = {
                row.account_id
                for row in self._group_history
                if row.tenant_id == tenant_id and row.closed_at is None
            }
            active_license_ids = {
                row.license_id
                for row in self._group_history
                if row.tenant_id == tenant_id and row.closed_at is None
            }
            return len(active_account_ids), len(active_license_ids)

    async def create_sensitive_grant(
        self, grant: SensitiveAccessGrantRecord
    ) -> SensitiveAccessGrantRecord:
        async with self._lock:
            if grant.grant_id in self._sensitive_grants:
                raise AccessRepositoryConflict("sensitive grant already exists")
            if grant.tenant_id not in self._tenants:
                raise AccessRepositoryError("tenant does not exist")
            if grant.expires_at <= grant.issued_at or (
                grant.expires_at - grant.issued_at > timedelta(minutes=15)
            ):
                raise ValueError("sensitive grant duration is invalid")
            self._sensitive_grants[grant.grant_id] = grant
            return grant

    async def use_sensitive_grant(
        self,
        *,
        grant_id: UUID,
        tenant_id: UUID,
        platform_identity_id: UUID,
        used_at: datetime,
    ) -> SensitiveAccessGrantRecord:
        async with self._lock:
            grant = self._sensitive_grants.get(grant_id)
            if (
                grant is None
                or grant.tenant_id != tenant_id
                or grant.platform_identity_id != platform_identity_id
                or grant.revoked_at is not None
                or grant.expires_at <= used_at
            ):
                raise AccessRepositoryConflict("sensitive grant is invalid")
            used = replace(grant, last_used_at=used_at)
            self._sensitive_grants[grant_id] = used
            return used


__all__ = [
    "AccessActivationRejected",
    "AccessGroupHistoryRecord",
    "AccessGroupSeed",
    "AccessRepository",
    "AccessRepositoryConflict",
    "AccessRepositoryError",
    "ActivatedAccess",
    "ActivationCodeRecord",
    "AuthenticationAttemptRecord",
    "AuditEventRecord",
    "ClientInstallationRecord",
    "HardwareAssetRecord",
    "HardwareLeaseRecord",
    "InMemoryAccessRepository",
    "LicenseEntitlementRecord",
    "PlatformIdentityRecord",
    "PlatformRoleBindingRecord",
    "RefreshSessionRecord",
    "SensitiveAccessGrantRecord",
    "TenantAccountRecord",
    "TenantRecord",
    "TenantSeed",
]
