"""Repository boundary and deterministic in-memory seed access adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

from shared.contracts.access_control import AccountState, LicenseState


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
    ) -> ActivatedAccess: ...


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
                        status=LicenseState.SUSPENDED,
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
    ) -> ActivatedAccess:
        async with self._lock:
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


__all__ = [
    "AccessActivationRejected",
    "AccessGroupHistoryRecord",
    "AccessGroupSeed",
    "AccessRepository",
    "AccessRepositoryConflict",
    "AccessRepositoryError",
    "ActivatedAccess",
    "ActivationCodeRecord",
    "ClientInstallationRecord",
    "HardwareAssetRecord",
    "InMemoryAccessRepository",
    "LicenseEntitlementRecord",
    "TenantAccountRecord",
    "TenantRecord",
    "TenantSeed",
]
