from __future__ import annotations

from PySide6.QtWidgets import QWidget

from client.app import packaged_entry
from client.app.packaged_entry import build_mandatory_startup_gate
from client.cloud.runtime import AuthenticatedInstitutionSession
from client.startup_validation.workflow import DeviceNotFound


class _AbsentConnector:
    def connect(self):
        raise DeviceNotFound("absent")


class _AuditTrail:
    def __init__(self) -> None:
        self.runs = []

    def record(self, run):
        self.runs.append(run)
        return f"event-{len(self.runs)}"

    def recent_results(self, _device_ref: str, *, limit: int):
        return ()


def test_packaged_composition_uses_the_mandatory_gate_before_workbench(qtbot) -> None:
    created: list[QWidget] = []
    audit = _AuditTrail()
    gate = build_mandatory_startup_gate(
        terminal_id="terminal-test",
        app_version="0.1.0-test",
        connector=_AbsentConnector(),
        workbench_factory=lambda: created.append(QWidget()) or created[-1],
        quit_application=lambda: None,
        audit_trail=audit,
    )
    qtbot.addWidget(gate.window)

    gate.start()
    qtbot.waitUntil(
        lambda: gate.window.presentation.error_code == "E-DEV-101",
        timeout=2_000,
    )

    assert created == []
    assert gate.workbench is None
    assert gate.window.isVisible()
    assert [run.reason.value for run in audit.runs] == ["DEVICE_NOT_FOUND"]


def test_formal_entry_starts_with_the_p00_institution_access_screen(qtbot) -> None:
    """Catch a regression that sends unregistered users straight to device checks."""

    window = packaged_entry.build_institution_access_screen()
    qtbot.addWidget(window)
    window.show()

    assert window.objectName() == "institutionAccessWindow"
    assert window.findChild(QWidget, "institutionLoginPage").isVisible()


class _AccessRuntime:
    def __init__(self) -> None:
        self.logins = []

    def discover_hardware_identity(self):
        return "usb-serial-0123456789abcdef0123"

    def login(self, account, password):
        self.logins.append((account, password))
        return AuthenticatedInstitutionSession(
            tenant_id="tenant",
            account_id="account",
            license_id="license",
            hardware_asset_id="hardware-asset",
            hardware_id="usb-serial-0123456789abcdef0123",
            client_installation_id="installation",
            access_token="access-token-value-at-least-20",
            signed_license="signed-license",
        )

    def activate(self, *_args):
        raise AssertionError("not used")


def test_configured_access_screen_hands_authenticated_session_forward(qtbot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QPushButton

    runtime = _AccessRuntime()
    sessions = []
    window = packaged_entry.build_institution_access_screen(
        runtime=runtime,
        environment_label="联调环境",
        on_authenticated=sessions.append,
    )
    qtbot.addWidget(window)
    window.show()
    window.findChild(QLineEdit, "institutionAccountInput").setText("seed-clinic")
    window.findChild(QLineEdit, "institutionPasswordInput").setText(
        "correct-horse-battery-staple"
    )

    qtbot.mouseClick(
        window.findChild(QPushButton, "LOGIN_INSTITUTION"),
        Qt.MouseButton.LeftButton,
    )

    assert runtime.logins == [("seed-clinic", "correct-horse-battery-staple")]
    assert len(sessions) == 1
    assert window.findChild(QWidget, "accessEnvironmentLabel").isVisible()
