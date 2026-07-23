from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QTableWidget

from client.app.qt_shell import ScreeningWindow
from client.app.pages import PageId
from client.app.ui_models import DashboardSnapshot, ScreeningRecordRow, SupportSnapshot


def test_dashboard_snapshot_populates_operator_summary_and_recent_records(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    snapshot = DashboardSnapshot(
        organization_name="安康体检中心 · A 区",
        device_status="设备已就绪",
        sync_status="数据已同步",
        pending_summary="待同步数据：0 次",
        recent_records=(
            ScreeningRecordRow("**2781", "07-21 10:20", "静态筛查", "完整报告"),
        ),
    )

    window.present_dashboard(snapshot)

    assert "安康体检中心" in window.findChild(QLabel, "organizationName").text()
    records = window.page_widget(PageId.WORKBENCH).findChild(
        QTableWidget,
        "recentScreenings",
    )
    assert records.rowCount() == 1
    assert records.item(0, 0).text() == "**2781"


def test_read_models_populate_record_history_and_support_summary(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    records = (
        ScreeningRecordRow("**2781", "07-21 10:20", "静态筛查", "完整报告"),
    )

    window.present_records(records)
    window.present_support(
        SupportSnapshot("已连接", "正常", "待同步数据：0 次", "1.0.0-demo")
    )

    records_page = window.page_widget(PageId.RECORDS)
    records_table = records_page.findChild(QTableWidget, "recordsTable")
    assert records_table.rowCount() == 1
    assert records_table.cellWidget(0, 3).accessibleName() == "完整报告"
    support_page = window.page_widget(PageId.SUPPORT)
    assert support_page.findChild(QLabel, "appVersion").text() == "1.0.0-demo"


def test_record_history_filters_by_identifier_and_report_status(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.present_records(
        (
            ScreeningRecordRow("**2781", "07-21 10:20", "静态筛查", "完整报告"),
            ScreeningRecordRow("临时034", "07-21 10:05", "静态筛查", "基础报告"),
        )
    )
    page = window.page_widget(PageId.RECORDS)
    search = page.findChild(QLineEdit, "recordSearchInput")
    status = page.findChild(QComboBox, "recordStatusFilter")
    table = page.findChild(QTableWidget, "recordsTable")

    search.setText("临时")
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "临时034"

    search.clear()
    status.setCurrentIndex(status.findData("完整报告"))
    assert table.rowCount() == 1
    assert table.cellWidget(0, 3).accessibleName() == "完整报告"


def test_record_history_filters_by_actual_performed_date(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.present_records(
        (
            ScreeningRecordRow(
                "**2781",
                "今天 10:20",
                "静态筛查",
                "完整报告",
                performed_on=date.today(),
            ),
            ScreeningRecordRow(
                "**1052",
                "昨天 09:42",
                "静态筛查",
                "基础报告",
                performed_on=date.today() - timedelta(days=1),
            ),
        )
    )
    page = window.page_widget(PageId.RECORDS)
    date_filter = page.findChild(QComboBox, "recordDateFilter")
    table = page.findChild(QTableWidget, "recordsTable")

    date_filter.setCurrentIndex(date_filter.findData("today"))

    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "**2781"
