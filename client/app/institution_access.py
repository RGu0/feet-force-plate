"""P-00 institution login and first-use License registration surfaces."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.cloud.runtime import StableHardwareRequired

from .app_icon import application_icon
from .design_system import apply_design_system


LOCAL_UI_TEST_LICENSE = "FFP-2026-TEST-0001"
_LOGGER = logging.getLogger(__name__)


def scaled_brand_logo_for_display(
    pixmap: QPixmap, *, logical_height: int, device_pixel_ratio: float
) -> QPixmap:
    """Keep a logo sharp while preserving its requested Qt logical height."""

    rendered = pixmap.scaledToHeight(
        round(logical_height * device_pixel_ratio), Qt.TransformationMode.SmoothTransformation
    )
    rendered.setDevicePixelRatio(device_pixel_ratio)
    return rendered


class InstitutionAccessWindow(QMainWindow):
    """Faithful P-00/P-00b UI; authentication remains an injected concern."""

    def __init__(
        self,
        *,
        on_login: Callable[[str, str], None] | None = None,
        on_activate: Callable[[str, str, str, str, str], None] | None = None,
        hardware_connected: bool = False,
        hardware_connection_ready: Callable[[], bool] | None = None,
        allow_local_test_handoff: bool = False,
        environment_label: str | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("institutionAccessWindow")
        self.setWindowTitle("足底压力健康筛查与分析平台")
        self.setWindowIcon(application_icon())
        self.setMinimumSize(1280, 720)
        self.resize(1440, 900)
        self._on_login = on_login
        self._on_activate = on_activate
        self._hardware_connected = hardware_connected
        self._hardware_connection_ready = hardware_connection_ready
        self._allow_local_test_handoff = allow_local_test_handoff
        self._environment_label = environment_label
        self._local_test_accounts: dict[str, str] = {}
        self._stack = QStackedWidget()
        self._stack.setObjectName("institutionAccessStack")
        self._login_page = self._build_login_page()
        self._registration_page = self._build_registration_page()
        self._stack.addWidget(self._login_page)
        self._stack.addWidget(self._registration_page)
        self.setCentralWidget(self._stack)
        apply_design_system(self)

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("institutionLoginPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(0)
        layout.addStretch(1)

        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)
        brand_layout.addWidget(self._brand_logo(72), alignment=Qt.AlignmentFlag.AlignHCenter)
        brand_layout.addSpacing(24)
        title = QLabel("足底压力健康筛查与分析平台")
        title.setObjectName("accessTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 600; color: #0F172A;")
        brand_layout.addWidget(title)
        brand_layout.addSpacing(12)
        if self._environment_label:
            environment = QLabel(self._environment_label)
            environment.setObjectName("accessEnvironmentLabel")
            environment.setAlignment(Qt.AlignmentFlag.AlignCenter)
            environment.setStyleSheet("color: #B45309; font-weight: 600;")
            brand_layout.addWidget(environment)
            brand_layout.addSpacing(8)
        subtitle = QLabel("请使用机构账号登录后开始检测")
        subtitle.setObjectName("accessSubtitle")
        subtitle.setProperty("secondaryText", True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(subtitle)
        layout.addWidget(brand, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(40)

        card = QFrame()
        card.setObjectName("contentCard")
        card.setFixedWidth(420)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 28)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._field_label("机构账号"))
        account = QLineEdit()
        account.setObjectName("institutionAccountInput")
        account.setAccessibleName("机构账号")
        account.setPlaceholderText("例如：community-kangjian")
        card_layout.addSpacing(8)
        card_layout.addWidget(account)
        account_hint = QLabel("由平台统一分配的机构编号")
        account_hint.setProperty("mutedText", True)
        card_layout.addSpacing(6)
        card_layout.addWidget(account_hint)
        card_layout.addSpacing(20)
        card_layout.addWidget(self._field_label("登录密码"))
        password = QLineEdit()
        password.setObjectName("institutionPasswordInput")
        password.setAccessibleName("登录密码")
        password.setEchoMode(QLineEdit.EchoMode.Password)
        password.setPlaceholderText("请输入登录密码")
        card_layout.addSpacing(8)
        card_layout.addWidget(password)
        notice = QLabel()
        notice.setObjectName("accessFormNotice")
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #C23B3B; font-size: 14px;")
        notice.hide()
        card_layout.addSpacing(8)
        card_layout.addWidget(notice)
        card_layout.addSpacing(24)
        login = self._button("LOGIN_INSTITUTION", "登录", primary=True)
        login.clicked.connect(lambda: self._submit_login(account.text(), password.text()))
        card_layout.addWidget(login)
        card_layout.addSpacing(20)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(
            self._status_pill(
                "loginDeviceStatus",
                self._login_hardware_status_text(),
                "success" if self._hardware_connected else "warning",
            )
        )
        status_row.addStretch(1)
        recheck_hardware = self._button(
            "RECHECK_LOGIN_HARDWARE", "重新检查硬件", ghost=True
        )
        recheck_hardware.clicked.connect(self._refresh_hardware_connection)
        status_row.addWidget(recheck_hardware)
        unable = self._button("LOGIN_HELP", "无法登录？", ghost=True)
        status_row.addWidget(unable)
        card_layout.addLayout(status_row)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #E2E8F0;")
        card_layout.addSpacing(20)
        card_layout.addWidget(separator)
        card_layout.addSpacing(12)
        registration_row = QHBoxLayout()
        registration_row.setContentsMargins(0, 0, 0, 0)
        registration_label = QLabel("还没有机构账户？")
        registration_label.setProperty("mutedText", True)
        registration_row.addStretch(1)
        registration_row.addWidget(registration_label)
        open_registration = self._button(
            "OPEN_LICENSE_REGISTRATION", "使用 License 注册", ghost=True
        )
        open_registration.clicked.connect(self._show_registration)
        registration_row.addWidget(open_registration)
        registration_row.addStretch(1)
        card_layout.addLayout(registration_row)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(32)
        footer = QLabel(
            "软件版本 1.0.0 · 本平台为健康筛查与分析工具，非临床诊断"
        )
        footer.setObjectName("accessFooter")
        footer.setProperty("mutedText", True)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        layout.addStretch(1)
        return page

    def _build_registration_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("licenseRegistrationPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(32, 32, 32, 32)
        page_layout.setSpacing(0)
        page_layout.addStretch(1)

        card = QFrame()
        card.setObjectName("registrationCard")
        card.setFixedWidth(920)
        card.setStyleSheet(
            "QFrame#registrationCard { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; }"
        )
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._registration_guide())
        card_layout.addWidget(self._registration_form(), 1)
        page_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        page_layout.addSpacing(24)
        footer = QLabel("License 由天富智柔随设备和机构账号发放，每个激活码仅可使用一次")
        footer.setProperty("mutedText", True)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_layout.addWidget(footer)
        page_layout.addStretch(1)
        return page

    def _registration_guide(self) -> QWidget:
        guide = QFrame()
        guide.setObjectName("registrationGuide")
        guide.setFixedWidth(340)
        guide.setStyleSheet(
            "QFrame#registrationGuide { background: #EFF5FC; border: 0; border-right: 1px solid #E2E8F0; border-top-left-radius: 12px; border-bottom-left-radius: 12px; }"
        )
        layout = QVBoxLayout(guide)
        layout.setContentsMargins(32, 40, 32, 40)
        layout.setSpacing(0)
        layout.addWidget(self._brand_logo(40), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(32)
        title = QLabel("使用 License 注册")
        title.setObjectName("registrationTitle")
        title.setStyleSheet("font-size: 24px; font-weight: 600; color: #0F172A;")
        layout.addWidget(title)
        layout.addSpacing(12)
        description = QLabel(
            "使用服务商随设备提供的机构账号和一次性激活码，连接当前硬件并设置登录密码。"
        )
        description.setProperty("secondaryText", True)
        description.setWordWrap(True)
        description.setStyleSheet("line-height: 1.7;")
        layout.addWidget(description)
        layout.addStretch(1)
        for number, text in (
            ("1", "连接随 License 发放的硬件"),
            ("2", "输入机构账号与一次性激活码"),
            ("3", "设置密码并完成激活"),
        ):
            step = QLabel(f"{number}    {text}")
            step.setObjectName(f"registrationStep{number}")
            step.setProperty("secondaryText", True)
            layout.addWidget(step)
            layout.addSpacing(14)
        return guide

    def _registration_form(self) -> QWidget:
        form = QWidget()
        layout = QVBoxLayout(form)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(0)
        account = self._line_field(
            layout,
            "机构账号",
            "registrationAccountInput",
            "请输入服务商提供的机构账号",
        )
        layout.addSpacing(16)
        asset_serial = self._line_field(
            layout,
            "设备编号",
            "assetSerialInput",
            "扫描设备标签二维码，或输入 FFP-DP4864-000001",
        )
        layout.addSpacing(16)
        layout.addWidget(self._field_label("一次性激活码 / License 码"))
        layout.addSpacing(8)
        license_code = QLineEdit()
        license_code.setObjectName("licenseCodeInput")
        license_code.setAccessibleName("一次性激活码")
        license_code.setPlaceholderText("请输入随设备提供的一次性激活码")
        layout.addWidget(license_code)
        layout.addSpacing(10)
        hardware_status = QHBoxLayout()
        hardware_status.setContentsMargins(0, 0, 0, 0)
        hardware_status.addWidget(
            self._status_pill(
                "activationHardwareStatus",
                self._hardware_status_text(),
                "success" if self._hardware_connected else "warning",
            )
        )
        hardware_status.addStretch(1)
        recheck_hardware = self._button(
            "RECHECK_ACTIVATION_HARDWARE", "重新检查硬件", ghost=True
        )
        recheck_hardware.clicked.connect(self._refresh_hardware_connection)
        hardware_status.addWidget(recheck_hardware)
        layout.addLayout(hardware_status)
        layout.addSpacing(20)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #E2E8F0;")
        layout.addWidget(divider)
        layout.addSpacing(16)
        passwords = QHBoxLayout()
        passwords.setContentsMargins(0, 0, 0, 0)
        passwords.setSpacing(16)
        password = self._password_field("登录密码", "registrationPasswordInput")
        confirmation = self._password_field("确认密码", "registrationPasswordConfirmationInput")
        passwords.addWidget(password, 1)
        passwords.addWidget(confirmation, 1)
        layout.addLayout(passwords)
        notice = QLabel()
        notice.setObjectName("registrationFormNotice")
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #C23B3B; font-size: 14px;")
        notice.hide()
        layout.addSpacing(12)
        layout.addWidget(notice)
        layout.addSpacing(28)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        back = self._button("RETURN_TO_LOGIN", "← 返回登录", ghost=True)
        back.clicked.connect(self._show_login)
        actions.addWidget(back)
        actions.addStretch(1)
        register = self._button("REGISTER_INSTITUTION", "激活 License", primary=True)
        register.setEnabled(False)
        license_code.textChanged.connect(
            lambda _text: self._update_activation_button(register)
        )
        asset_serial.textChanged.connect(lambda _text: self._update_activation_button(register))
        register.clicked.connect(
            lambda: self._submit_activation(
                account.text(),
                asset_serial.text(),
                license_code.text(),
                password.findChild(QLineEdit, "registrationPasswordInput").text(),
                confirmation.findChild(
                    QLineEdit, "registrationPasswordConfirmationInput"
                ).text(),
            )
        )
        actions.addWidget(register)
        layout.addLayout(actions)
        return form

    def _line_field(
        self, layout: QVBoxLayout, label: str, object_name: str, placeholder: str
    ) -> QLineEdit:
        layout.addWidget(self._field_label(label))
        layout.addSpacing(8)
        field = QLineEdit()
        field.setObjectName(object_name)
        field.setAccessibleName(label)
        field.setPlaceholderText(placeholder)
        layout.addWidget(field)
        return field

    def _password_field(self, label: str, object_name: str) -> QWidget:
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._field_label(label))
        layout.addSpacing(8)
        field = QLineEdit()
        field.setObjectName(object_name)
        field.setAccessibleName(label)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText("至少 12 个字符")
        layout.addWidget(field)
        return group

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("fieldLabel", True)
        return label

    @staticmethod
    def _button(
        object_name: str, text: str, *, primary: bool = False, ghost: bool = False
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        if primary:
            button.setProperty("importance", "primary")
        elif ghost:
            button.setProperty("importance", "ghost")
        return button

    @staticmethod
    def _status_pill(object_name: str, text: str, tone: str) -> QFrame:
        pill = QFrame()
        pill.setObjectName(object_name)
        pill.setProperty("statusPill", True)
        pill.setProperty("statusPillTone", tone)
        layout = QHBoxLayout(pill)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        dot = QFrame()
        dot.setProperty("statusDot", True)
        dot.setProperty("statusDotTone", tone)
        layout.addWidget(dot)
        label = QLabel(text)
        label.setObjectName(f"{object_name}Text")
        layout.addWidget(label)
        return pill

    @staticmethod
    def _brand_logo(height: int) -> QLabel:
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setAccessibleName("天富智柔 TechFlex")
        asset = Path(__file__).with_name("assets") / "logo-horizontal-trimmed.png"
        pixmap = QPixmap(str(asset))
        if not pixmap.isNull():
            screen = QGuiApplication.primaryScreen()
            device_pixel_ratio = screen.devicePixelRatio() if screen is not None else 1.0
            logo.setPixmap(
                scaled_brand_logo_for_display(
                    pixmap, logical_height=height, device_pixel_ratio=device_pixel_ratio
                )
            )
        logo.setFixedHeight(height)
        return logo

    def _show_registration(self) -> None:
        self._refresh_hardware_connection()
        self._stack.setCurrentWidget(self._registration_page)

    def _show_login(self) -> None:
        self._stack.setCurrentWidget(self._login_page)

    def _submit_login(self, account: str, password: str) -> None:
        notice = self.findChild(QLabel, "accessFormNotice")
        notice.setStyleSheet("color: #C23B3B; font-size: 14px;")
        if not account.strip() or not password:
            notice.setText("请输入机构账号和登录密码。")
            notice.show()
            return
        local_password = self._local_test_accounts.get(account.strip())
        if local_password is not None:
            if password != local_password:
                notice.setText("本机测试账户的密码不正确，请重新输入。")
                notice.show()
                return
            notice.setStyleSheet("color: #15803D; font-size: 14px;")
            notice.setText("本机测试账户登录成功。该账户仅在本次应用运行期间有效。")
            notice.show()
            if self._allow_local_test_handoff and self._on_login is not None:
                self._on_login(account.strip(), password)
            return
        if self._on_login is None:
            notice.setText("当前版本尚未连接 License 服务，暂不能登录。")
            notice.show()
            return
        notice.hide()
        try:
            self._on_login(account.strip(), password)
        except Exception as error:
            _LOGGER.error(
                "institution login handoff failed: %s",
                type(error).__name__,
            )
            self.show()
            if isinstance(error, StableHardwareRequired):
                self.set_hardware_connection(False)
                notice.setText(
                    "未发现可用压力设备，请检查 USB 数据线和供电后点击重新检查硬件。"
                )
            else:
                notice.setText("登录未完成，请检查账号、网络和已连接设备后重试。")
            notice.show()

    def show_login_error(self, message: str) -> None:
        """Show a composition-layer error without exposing adapter details."""

        notice = self.findChild(QLabel, "accessFormNotice")
        notice.setStyleSheet("color: #C23B3B; font-size: 14px;")
        notice.setText(message)
        notice.show()

    def _submit_activation(
        self,
        account: str,
        asset_serial: str,
        activation_code: str,
        password: str,
        password_confirmation: str,
    ) -> None:
        notice = self.findChild(QLabel, "registrationFormNotice")
        notice.setStyleSheet("color: #C23B3B; font-size: 14px;")
        local_test_code = activation_code.strip().upper() == LOCAL_UI_TEST_LICENSE
        required = (account, activation_code, password, password_confirmation)
        if not all(value.strip() for value in required) or (
            not local_test_code and not asset_serial.strip()
        ):
            notice.setText("请填写机构账号、设备编号、一次性激活码和两次密码。")
            notice.show()
            return
        if password != password_confirmation:
            notice.setText("两次输入的密码不一致，请重新确认。")
            notice.show()
            return
        if len(password) < 12:
            notice.setText("登录密码至少需要 12 个字符，请重新设置。")
            notice.show()
            return
        normalized_code = activation_code.strip().upper()
        normalized_account = account.strip()
        if normalized_code == LOCAL_UI_TEST_LICENSE:
            if not self._allow_local_test_handoff:
                notice.setText("本机测试 License 仅可在显式测试模式下使用。")
                notice.show()
                return
            if normalized_account in self._local_test_accounts:
                notice.setText("该本机测试机构账号已创建，请返回登录。")
                notice.show()
                return
            self._local_test_accounts[normalized_account] = password
            self._show_login()
            self.findChild(QLineEdit, "institutionAccountInput").setText(
                normalized_account
            )
            login_notice = self.findChild(QLabel, "accessFormNotice")
            login_notice.setStyleSheet("color: #15803D; font-size: 14px;")
            login_notice.setText("本机测试账户已创建，请使用设置的密码登录。")
            login_notice.show()
            return
        self._refresh_hardware_connection()
        if not self._hardware_connected:
            notice.setText("未发现可用于激活的硬件，请连接设备后重试。")
            notice.show()
            return
        if self._on_activate is None:
            notice.setText("当前版本尚未连接 License 服务，无法激活并创建账户。")
            notice.show()
            return
        notice.hide()
        try:
            self._on_activate(
                normalized_account,
                asset_serial.strip().upper(),
                activation_code.strip(),
                password,
                password_confirmation,
            )
        except Exception:
            notice.setText("激活未完成，请核对账号、激活码、网络和硬件后重试。")
            notice.show()

    def _refresh_hardware_connection(self) -> bool:
        """Refresh the activation gate instead of relying on startup-time USB state."""

        if self._hardware_connection_ready is None:
            return self._hardware_connected
        try:
            connected = bool(self._hardware_connection_ready())
        except Exception:
            connected = False
        self.set_hardware_connection(connected)
        return connected

    def set_hardware_connection(self, connected: bool) -> None:
        self._hardware_connected = connected
        activation_label = self.findChild(QLabel, "activationHardwareStatusText")
        activation_pill = self.findChild(QFrame, "activationHardwareStatus")
        if activation_label is not None and activation_pill is not None:
            activation_label.setText(self._hardware_status_text())
            self._set_pill_tone(activation_pill, "success" if connected else "warning")
        login_label = self.findChild(QLabel, "loginDeviceStatusText")
        login_pill = self.findChild(QFrame, "loginDeviceStatus")
        if login_label is not None and login_pill is not None:
            login_label.setText(self._login_hardware_status_text())
            self._set_pill_tone(login_pill, "success" if connected else "warning")
        button = self.findChild(QPushButton, "REGISTER_INSTITUTION")
        if button is not None:
            self._update_activation_button(button)

    def _hardware_status_text(self) -> str:
        if not self._hardware_connected:
            return "未发现可激活硬件"
        return "已连接可用压力设备"

    def _login_hardware_status_text(self) -> str:
        if not self._hardware_connected:
            return "未发现可用压力设备"
        return "已连接可用压力设备"

    def _update_activation_button(self, button: QPushButton) -> None:
        code = self.findChild(QLineEdit, "licenseCodeInput").text()
        asset_serial = self.findChild(QLineEdit, "assetSerialInput").text()
        local_test = (
            self._allow_local_test_handoff
            and code.strip().upper() == LOCAL_UI_TEST_LICENSE
        )
        button.setEnabled(
            local_test or (self._hardware_connected and bool(code.strip()) and bool(asset_serial.strip()))
        )

    @staticmethod
    def _set_pill_tone(pill: QFrame, tone: str) -> None:
        pill.setProperty("statusPillTone", tone)
        dot = pill.findChild(QFrame)
        if dot is not None:
            dot.setProperty("statusDotTone", tone)
            dot.style().unpolish(dot)
            dot.style().polish(dot)
        pill.style().unpolish(pill)
        pill.style().polish(pill)
