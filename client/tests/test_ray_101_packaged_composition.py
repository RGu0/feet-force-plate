from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from client.app.packaged_entry import (
    AuthenticatedInstitutionSession,
    InstitutionAuthenticationRejected,
    build_institution_application,
)


class _RecordingAuthenticator:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str]] = []

    def authenticate(self, account: str, password: str) -> AuthenticatedInstitutionSession:
        self.calls.append((account, password))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _RecordingStartupGate:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.start_count = 0

    def start(self) -> None:
        self.start_count += 1
        if self.failure is not None:
            raise self.failure


def _submit_login(window, qtbot, *, account: str, password: str) -> None:
    window.findChild(QLineEdit, "institutionAccountInput").setText(account)
    window.findChild(QLineEdit, "institutionPasswordInput").setText(password)
    qtbot.mouseClick(
        window.findChild(QPushButton, "LOGIN_INSTITUTION"),
        Qt.MouseButton.LeftButton,
    )


def _enter_local_test_activation(window, qtbot) -> QPushButton:
    qtbot.mouseClick(
        window.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION"),
        Qt.MouseButton.LeftButton,
    )
    window.findChild(QLineEdit, "licenseCodeInput").setText("FFP-2026-TEST-0001")
    window.findChild(QLineEdit, "registrationAccountInput").setText("local-test")
    window.findChild(QLineEdit, "registrationPasswordInput").setText("local-test-password")
    window.findChild(QLineEdit, "registrationPasswordConfirmationInput").setText(
        "local-test-password"
    )
    return window.findChild(QPushButton, "REGISTER_INSTITUTION")


def test_authenticated_institution_hands_off_to_the_mandatory_startup_gate(qtbot) -> None:
    """Catch production login bypassing or failing to start the hardware gate."""

    session = AuthenticatedInstitutionSession(
        tenant_id="tenant-kangjian",
        site_id="site-shanghai-01",
        terminal_id="terminal-001",
        account_id="operator-42",
    )
    authenticator = _RecordingAuthenticator(session)
    created: list[tuple[AuthenticatedInstitutionSession, _RecordingStartupGate]] = []

    def build_gate(authenticated_session: AuthenticatedInstitutionSession):
        gate = _RecordingStartupGate()
        created.append((authenticated_session, gate))
        return gate

    application = build_institution_application(
        authentication_port=authenticator,
        startup_gate_factory=build_gate,
    )
    qtbot.addWidget(application.access_window)
    application.show()

    _submit_login(
        application.access_window,
        qtbot,
        account="community-kangjian",
        password="production-secret",
    )

    assert authenticator.calls == [("community-kangjian", "production-secret")]
    assert len(created) == 1
    assert created[0][0] == session
    assert created[0][1].start_count == 1
    assert application.startup_gate is created[0][1]
    assert not application.access_window.isVisible()


def test_rejected_institution_login_keeps_p00_visible_and_never_builds_gate(qtbot) -> None:
    """Catch rejected credentials entering startup validation or leaking adapter details."""

    authenticator = _RecordingAuthenticator(
        InstitutionAuthenticationRejected("remote detail must not reach the operator")
    )
    created: list[AuthenticatedInstitutionSession] = []
    application = build_institution_application(
        authentication_port=authenticator,
        startup_gate_factory=lambda session: created.append(session),
    )
    qtbot.addWidget(application.access_window)
    application.show()

    _submit_login(
        application.access_window,
        qtbot,
        account="community-kangjian",
        password="wrong-password",
    )

    notice = application.access_window.findChild(QLabel, "accessFormNotice")
    assert application.access_window.isVisible()
    assert application.startup_gate is None
    assert created == []
    assert notice.isVisible()
    assert notice.text() == "机构账号或登录密码不正确，请检查后重试。"
    assert "remote detail" not in notice.text()


def test_formal_entry_disables_local_test_license_activation(qtbot) -> None:
    """Catch a local test License becoming usable in the formal entry point."""

    production_session = AuthenticatedInstitutionSession(
        tenant_id="tenant-production",
        site_id="site-production",
        terminal_id="terminal-production",
        account_id="operator-production",
    )
    authenticator = _RecordingAuthenticator(production_session)
    created: list[AuthenticatedInstitutionSession] = []
    application = build_institution_application(
        authentication_port=authenticator,
        startup_gate_factory=lambda session: created.append(session),
    )
    qtbot.addWidget(application.access_window)
    application.show()
    activate = _enter_local_test_activation(application.access_window, qtbot)

    assert not activate.isEnabled()
    assert authenticator.calls == []
    assert created == []
    assert application.startup_gate is None
    assert application.access_window.isVisible()


def test_startup_gate_failure_returns_to_p00_without_exposing_internal_error(qtbot) -> None:
    """Catch a failed gate handoff hiding P-00 or disclosing internal paths."""

    session = AuthenticatedInstitutionSession(
        tenant_id="tenant-kangjian",
        site_id="site-shanghai-01",
        terminal_id="terminal-001",
        account_id="operator-42",
    )
    authenticator = _RecordingAuthenticator(session)
    gate = _RecordingStartupGate(failure=RuntimeError("/private/secret/device.log"))
    application = build_institution_application(
        authentication_port=authenticator,
        startup_gate_factory=lambda _session: gate,
    )
    qtbot.addWidget(application.access_window)
    application.show()

    _submit_login(
        application.access_window,
        qtbot,
        account="community-kangjian",
        password="production-secret",
    )

    notice = application.access_window.findChild(QLabel, "accessFormNotice")
    assert gate.start_count == 1
    assert application.startup_gate is None
    assert application.access_window.isVisible()
    assert notice.text() == "设备启动检查暂时无法开始，请稍后重试。"
    assert "/private/secret" not in notice.text()
