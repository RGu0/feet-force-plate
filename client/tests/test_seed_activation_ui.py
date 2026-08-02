from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from client.app.institution_access import InstitutionAccessWindow


HARDWARE_ID = "usb-serial-0123456789abcdef0123"


def open_activation(window: InstitutionAccessWindow, qtbot) -> None:
    qtbot.mouseClick(
        window.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION"),
        Qt.MouseButton.LeftButton,
    )


def test_seed_activation_uses_provider_provisioned_fields_only(qtbot) -> None:
    window = InstitutionAccessWindow(stable_hardware_id=HARDWARE_ID)
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)

    assert window.findChild(QLineEdit, "registrationAccountInput") is not None
    assert window.findChild(QLineEdit, "licenseCodeInput") is not None
    assert window.findChild(QLineEdit, "registrationPasswordInput") is not None
    assert window.findChild(QLineEdit, "registrationPasswordConfirmationInput") is not None
    assert window.findChild(QLineEdit, "registrationOrganizationInput") is None
    visible_text = " ".join(
        label.text() for label in window.findChildren(QLabel) if label.isVisible()
    )
    for forbidden in ("检索机构", "新建机构", "选择机构", "机构管理员"):
        assert forbidden not in visible_text
    hardware_text = window.findChild(QLabel, "activationHardwareStatusText").text()
    assert HARDWARE_ID not in hardware_text
    assert hardware_text.endswith(HARDWARE_ID[-6:])


def test_production_activation_is_disabled_until_stable_hardware_exists(qtbot) -> None:
    window = InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)

    activate = window.findChild(QPushButton, "REGISTER_INSTITUTION")
    assert not activate.isEnabled()
    window.set_hardware_identity(HARDWARE_ID)
    assert activate.isEnabled()


def test_activation_callback_receives_account_code_passwords_and_hardware(qtbot) -> None:
    calls: list[tuple[str, str, str, str, str]] = []
    window = InstitutionAccessWindow(
        stable_hardware_id=HARDWARE_ID,
        on_activate=lambda *values: calls.append(values),
    )
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)
    window.findChild(QLineEdit, "registrationAccountInput").setText("seed-clinic")
    window.findChild(QLineEdit, "licenseCodeInput").setText(
        "provider-activation-code-at-least-20"
    )
    window.findChild(QLineEdit, "registrationPasswordInput").setText(
        "correct-horse-battery-staple"
    )
    window.findChild(QLineEdit, "registrationPasswordConfirmationInput").setText(
        "correct-horse-battery-staple"
    )

    qtbot.mouseClick(
        window.findChild(QPushButton, "REGISTER_INSTITUTION"),
        Qt.MouseButton.LeftButton,
    )

    assert calls == [
        (
            "seed-clinic",
            "provider-activation-code-at-least-20",
            "correct-horse-battery-staple",
            "correct-horse-battery-staple",
            HARDWARE_ID,
        )
    ]


def test_local_test_license_does_not_call_production_activation(qtbot) -> None:
    calls: list[tuple[str, ...]] = []
    window = InstitutionAccessWindow(
        on_activate=lambda *values: calls.append(values),
        allow_local_test_handoff=True,
    )
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)
    window.findChild(QLineEdit, "registrationAccountInput").setText("local-test")
    window.findChild(QLineEdit, "licenseCodeInput").setText("FFP-2026-TEST-0001")
    window.findChild(QLineEdit, "registrationPasswordInput").setText(
        "local-test-password"
    )
    window.findChild(QLineEdit, "registrationPasswordConfirmationInput").setText(
        "local-test-password"
    )

    qtbot.mouseClick(
        window.findChild(QPushButton, "REGISTER_INSTITUTION"),
        Qt.MouseButton.LeftButton,
    )

    assert calls == []
