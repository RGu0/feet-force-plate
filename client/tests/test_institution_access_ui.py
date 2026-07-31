from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

import client.app
from client.app import institution_access


def test_brand_logo_keeps_retina_native_pixels_at_its_logical_size(qapp) -> None:
    """Catch a 1x logo pixmap being enlarged on a 2x display and becoming blurry."""

    source = QPixmap.fromImage(QImage(600, 200, QImage.Format.Format_ARGB32))

    prepared = institution_access.scaled_brand_logo_for_display(
        source, logical_height=72, device_pixel_ratio=2.0
    )

    assert prepared.width() == 432
    assert prepared.height() == 144
    assert prepared.devicePixelRatio() == 2.0
    assert prepared.deviceIndependentSize().height() == 72.0


def test_p00_login_opens_the_p00b_license_registration_form(qtbot) -> None:
    """Catch a regression that removes the only route to first-use registration."""

    window = client.app.InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.findChild(QLabel, "accessTitle").isVisible()
    assert not window.findChild(QLabel, "registrationTitle").isVisible()
    assert window.findChild(QLabel, "accessTitle").text() == "足底压力健康筛查与分析平台"
    assert window.findChild(QLineEdit, "institutionAccountInput") is not None
    password = window.findChild(QLineEdit, "institutionPasswordInput")
    assert password.echoMode() is QLineEdit.EchoMode.Password

    qtbot.mouseClick(
        window.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION"),
        Qt.MouseButton.LeftButton,
    )

    assert window.findChild(QLabel, "registrationTitle").isVisible()
    assert window.findChild(QLineEdit, "licenseCodeInput") is not None
    assert window.findChild(QLineEdit, "registrationOrganizationInput") is not None
    assert window.findChild(QPushButton, "VALIDATE_LICENSE").isVisible()
    assert window.findChild(QPushButton, "RETURN_TO_LOGIN").isVisible()


def test_local_test_license_is_presented_as_a_local_only_test_license(
    qtbot,
) -> None:
    """Catch the documented test code falling through to the unavailable-service state."""

    window = client.app.InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.mouseClick(
        window.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION"),
        Qt.MouseButton.LeftButton,
    )
    window.findChild(QLineEdit, "licenseCodeInput").setText("FFP-2026-TEST-0001")

    qtbot.mouseClick(
        window.findChild(QPushButton, "VALIDATE_LICENSE"),
        Qt.MouseButton.LeftButton,
    )

    status = window.findChild(QLabel, "licenseValidationStatusText")
    assert status.text() == "本机测试 License 已校验"


def test_local_test_license_creates_an_account_and_allows_local_login(qtbot) -> None:
    """Catch a test registration that never creates credentials usable by local login."""

    successful_logins: list[tuple[str, str]] = []
    window = client.app.InstitutionAccessWindow(
        on_login=lambda account, password: successful_logins.append((account, password))
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.mouseClick(
        window.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION"),
        Qt.MouseButton.LeftButton,
    )
    window.findChild(QLineEdit, "licenseCodeInput").setText("FFP-2026-TEST-0001")
    window.findChild(QLineEdit, "registrationOrganizationInput").setText("本机测试机构")
    window.findChild(QLineEdit, "registrationAccountInput").setText("local-test")
    window.findChild(QLineEdit, "registrationPasswordInput").setText("local-test-password")
    window.findChild(QLineEdit, "registrationPasswordConfirmationInput").setText(
        "local-test-password"
    )

    qtbot.mouseClick(
        window.findChild(QPushButton, "REGISTER_INSTITUTION"), Qt.MouseButton.LeftButton
    )

    account = window.findChild(QLineEdit, "institutionAccountInput")
    assert account.text() == "local-test"
    assert window.findChild(QLabel, "accessFormNotice").text() == (
        "本机测试账户已创建，请使用设置的密码登录。"
    )

    window.findChild(QLineEdit, "institutionPasswordInput").setText("local-test-password")
    qtbot.mouseClick(
        window.findChild(QPushButton, "LOGIN_INSTITUTION"), Qt.MouseButton.LeftButton
    )

    assert successful_logins == [("local-test", "local-test-password")]


def test_login_requires_both_institution_account_and_password(qtbot) -> None:
    """Catch a login CTA that appears active but silently accepts blank credentials."""

    window = client.app.InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()

    qtbot.mouseClick(
        window.findChild(QPushButton, "LOGIN_INSTITUTION"), Qt.MouseButton.LeftButton
    )

    notice = window.findChild(QLabel, "accessFormNotice")
    assert notice.isVisible()
    assert notice.text() == "请输入机构账号和登录密码。"


def test_login_does_not_claim_success_when_the_license_service_is_unavailable(qtbot) -> None:
    """Catch a false login success before the real authentication port is wired."""

    window = client.app.InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()
    window.findChild(QLineEdit, "institutionAccountInput").setText("community-kangjian")
    window.findChild(QLineEdit, "institutionPasswordInput").setText("not-a-real-password")

    qtbot.mouseClick(
        window.findChild(QPushButton, "LOGIN_INSTITUTION"), Qt.MouseButton.LeftButton
    )

    notice = window.findChild(QLabel, "accessFormNotice")
    assert notice.isVisible()
    assert notice.text() == "当前版本尚未连接 License 服务，暂不能登录。"


def test_registration_requires_complete_values_before_attempting_activation(qtbot) -> None:
    """Catch an activation CTA that crashes or sends an incomplete registration."""

    window = client.app.InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.mouseClick(
        window.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION"),
        Qt.MouseButton.LeftButton,
    )

    qtbot.mouseClick(
        window.findChild(QPushButton, "REGISTER_INSTITUTION"),
        Qt.MouseButton.LeftButton,
    )

    notice = window.findChild(QLabel, "registrationFormNotice")
    assert notice.isVisible()
    assert notice.text() == "请填写 License、机构信息、机构账号和两次密码。"
