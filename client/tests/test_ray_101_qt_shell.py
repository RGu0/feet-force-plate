from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QLabel, QPushButton, QTableWidget, QWidget

from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.workflow.models import (
    ClientAction,
    ClientError,
    ReportStatus,
    SessionValidity,
    WorkflowState,
)
from client.workflow.state_machine import ScreeningStep


def test_shell_builds_all_prd_pages_with_accessible_action_targets(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    assert window.page_count == 11
    for page_id in PageId:
        page = window.page_widget(page_id)
        assert page.objectName() == page_id.value
        for button in page.findChildren(QPushButton):
            expected_height = 40 if button.property("profileChip") else 48
            assert button.minimumHeight() >= expected_height
            assert button.accessibleName()

    for table in window.findChildren(QTableWidget):
        assert table.selectionMode() is QAbstractItemView.SelectionMode.NoSelection


def test_acquiring_state_locks_navigation_and_shows_only_safe_error(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    state = WorkflowState(
        step=ScreeningStep.ACQUIRING,
        session_id="session-1",
        error=ClientError(
            code="E-DEV-002",
            operator_message="压力设备连接已中断，本次检测未完成",
            action=ClientAction.RETRY_SCREENING,
        ),
    )

    window.present_state(state)

    assert window.current_page_id == PageId.ACQUIRING
    assert not window.global_navigation_enabled
    assert "E-DEV-002" in window.error_text
    assert "压力设备连接已中断" in window.error_text
    assert "SerialException" not in window.error_text


def test_each_page_exposes_the_required_operator_controls(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    required_controls = {
        PageId.WORKBENCH: {
            "recentScreenings",
        },
        PageId.SUBJECT_IDENTIFICATION: {
            "subjectExternalIdInput",
            "lookupSubjectButton",
            "subjectMatchSummary",
        },
        PageId.PROFILE: {
            "ageBandInput",
            "sexInput",
            "heightInput",
            "weightInput",
        },
        PageId.CONSENT: {"requiredConsent", "researchConsent", "policyLink"},
        PageId.PREFLIGHT: {
            "deviceCheck",
            "storageCheck",
                "calibrationCheck",
                "syncCheck",
        },
        PageId.POSITION_GUIDANCE: {"positionStatus", "countdownLabel"},
        PageId.ACQUIRING: {
            "heatmapHost",
            "remainingTime",
            "acquisitionStatus",
            "STOP_SCREENING",
        },
        PageId.RESULT: {"basicReportStatus", "fullReportStatus"},
        PageId.RECORDS: {"recordSearchInput", "recordsTable"},
            PageId.REPORT_PREVIEW: {"reportPaper", "EXPORT_PDF", "PRINT_REPORT"},
        PageId.SUPPORT: {
            "deviceHealth",
            "syncHealth",
            "pendingCount",
            "appVersion",
        },
    }

    for page_id, object_names in required_controls.items():
        page = window.page_widget(page_id)
        for object_name in object_names:
            assert page.findChild(QWidget, object_name) is not None, (
                page_id,
                object_name,
            )


def test_subject_match_card_wraps_detail_without_obscuring_primary_action(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.set_subject_match_summary(
        "已找到唯一档案：编号 **2781 · 年龄 64 岁 · 性别 女 · 上次检测 07-12"
    )
    window.show_page(PageId.SUBJECT_IDENTIFICATION)
    window.resize(1280, 900)
    window.show()
    qtbot.waitUntil(lambda: window.isVisible())

    page = window.page_widget(PageId.SUBJECT_IDENTIFICATION)
    subject_id = page.findChild(QLabel, "subjectMatchId")
    detail = page.findChild(QLabel, "subjectMatchSummary")
    confirm = page.findChild(QPushButton, "CONFIRM_SUBJECT")

    assert detail.wordWrap()
    assert "年龄 64 岁" in detail.text()
    assert subject_id.font().pixelSize() == 20
    assert subject_id.font().weight() == QFont.Weight.DemiBold
    assert detail.font().pixelSize() == 16
    assert detail.font().weight() == QFont.Weight.Normal
    assert confirm.width() == 140
    assert detail.mapToGlobal(detail.rect().topRight()).x() < confirm.mapToGlobal(confirm.rect().topLeft()).x()


def test_nonblocking_sync_notice_keeps_basic_report_available(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.present_state(
        WorkflowState(
            step=ScreeningStep.BASIC_REPORT,
            notice="基础报告已生成。网络恢复后系统会自动完成完整分析。",
        )
    )

    assert window.current_page_id == PageId.RESULT
    assert window.global_navigation_enabled
    assert "基础报告已生成" in window.notice_text
    assert window.error_text == ""


def test_report_generation_failure_replaces_processing_result_state(qtbot) -> None:
    """A valid session without a report must not remain visibly processing."""

    window = ScreeningWindow()
    qtbot.addWidget(window)
    state = WorkflowState(
        step=ScreeningStep.FAILED,
        session_id="session-1",
        validity=SessionValidity.VALID,
        report_status=ReportStatus.BASIC_READY,
        error=ClientError(
            code="E-RPT-001",
            operator_message="暂时无法生成基础报告，请联系技术支持",
            action=ClientAction.CONTACT_SUPPORT,
        ),
    )

    window.present_state(state)

    page = window.page_widget(PageId.RESULT)
    assert page.findChild(QLabel, "resultTitle").text() == "基础报告暂不可用"
    assert "暂时无法生成基础报告" in page.findChild(QLabel, "resultSummary").text()
    assert page.findChild(QLabel, "basicReportStatusText").text() == "基础报告未生成"
    assert "处理中" not in page.findChild(QLabel, "resultTitle").text()
    assert "处理中" not in page.findChild(QLabel, "resultSummary").text()
    assert not page.findChild(QPushButton, "RETURN_WORKBENCH").isHidden()
    assert page.findChild(QPushButton, "VIEW_BASIC_REPORT").isHidden()
    assert page.findChild(QPushButton, "START_NEXT_SCREENING").isHidden()
    assert page.findChild(QPushButton, "RETRY_SCREENING").isHidden()


def test_incomplete_screen_return_dispatches_the_same_workbench_reset_action(qtbot) -> None:
    actions: list[str] = []
    window = ScreeningWindow(on_action=actions.append)
    qtbot.addWidget(window)
    window.present_state(WorkflowState(step=ScreeningStep.INCOMPLETE))

    qtbot.mouseClick(
        window.page_widget(PageId.RESULT).findChild(
            QPushButton, "RETURN_WORKBENCH"
        ),
        Qt.MouseButton.LeftButton,
    )

    assert actions == ["RETURN_TO_WORKBENCH"]
