from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QLabel, QPushButton, QTableWidget, QWidget

from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.workflow.models import ClientAction, ClientError, WorkflowState
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
