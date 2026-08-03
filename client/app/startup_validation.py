from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading
from typing import Any, Protocol

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from client.startup_validation.models import DeviceValidationRun, ValidationOutcome
from client.startup_validation.workflow import (
    StartupProgressMode,
    StartupPresentation,
    StartupValidationState,
    presentation_for,
)

from .design_system import apply_design_system
from .app_icon import application_icon


class StartupCoordinator(Protocol):
    @property
    def can_enter_workbench(self) -> bool: ...

    def run(self) -> DeviceValidationRun: ...

    def retry(self) -> DeviceValidationRun: ...


class StartupValidationWindow(QMainWindow):
    """Steady Health launch screen shown before the operator workbench."""

    def __init__(
        self,
        *,
        on_retry: Callable[[], None] | None = None,
        on_exit: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("startupValidationWindow")
        self.setWindowTitle("足底压力健康筛查与分析平台")
        self.setWindowIcon(application_icon())
        self.setMinimumSize(1280, 720)
        self.resize(1440, 900)
        self._on_retry = on_retry or (lambda: None)
        self._on_exit = on_exit or (lambda: None)
        self._presentation = presentation_for(StartupValidationState.BOOTSTRAPPING)
        self._build_ui()
        apply_design_system(self)
        self.present(self._presentation)

    @property
    def presentation(self) -> StartupPresentation:
        return self._presentation

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appSurface")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(40, 0, 40, 0)
        header_layout.setSpacing(16)
        header_layout.addWidget(self._brand_logo(28))
        divider = QLabel()
        divider.setObjectName("brandDivider")
        header_layout.addWidget(divider)
        product_name = QLabel("足底压力健康筛查与分析平台")
        product_name.setObjectName("organizationName")
        header_layout.addWidget(product_name)
        header_layout.addStretch(1)
        root_layout.addWidget(header)

        canvas = QWidget()
        canvas.setObjectName("pageCanvas")
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(48, 48, 48, 32)
        canvas_layout.setSpacing(0)
        canvas_layout.addStretch(1)

        card = QFrame()
        card.setObjectName("contentCard")
        card.setMinimumWidth(680)
        card.setMaximumWidth(720)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(48, 44, 48, 40)
        card_layout.setSpacing(0)

        eyebrow = QLabel("启动设备检查")
        eyebrow.setProperty("eyebrow", True)
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(eyebrow)
        card_layout.addSpacing(24)

        self._status_icon = QSvgWidget()
        self._status_icon.setObjectName("startupStatusIcon")
        self._status_icon.setFixedSize(56, 56)
        icon_row = QHBoxLayout()
        icon_row.addStretch(1)
        icon_row.addWidget(self._status_icon)
        icon_row.addStretch(1)
        card_layout.addLayout(icon_row)
        card_layout.addSpacing(20)

        self._title = QLabel()
        self._title.setObjectName("startupTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("font-size: 28px; font-weight: 600; color: #0F172A;")
        card_layout.addWidget(self._title)
        card_layout.addSpacing(12)

        self._message = QLabel()
        self._message.setObjectName("startupMessage")
        self._message.setProperty("secondaryText", True)
        self._message.setWordWrap(True)
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        card_layout.addWidget(self._message)
        card_layout.addSpacing(32)

        self._progress = QProgressBar()
        self._progress.setObjectName("startupProgress")
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        card_layout.addWidget(self._progress)
        card_layout.addSpacing(12)

        progress_row = QHBoxLayout()
        self._progress_text = QLabel()
        self._progress_text.setObjectName("startupProgressText")
        self._progress_text.setProperty("mutedText", True)
        self._countdown = QLabel()
        self._countdown.setObjectName("startupCountdown")
        self._countdown.setProperty("secondaryText", True)
        self._countdown.setStyleSheet("font-weight: 600;")
        progress_row.addWidget(self._progress_text)
        progress_row.addStretch(1)
        progress_row.addWidget(self._countdown)
        card_layout.addLayout(progress_row)

        self._error_code = QLabel()
        self._error_code.setObjectName("startupErrorCode")
        self._error_code.setProperty("mutedText", True)
        self._error_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._error_code)
        card_layout.addSpacing(20)

        self._primary_action = QPushButton()
        self._primary_action.setObjectName("startupPrimaryAction")
        self._primary_action.setProperty("importance", "primary")
        self._primary_action.clicked.connect(self._on_retry)
        card_layout.addWidget(self._primary_action)

        card_row = QHBoxLayout()
        card_row.addStretch(1)
        card_row.addWidget(card)
        card_row.addStretch(1)
        canvas_layout.addLayout(card_row)
        canvas_layout.addStretch(1)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 20, 0, 0)
        local_note = QLabel("启动检查在本机完成，无需联网")
        local_note.setProperty("mutedText", True)
        footer_row.addWidget(local_note)
        footer_row.addStretch(1)
        self._exit_action = QPushButton("安全退出")
        self._exit_action.setObjectName("EXIT_APPLICATION")
        self._exit_action.setProperty("importance", "ghost")
        self._exit_action.clicked.connect(self._on_exit)
        footer_row.addWidget(self._exit_action)
        canvas_layout.addLayout(footer_row)

        root_layout.addWidget(canvas, 1)
        self.setCentralWidget(root)

    def present(self, presentation: StartupPresentation) -> None:
        self._presentation = presentation
        self._title.setText(presentation.title)
        self._message.setText(presentation.message)
        self._set_status_icon(presentation.state)

        progress_visible = presentation.progress_mode is not StartupProgressMode.HIDDEN
        self._progress.setVisible(progress_visible)
        if presentation.progress_mode is StartupProgressMode.INDETERMINATE:
            self._progress.setRange(0, 0)
            self._progress_text.setText("正在处理")
        elif presentation.progress_mode in {
            StartupProgressMode.DETERMINATE,
            StartupProgressMode.COMPLETE,
        }:
            fraction = max(0.0, min(1.0, presentation.progress_fraction or 0.0))
            percentage = round(fraction * 100)
            self._progress.setRange(0, 100)
            self._progress.setValue(percentage)
            self._progress_text.setText(f"已完成 {percentage}%")
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            self._progress_text.clear()
        self._progress_text.setVisible(progress_visible)

        has_countdown = (
            presentation.countdown_seconds is not None
            and presentation.state is StartupValidationState.COLLECTING_BASELINE
        )
        self._countdown.setText(
            f"{presentation.countdown_seconds} 秒" if has_countdown else ""
        )
        self._countdown.setVisible(has_countdown)

        has_error = presentation.error_code is not None
        self._error_code.setText(
            f"诊断编号 {presentation.error_code}" if has_error else ""
        )
        self._error_code.setVisible(has_error)

        has_action = presentation.primary_action is not None
        self._primary_action.setText(presentation.primary_action or "")
        self._primary_action.setAccessibleName(presentation.primary_action or "启动检查主要操作")
        self._primary_action.setVisible(has_action)
        self._primary_action.setEnabled(has_action)
        self._exit_action.setVisible(presentation.can_exit)
        if has_action:
            QTimer.singleShot(0, self._focus_primary_action)

    def _focus_primary_action(self) -> None:
        if self._primary_action.isVisible() and self._primary_action.isEnabled():
            self.raise_()
            self.activateWindow()
            self._primary_action.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_attempt_running(self, running: bool) -> None:
        self._primary_action.setEnabled(not running)

    def _set_status_icon(self, state: StartupValidationState) -> None:
        if state is StartupValidationState.PASSED:
            asset = "status-success.svg"
        elif state in {
            StartupValidationState.DEVICE_NOT_FOUND,
            StartupValidationState.DEVICE_BUSY,
            StartupValidationState.LOAD_NOT_EMPTY,
            StartupValidationState.STREAM_INTERRUPTED,
            StartupValidationState.SIGNAL_INVALID,
            StartupValidationState.SERVICE_REQUIRED,
            StartupValidationState.INTERNAL_ERROR,
        }:
            asset = "status-warning.svg"
        else:
            asset = "status-warning.svg"
        self._status_icon.load(str(Path(__file__).with_name("assets") / asset))

    @staticmethod
    def _brand_logo(height: int) -> QLabel:
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setAccessibleName("天富智柔 TechFlex")
        path = Path(__file__).with_name("assets") / "logo-horizontal-trimmed.png"
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaledToHeight(
                    height,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        logo.setFixedHeight(height)
        return logo


class _GateSignals(QObject):
    presentation = Signal(object)
    completed = Signal(object)


class MandatoryStartupGate(QObject):
    """Asynchronous gate that creates the workbench only after a passing run."""

    def __init__(
        self,
        *,
        coordinator_factory: Callable[[Callable[[StartupPresentation], None]], StartupCoordinator],
        workbench_factory: Callable[[], QWidget],
        quit_application: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._signals = _GateSignals(self)
        self._signals.presentation.connect(self._present)
        self._signals.completed.connect(self._attempt_completed)
        self._coordinator = coordinator_factory(self._signals.presentation.emit)
        self._workbench_factory = workbench_factory
        self._quit_application = quit_application or QApplication.quit
        self._workbench: QWidget | None = None
        self._running = False
        self.window = StartupValidationWindow(
            on_retry=self.retry,
            on_exit=self._quit_application,
        )

    @property
    def workbench(self) -> QWidget | None:
        return self._workbench

    def start(self) -> None:
        self.window.show()
        QTimer.singleShot(0, lambda: self._start_attempt(retry=False))

    def retry(self) -> None:
        self._start_attempt(retry=True)

    def _start_attempt(self, *, retry: bool) -> None:
        if self._running:
            return
        self._running = True
        self.window.set_attempt_running(True)
        target = self._coordinator.retry if retry else self._coordinator.run

        def worker() -> None:
            try:
                run = target()
            except Exception as error:  # pragma: no cover - final safety boundary
                self._signals.completed.emit(error)
            else:
                self._signals.completed.emit(run)

        threading.Thread(
            target=worker,
            name="startup-device-validation",
            daemon=True,
        ).start()

    def _present(self, presentation: StartupPresentation) -> None:
        self.window.present(presentation)

    def _attempt_completed(self, result: Any) -> None:
        self._running = False
        self.window.set_attempt_running(False)
        if (
            isinstance(result, DeviceValidationRun)
            and result.outcome is ValidationOutcome.PASS
            and self._coordinator.can_enter_workbench
        ):
            self._workbench = self._workbench_factory()
            self._workbench.show()
            self.window.hide()
            return
        if isinstance(result, Exception):
            self.window.present(presentation_for(StartupValidationState.INTERNAL_ERROR))
