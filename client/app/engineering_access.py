"""Short-lived Platform IAM authorization for local engineering maintenance."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from shared.contracts.access_control import (
    PlatformLoginRequest,
    PlatformLoginResponse,
    PlatformRole,
)


class EngineeringAuthorizationDenied(PermissionError):
    """The current Platform IAM response does not authorize engineering access."""


class PlatformEngineerLoginPort(Protocol):
    """Minimal Platform IAM client boundary for an engineering re-login."""

    def platform_login(self, request: PlatformLoginRequest) -> PlatformLoginResponse: ...


class PlatformEngineerAuthorizer:
    """Retain only a validated engineer-session expiry in process memory."""

    def __init__(
        self,
        client: PlatformEngineerLoginPort,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._now = now or (lambda: datetime.now(UTC))
        self._expires_at: datetime | None = None

    def login(self, login_name: str, password: str) -> None:
        """Authorize a new session only when Platform IAM grants ENGINEER."""

        self._expires_at = None
        response = self._client.platform_login(
            PlatformLoginRequest(login_name=login_name, password=password)
        )
        if (
            PlatformRole.ENGINEER not in response.roles
            or response.access_token_expires_at <= self._now()
        ):
            raise EngineeringAuthorizationDenied("engineering authorization denied")
        self._expires_at = response.access_token_expires_at

    def is_authorized(self) -> bool:
        """Return whether the memory-only authorization remains valid."""

        return self._expires_at is not None and self._expires_at > self._now()
