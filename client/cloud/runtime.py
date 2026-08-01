"""Desktop institution access orchestration and environment configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import time
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

from platformdirs import user_data_path

from shared.contracts.access_control import (
    AccessSession,
    ActivateAccountRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
)

from .access_client import AccessAuthenticationFailed, CloudAccessClient
from .access_store import ClientAccessStore, KeyringCredentialStore
from .hardware_identity import (
    ActivationHardwareIdentityProvider,
    ActivationHardwareStatus,
)


class AccessClientPort(Protocol):
    last_server_time: datetime | None

    def activate(self, request: ActivateAccountRequest): ...

    def login(self, request: LoginRequest): ...

    def refresh(self, request: RefreshRequest): ...

    def logout(self, request: LogoutRequest) -> None: ...


class HardwareIdentityPort(Protocol):
    def discover(self): ...


class ClientAccessRuntimeError(RuntimeError):
    pass


class StableHardwareRequired(ClientAccessRuntimeError):
    pass


class LicenseHardwareMismatch(ClientAccessRuntimeError):
    pass


class StoredCredentialUnavailable(ClientAccessRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthenticatedInstitutionSession:
    tenant_id: str
    account_id: str
    license_id: str
    hardware_id: str
    client_installation_id: str
    access_token: str
    signed_license: str


@dataclass(frozen=True, slots=True)
class AccessRuntimeSettings:
    base_url: str
    verify: bool | str
    integration_mode: bool

    @property
    def environment_label(self) -> str | None:
        return "联调环境" if self.integration_mode else None

    @classmethod
    def from_environment(cls, environment: dict[str, str] | None = None):
        env = os.environ if environment is None else environment
        raw_url = env.get("FEETFORCEPLATE_API_BASE_URL", "").strip()
        if not raw_url:
            return None
        parsed = urlparse(raw_url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("FEETFORCEPLATE_API_BASE_URL must use HTTPS")
        integration_mode = env.get("FEETFORCEPLATE_INTEGRATION_MODE", "") == "1"
        if parsed.port == 7443 and not integration_mode:
            raise ValueError("port 7443 requires explicit integration mode")
        ca_bundle = env.get("FEETFORCEPLATE_CA_BUNDLE", "").strip()
        verify: bool | str = ca_bundle or True
        if integration_mode and parsed.port == 7443 and not ca_bundle:
            raise ValueError("integration endpoint requires an explicit CA bundle")
        if ca_bundle and not Path(ca_bundle).is_file():
            raise ValueError("configured CA bundle does not exist")
        return cls(raw_url.rstrip("/"), verify, integration_mode)


class ClientAccessRuntime:
    """Coordinates cloud access, local metadata, keyring, and hardware identity."""

    _REFRESH_EARLY = timedelta(minutes=1)

    def __init__(
        self,
        client: AccessClientPort,
        store: ClientAccessStore,
        hardware: HardwareIdentityPort,
        *,
        client_installation_id: UUID | None = None,
        now=None,
        monotonic_ns=None,
    ) -> None:
        self._client = client
        self._store = store
        self._hardware = hardware
        stored = store.load()
        self.client_installation_id = (
            client_installation_id
            or (stored.client_installation_id if stored is not None else uuid4())
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._session: AuthenticatedInstitutionSession | None = None
        self._access_expires_at: datetime | None = None

    def discover_hardware_identity(self) -> str | None:
        result = self._hardware.discover()
        if result.status is ActivationHardwareStatus.READY:
            return result.hardware_id
        return None

    def activate(
        self,
        account_name: str,
        activation_code: str,
        password: str,
        password_confirmation: str,
        hardware_id: str,
    ) -> AuthenticatedInstitutionSession:
        observed = self._require_hardware()
        if observed != hardware_id:
            raise LicenseHardwareMismatch("连接的硬件与激活页面不一致")
        response = self._client.activate(
            ActivateAccountRequest(
                account_name=account_name,
                activation_code=activation_code,
                password=password,
                password_confirmation=password_confirmation,
                hardware_id=hardware_id,
                client_installation_id=self.client_installation_id,
            )
        )
        return self._accept_session(response, expected_hardware_id=observed)

    def login(
        self,
        account_name: str,
        password: str,
    ) -> AuthenticatedInstitutionSession:
        observed = self._require_hardware()
        response = self._client.login(
            LoginRequest(
                account_name=account_name,
                password=password,
                client_installation_id=self.client_installation_id,
            )
        )
        return self._accept_session(response, expected_hardware_id=observed)

    def current_access_token(self) -> str:
        if self._session is None or self._access_expires_at is None:
            raise StoredCredentialUnavailable("当前没有已登录机构会话")
        if self._access_expires_at <= self._now() + self._REFRESH_EARLY:
            self.refresh()
        assert self._session is not None
        return self._session.access_token

    def refresh(self) -> AuthenticatedInstitutionSession:
        refresh_token = self._store.refresh_token()
        if refresh_token is None:
            raise StoredCredentialUnavailable("登录凭据已失效，请重新登录")
        try:
            response = self._client.refresh(
                RefreshRequest(
                    refresh_token=refresh_token,
                    client_installation_id=self.client_installation_id,
                )
            )
        except AccessAuthenticationFailed:
            self._store.clear_credentials()
            self._session = None
            self._access_expires_at = None
            raise
        return self._accept_session(response)

    def logout(self) -> None:
        refresh_token = self._store.refresh_token()
        if refresh_token is not None:
            try:
                self._client.logout(LogoutRequest(refresh_token=refresh_token))
            finally:
                self._store.clear_credentials()
        self._session = None
        self._access_expires_at = None

    def _require_hardware(self) -> str:
        result = self._hardware.discover()
        if (
            result.status is not ActivationHardwareStatus.READY
            or result.hardware_id is None
        ):
            raise StableHardwareRequired("未发现具有稳定身份的压力设备")
        return result.hardware_id

    def _accept_session(
        self,
        response: AccessSession,
        *,
        expected_hardware_id: str | None = None,
    ) -> AuthenticatedInstitutionSession:
        if (
            expected_hardware_id is not None
            and response.hardware_id != expected_hardware_id
        ):
            raise LicenseHardwareMismatch("当前硬件与机构 License 不匹配")
        server_time = self._client.last_server_time
        if server_time is None:
            raise ClientAccessRuntimeError("机构服务未返回可信时间")
        wall = self._now()
        self._store.save_session(
            response,
            trusted_server_utc=server_time,
            observed_wall_utc=wall,
            observed_monotonic_ns=self._monotonic_ns(),
        )
        session = AuthenticatedInstitutionSession(
            tenant_id=str(response.tenant_id),
            account_id=str(response.account_id),
            license_id=str(response.license_id),
            hardware_id=response.hardware_id,
            client_installation_id=str(response.client_installation_id),
            access_token=response.access_token,
            signed_license=response.signed_license.model_dump_json(),
        )
        self._session = session
        self._access_expires_at = response.access_token_expires_at
        return session


def build_client_access_runtime(
    settings: AccessRuntimeSettings,
    *,
    data_root: Path | None = None,
) -> ClientAccessRuntime:
    root = data_root or Path(
        user_data_path("FeetForcePlate", "TechFlex", ensure_exists=True)
    )
    store = ClientAccessStore(
        root / "database" / "access.sqlite3",
        KeyringCredentialStore(),
    )
    client = CloudAccessClient(settings.base_url, verify=settings.verify)
    return ClientAccessRuntime(
        client,
        store,
        ActivationHardwareIdentityProvider(),
    )


__all__ = [
    "AccessRuntimeSettings",
    "AuthenticatedInstitutionSession",
    "ClientAccessRuntime",
    "ClientAccessRuntimeError",
    "LicenseHardwareMismatch",
    "StableHardwareRequired",
    "StoredCredentialUnavailable",
    "build_client_access_runtime",
]
