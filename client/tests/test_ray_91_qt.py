from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.workflow.models import (
    PreflightCheck,
    ReportStatus,
    SessionValidity,
    WorkflowState,
)
from client.workflow.protocol import PositionGuidanceState, PositionStatus
from client.workflow.state_machine import ScreeningStep


def test_position_page_presents_numeric_and_text_countdown_with_one_main_action(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    guidance = PositionGuidanceState(
        status=PositionStatus.STABILIZING,
        instruction_text="双脚自然站立，保持身体放松",
        countdown_seconds=2,
        countdown_text="正在确认站位稳定… 2 秒",
        manual_start_allowed=False,
    )

    window.present_state(
        WorkflowState(
            step=ScreeningStep.POSITION_GUIDANCE,
            position_guidance=guidance,
        )
    )

    page = window.page_widget(PageId.POSITION_GUIDANCE)
    assert page.findChild(QLabel, "positionStatus").text() == guidance.instruction_text
    assert page.findChild(QLabel, "positionState").text() == guidance.countdown_text
    assert page.findChild(QLabel, "countdownLabel").text() == "2"
    start = page.findChild(QPushButton, "START_ACQUISITION")
    assert start.text() == "开始本段"
    assert not start.isEnabled()
    assert not window.global_navigation_enabled


def test_preflight_shows_four_checks_and_waits_for_operator_entry(qtbot) -> None:
    actions: list[str] = []
    window = ScreeningWindow(on_action=actions.append)
    qtbot.addWidget(window)
    window.present_state(
        WorkflowState(
            step=ScreeningStep.PREFLIGHT,
            preflight_checks=(
                PreflightCheck("device_connected", True, operator_message="已连接"),
                PreflightCheck("storage_space", True, operator_message="空间充足"),
                PreflightCheck(
                    "calibration_status",
                    True,
                    operator_message="最近校准 07-20",
                ),
                PreflightCheck("data_sync", True, operator_message="已同步"),
            ),
            preflight_ready=True,
        )
    )

    page = window.page_widget(PageId.PREFLIGHT)
    assert page.findChild(QLabel, "deviceCheckHint").text() == "已连接"
    assert page.findChild(QLabel, "storageCheckHint").text() == "空间充足"
    assert page.findChild(QLabel, "calibrationCheckHint").text() == "最近校准 07-20"
    assert page.findChild(QLabel, "syncCheckHint").text() == "已同步"
    enter = page.findChild(QPushButton, "ENTER_POSITION")
    assert enter.isEnabled()
    assert window.current_page_id is PageId.PREFLIGHT

    qtbot.mouseClick(enter, Qt.MouseButton.LeftButton)

    assert actions == ["ENTER_POSITION"]


def test_acquisition_page_uses_protocol_prompt_and_only_exposes_stop(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    window.present_state(
        WorkflowState(
            step=ScreeningStep.ACQUIRING,
            acquisition_instruction="请保持自然站立，不要说话或大幅移动",
        )
    )

    page = window.page_widget(PageId.ACQUIRING)
    assert "不要说话" in page.findChild(QLabel, "acquisitionInstruction").text()
    assert page.findChild(QPushButton, "STOP_SCREENING") is not None
    assert not window.global_navigation_enabled


def test_stop_action_requires_one_brief_confirmation(qtbot) -> None:
    actions: list[str] = []
    window = ScreeningWindow(on_action=actions.append)
    qtbot.addWidget(window)
    window.present_state(WorkflowState(step=ScreeningStep.ACQUIRING))
    stop = window.page_widget(PageId.ACQUIRING).findChild(
        QPushButton,
        "STOP_SCREENING",
    )

    qtbot.mouseClick(stop, Qt.MouseButton.LeftButton)

    assert actions == []
    overlay = window.page_widget(PageId.ACQUIRING).findChild(
        QWidget,
        "stopConfirmationOverlay",
    )
    assert not overlay.isHidden()
    confirm = overlay.findChild(QPushButton, "CONFIRM_STOP_SCREENING")
    qtbot.mouseClick(confirm, Qt.MouseButton.LeftButton)
    assert actions == ["STOP_SCREENING"]


def test_valid_result_shows_report_and_next_but_invalid_result_only_shows_retry(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    result_page = window.page_widget(PageId.RESULT)
    report = result_page.findChild(QPushButton, "VIEW_BASIC_REPORT")
    next_subject = result_page.findChild(QPushButton, "START_NEXT_SCREENING")
    retry = result_page.findChild(QPushButton, "RETRY_SCREENING")

    window.present_state(
        WorkflowState(
            step=ScreeningStep.BASIC_REPORT,
            validity=SessionValidity.VALID,
            report_status=ReportStatus.BASIC_READY,
            report_id="report-1",
            report_version=1,
        )
    )

    assert report.isVisibleTo(result_page)
    assert next_subject.isVisibleTo(result_page)
    assert not retry.isVisibleTo(result_page)

    window.present_state(
        WorkflowState(
            step=ScreeningStep.RETRY_REQUIRED,
            validity=SessionValidity.INVALID,
        )
    )
    assert not report.isVisibleTo(result_page)
    assert not next_subject.isVisibleTo(result_page)
    assert retry.isVisibleTo(result_page)
