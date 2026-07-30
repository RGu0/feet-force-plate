from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from client.app.controller import ApplicationController
from client.app.hardware_failure import resolve_hardware_ui_failure
from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.device.session_ui import (
    HardwareRecoveryAction,
    HardwareUiFailure,
    HardwareUiFailureCode,
)
from client.workflow.models import (
    ClientAction,
    SessionValidity,
    WorkflowState,
)
from client.workflow.state_machine import ScreeningStep


class _Coordinator:
    def __init__(self) -> None:
        self._state = WorkflowState(step=ScreeningStep.ACQUIRING, session_id="session-1")

    @property
    def state(self) -> WorkflowState:
        return self._state

    def handle_hardware_failure(self, *, error) -> None:
        self._state = WorkflowState(
            step=ScreeningStep.INCOMPLETE,
            session_id="session-1",
            validity=SessionValidity.INCOMPLETE,
            error=error,
        )


def _failure(
    code: HardwareUiFailureCode,
    action: HardwareRecoveryAction,
    retry_allowed: bool,
) -> HardwareUiFailure:
    return HardwareUiFailure(
        code=code,
        recovery_action=action,
        retry_allowed=retry_allowed,
        operator_message_key=f"hardware.failure.{code.value.lower()}",
    )


def test_retryable_device_disconnect_resolves_without_transport_detail() -> None:
    error = resolve_hardware_ui_failure(
        _failure(
            HardwareUiFailureCode.DEVICE_DISCONNECTED,
            HardwareRecoveryAction.RECONNECT_DEVICE,
            True,
        )
    )

    assert error.code == "E-DEV-002"
    assert error.action is ClientAction.RETRY_SCREENING
    assert "重新连接" in error.operator_message
    assert "usbserial" not in repr(error).lower()
    assert "serialexception" not in repr(error).lower()


def test_controller_presents_retryable_hardware_failure_to_operator(qtbot) -> None:
    controller = ApplicationController(_Coordinator())
    qtbot.addWidget(controller.window)

    controller.on_hardware_failure(
        _failure(
            HardwareUiFailureCode.DEVICE_DISCONNECTED,
            HardwareRecoveryAction.RECONNECT_DEVICE,
            True,
        )
    )

    page = controller.window.page_widget(PageId.RESULT)
    assert controller.window.current_page_id is PageId.RESULT
    assert "重新连接" in page.findChild(QLabel, "resultSummary").text()
    assert page.findChild(QPushButton, "RETRY_SCREENING").isVisibleTo(page)


def test_support_only_hardware_failure_hides_retry_and_shows_safe_instruction(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    error = resolve_hardware_ui_failure(
        _failure(
            HardwareUiFailureCode.LOCAL_FINALIZATION_FAILED,
            HardwareRecoveryAction.CONTACT_SUPPORT,
            False,
        )
    )

    window.present_state(
        WorkflowState(
            step=ScreeningStep.INCOMPLETE,
            validity=SessionValidity.INCOMPLETE,
            error=error,
        )
    )

    page = window.page_widget(PageId.RESULT)
    assert "联系技术支持" in page.findChild(QLabel, "resultSummary").text()
    assert "质量校核" not in page.findChild(QLabel, "basicReportStatusText").text()
    assert not page.findChild(QPushButton, "RETRY_SCREENING").isVisibleTo(page)
