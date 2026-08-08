"""Synchronous, typed client for institution access and hardware leases."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ValidationError

from shared.contracts.access_control import (
    ActivateAccountRequest,
    ActivateAccountResponse,
    InventoryActivationRequest,
    HardwareLeaseRequest,
    HardwareLeaseResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    PlatformLoginRequest,
    PlatformLoginResponse,
    RefreshRequest,
    RefreshResponse,
    SignedLicenseV2,
)


class CloudAccessError(RuntimeError):
    """Safe public client error that never embeds response or credential data."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AccessAuthenticationFailed(CloudAccessError):
    pass


class AccessDenied(CloudAccessError):
    pass


class AccessConflict(CloudAccessError):
    pass


class AccessServiceUnavailable(CloudAccessError):
    pass


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class CloudAccessClient:
    """Typed API boundary suitable for the existing synchronous Qt composition."""

    def __init__(
        self,
        base_url: str,
        *,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            verify=verify,
            transport=transport,
            # The packaged device client connects only to the explicitly
            # configured institution endpoint.  Ambient desktop proxy settings
            # must not silently route access tokens or hardware leases.
            trust_env=False,
            timeout=timeout
            or httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0),
        )
        self.last_server_time: datetime | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CloudAccessClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def activate(self, request: ActivateAccountRequest) -> ActivateAccountResponse:
        return self._model_request(
            "POST",
            "/v1/access/activate",
            ActivateAccountResponse,
            json=request.model_dump(mode="json"),
        )

    def activate_inventory(
        self, request: InventoryActivationRequest
    ) -> ActivateAccountResponse:
        return self._model_request(
            "POST",
            "/v1/access/inventory-activate",
            ActivateAccountResponse,
            json=request.model_dump(mode="json"),
        )

    def login(self, request: LoginRequest) -> LoginResponse:
        return self._model_request(
            "POST",
            "/v1/access/login",
            LoginResponse,
            json=request.model_dump(mode="json"),
        )

    def platform_login(self, request: PlatformLoginRequest) -> PlatformLoginResponse:
        """Authenticate a short-lived Platform IAM engineering session."""

        return self._model_request(
            "POST",
            "/v1/platform/login",
            PlatformLoginResponse,
            json=request.model_dump(mode="json"),
        )

    def refresh(self, request: RefreshRequest) -> RefreshResponse:
        return self._model_request(
            "POST",
            "/v1/access/refresh",
            RefreshResponse,
            json=request.model_dump(mode="json"),
        )

    def logout(self, request: LogoutRequest) -> None:
        self._request(
            "POST",
            "/v1/access/logout",
            json=request.model_dump(mode="json"),
        )

    def fetch_license(self, access_token: str) -> SignedLicenseV2:
        return self._model_request(
            "GET",
            "/v1/access/license",
            SignedLicenseV2,
            access_token=access_token,
        )

    def acquire_hardware_lease(
        self,
        access_token: str,
        request: HardwareLeaseRequest,
    ) -> HardwareLeaseResponse:
        return self._model_request(
            "POST",
            "/v1/access/hardware-lease",
            HardwareLeaseResponse,
            access_token=access_token,
            json=request.model_dump(mode="json"),
        )

    def renew_hardware_lease(
        self,
        access_token: str,
        lease_id: UUID,
    ) -> HardwareLeaseResponse:
        return self._model_request(
            "PUT",
            f"/v1/access/hardware-lease/{lease_id}",
            HardwareLeaseResponse,
            access_token=access_token,
        )

    def release_hardware_lease(self, access_token: str, lease_id: UUID) -> None:
        self._request(
            "DELETE",
            f"/v1/access/hardware-lease/{lease_id}",
            access_token=access_token,
        )

    def _model_request(
        self,
        method: str,
        path: str,
        model: type[ResponseModel],
        *,
        access_token: str | None = None,
        json: dict[str, Any] | None = None,
    ) -> ResponseModel:
        payload = self._request(
            method,
            path,
            access_token=access_token,
            json=json,
        )
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise AccessServiceUnavailable("服务返回了无法识别的数据") from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        access_token: str | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"X-Correlation-ID": str(uuid4())}
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            response = self._client.request(method, path, headers=headers, json=json)
        except httpx.HTTPError as exc:
            raise AccessServiceUnavailable("暂时无法连接机构服务") from exc
        if response.status_code >= 400:
            self._raise_safe_error(response.status_code)
        try:
            envelope = response.json()
            data = envelope["data"]
            raw_server_time = envelope.get("meta", {}).get("server_time")
            if raw_server_time:
                self.last_server_time = datetime.fromisoformat(
                    str(raw_server_time).replace("Z", "+00:00")
                )
            return data
        except (KeyError, TypeError, ValueError) as exc:
            raise AccessServiceUnavailable("服务返回了无法识别的数据") from exc

    @staticmethod
    def _raise_safe_error(status_code: int) -> None:
        if status_code == 401:
            raise AccessAuthenticationFailed("账号或凭据验证失败", status_code=status_code)
        if status_code == 403:
            raise AccessDenied("当前账号不允许执行此操作", status_code=status_code)
        if status_code == 409:
            raise AccessConflict("当前资源正在其他位置使用", status_code=status_code)
        if status_code >= 500:
            raise AccessServiceUnavailable("机构服务暂时不可用", status_code=status_code)
        raise CloudAccessError("机构服务拒绝了当前请求", status_code=status_code)


__all__ = [
    "AccessAuthenticationFailed",
    "AccessConflict",
    "AccessDenied",
    "AccessServiceUnavailable",
    "CloudAccessClient",
    "CloudAccessError",
]
