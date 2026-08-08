from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import httpx
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton

from client.app.engineering_maintenance import EngineeringMaintenanceService
from client.app.packaged_entry import (
    build_packaged_engineering_login,
    build_packaged_workbench_factory,
)
from client.app.pages import PageId
from client.cloud.access_client import CloudAccessClient
from shared.contracts.access_control import (
    PlatformLoginRequest,
    PlatformLoginResponse,
    PlatformRole,
)


def test_platform_login_posts_to_platform_endpoint() -> None:
    requests: list[httpx.Request] = []
    now = datetime.now(UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "platform_identity_id": str(uuid4()),
                    "roles": [PlatformRole.ENGINEER.value],
                    "access_token": "a" * 20,
                    "access_token_expires_at": (now + timedelta(minutes=15)).isoformat(),
                    "refresh_token": "r" * 20,
                }
            },
        )

    client = CloudAccessClient(
        "https://api.example", transport=httpx.MockTransport(handler)
    )

    client.platform_login(
        PlatformLoginRequest(login_name="engineer", password="valid-password-123")
    )

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/platform/login")
    ]
    assert json.loads(requests[0].content) == {
        "login_name": "engineer",
        "password": "valid-password-123",
    }


class _PlatformClient:
    def __init__(self, roles: tuple[PlatformRole, ...]) -> None:
        self.closed = False
        self._response = PlatformLoginResponse(
            platform_identity_id=uuid4(),
            roles=roles,
            access_token="a" * 20,
            access_token_expires_at=datetime.now(UTC) + timedelta(minutes=15),
            refresh_token="r" * 20,
        )

    def platform_login(self, _request: PlatformLoginRequest) -> PlatformLoginResponse:
        return self._response

    def close(self) -> None:
        self.closed = True


def test_packaged_engineering_login_rejects_role_and_composes_manual_service(
    tmp_path
) -> None:
    denied_client = _PlatformClient((PlatformRole.SUPPORT,))
    denied_login = build_packaged_engineering_login(
        data_root=tmp_path,
        client_factory=lambda: denied_client,
    )

    assert denied_login("engineer", "valid-password-123") is None
    assert denied_client.closed is True

    approved_client = _PlatformClient((PlatformRole.ENGINEER,))
    approved_login = build_packaged_engineering_login(
        data_root=tmp_path,
        client_factory=lambda: approved_client,
    )
    service = approved_login("engineer", "valid-password-123")

    assert isinstance(service, EngineeringMaintenanceService)
    assert approved_client.closed is True
    service.bind_current_device("FFP-001")
    assert service.read_distribution().device_id == "FFP-001"


def test_packaged_workbench_opens_engineer_login(qtbot, tmp_path) -> None:
    service = EngineeringMaintenanceService(
        mask_store_for_device=lambda _device_id: None,
        authorization_verifier=lambda: True,
    )
    window = build_packaged_workbench_factory(
        engineering_login=lambda name, password: service
        if (name, password) == ("engineer", "secret")
        else None
    )()
    qtbot.addWidget(window)
    window.show()
    window.show_page(PageId.SUPPORT)

    entry = window.findChild(QPushButton, "OPEN_ENGINEERING_MAINTENANCE")
    assert entry.isVisible()
    qtbot.mouseClick(entry, Qt.MouseButton.LeftButton)
    login = window.findChild(QDialog, "engineeringPlatformLoginDialog")
    assert login is not None
    qtbot.keyClicks(login.findChild(QLineEdit, "engineeringLoginName"), "engineer")
    qtbot.keyClicks(login.findChild(QLineEdit, "engineeringLoginPassword"), "secret")
    qtbot.mouseClick(
        login.findChild(QPushButton, "CONFIRM_ENGINEERING_LOGIN"),
        Qt.MouseButton.LeftButton,
    )

    assert window.findChild(QDialog, "engineeringMaintenanceDialog") is not None
