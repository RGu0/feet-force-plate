from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from shared.contracts.access_control import (
    PlatformLoginRequest,
    PlatformLoginResponse,
    PlatformRole,
)

from client.app.engineering_access import (
    EngineeringAuthorizationDenied,
    PlatformEngineerAuthorizer,
)


_NOW = datetime(2026, 8, 3, tzinfo=UTC)


class _PlatformClient:
    def __init__(self, response: PlatformLoginResponse) -> None:
        self.response = response
        self.requests: list[PlatformLoginRequest] = []

    def platform_login(self, request: PlatformLoginRequest) -> PlatformLoginResponse:
        self.requests.append(request)
        return self.response


def _response(
    *, roles: tuple[PlatformRole, ...], expires_at: datetime
) -> PlatformLoginResponse:
    return PlatformLoginResponse(
        platform_identity_id=uuid4(),
        roles=roles,
        access_token="a" * 20,
        access_token_expires_at=expires_at,
        refresh_token="r" * 20,
    )


def test_engineer_role_is_authorized_until_response_expiry() -> None:
    client = _PlatformClient(
        _response(
            roles=(PlatformRole.ENGINEER,),
            expires_at=_NOW + timedelta(minutes=15),
        )
    )
    authorizer = PlatformEngineerAuthorizer(client, now=lambda: _NOW)

    authorizer.login("field-engineer", "valid-password-123")

    assert authorizer.is_authorized() is True
    assert client.requests == [
        PlatformLoginRequest(
            login_name="field-engineer",
            password="valid-password-123",
        )
    ]


@pytest.mark.parametrize(
    ("roles", "expires_at"),
    [
        ((PlatformRole.SUPPORT,), _NOW + timedelta(minutes=15)),
        ((PlatformRole.ENGINEER,), _NOW),
    ],
)
def test_non_engineer_or_expired_response_is_rejected(
    roles: tuple[PlatformRole, ...], expires_at: datetime
) -> None:
    authorizer = PlatformEngineerAuthorizer(
        _PlatformClient(_response(roles=roles, expires_at=expires_at)),
        now=lambda: _NOW,
    )

    with pytest.raises(EngineeringAuthorizationDenied):
        authorizer.login("field-engineer", "valid-password-123")

    assert authorizer.is_authorized() is False


def test_authorization_expires_without_retaining_the_response() -> None:
    clock = [_NOW]
    authorizer = PlatformEngineerAuthorizer(
        _PlatformClient(
            _response(
                roles=(PlatformRole.ENGINEER,),
                expires_at=_NOW + timedelta(minutes=15),
            )
        ),
        now=lambda: clock[0],
    )
    authorizer.login("field-engineer", "valid-password-123")

    clock[0] = _NOW + timedelta(minutes=15)

    assert authorizer.is_authorized() is False
