from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from client.app.institution_access import InstitutionAccessWindow


ASSET_SERIAL = "FFP-DP4864-000001"


def open_activation(window: InstitutionAccessWindow, qtbot) -> None:
    qtbot.mouseClick(
        window.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION"),
        Qt.MouseButton.LeftButton,
    )


def test_activation_uses_scanned_or_entered_asset_serial_not_usb_identity(qtbot) -> None:
    window = InstitutionAccessWindow(hardware_connected=True)
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)

    assert window.findChild(QLineEdit, "assetSerialInput") is not None
    visible_text = " ".join(
        label.text() for label in window.findChildren(QLabel) if label.isVisible()
    )
    assert "usb-serial" not in visible_text.lower()
    assert "已连接可用压力设备" in window.findChild(
        QLabel, "activationHardwareStatusText"
    ).text()


def test_production_activation_requires_connected_board_and_asset_serial(qtbot) -> None:
    window = InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)
    activate = window.findChild(QPushButton, "REGISTER_INSTITUTION")
    assert not activate.isEnabled()
    window.set_hardware_connection(True)
    window.findChild(QLineEdit, "licenseCodeInput").setText("provider-code-at-least-20")
    assert not activate.isEnabled()
    window.findChild(QLineEdit, "assetSerialInput").setText(ASSET_SERIAL)
    assert activate.isEnabled()


def test_activation_refreshes_hardware_state_when_registration_opens(qtbot) -> None:
    checks = iter((False, True))
    window = InstitutionAccessWindow(
        hardware_connection_ready=lambda: next(checks),
    )
    qtbot.addWidget(window)
    window.show()

    open_activation(window, qtbot)

    assert window.findChild(QLabel, "activationHardwareStatusText").text() == "未发现可激活硬件"
    qtbot.mouseClick(
        window.findChild(QPushButton, "RECHECK_ACTIVATION_HARDWARE"),
        Qt.MouseButton.LeftButton,
    )
    assert window.findChild(QLabel, "activationHardwareStatusText").text() == "已连接可用压力设备"


def test_activation_callback_receives_asset_serial(qtbot) -> None:
    calls: list[tuple[str, str, str, str, str]] = []
    window = InstitutionAccessWindow(
        hardware_connected=True,
        on_activate=lambda *values: calls.append(values),
    )
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)
    window.findChild(QLineEdit, "registrationAccountInput").setText("seed-clinic")
    window.findChild(QLineEdit, "assetSerialInput").setText(ASSET_SERIAL)
    window.findChild(QLineEdit, "licenseCodeInput").setText("provider-activation-code-at-least-20")
    window.findChild(QLineEdit, "registrationPasswordInput").setText("correct-horse-battery-staple")
    window.findChild(QLineEdit, "registrationPasswordConfirmationInput").setText("correct-horse-battery-staple")
    qtbot.mouseClick(window.findChild(QPushButton, "REGISTER_INSTITUTION"), Qt.MouseButton.LeftButton)

    assert calls == [
        ("seed-clinic", ASSET_SERIAL, "provider-activation-code-at-least-20", "correct-horse-battery-staple", "correct-horse-battery-staple")
    ]


def test_local_test_license_does_not_call_production_activation(qtbot) -> None:
    calls: list[tuple[str, ...]] = []
    window = InstitutionAccessWindow(on_activate=lambda *values: calls.append(values), allow_local_test_handoff=True)
    qtbot.addWidget(window)
    window.show()
    open_activation(window, qtbot)
    window.findChild(QLineEdit, "registrationAccountInput").setText("local-test")
    window.findChild(QLineEdit, "licenseCodeInput").setText("FFP-2026-TEST-0001")
    window.findChild(QLineEdit, "registrationPasswordInput").setText("local-test-password")
    window.findChild(QLineEdit, "registrationPasswordConfirmationInput").setText("local-test-password")
    qtbot.mouseClick(window.findChild(QPushButton, "REGISTER_INSTITUTION"), Qt.MouseButton.LeftButton)
    assert calls == []
