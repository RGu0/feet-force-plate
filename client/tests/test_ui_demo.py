from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTableWidget

from client.app.demo import DesignDemoController
from client.app.pages import PageId


def test_design_demo_routes_the_operator_through_the_standard_flow(qtbot) -> None:
    demo = DesignDemoController()
    qtbot.addWidget(demo.window)

    demo.dispatch("START_NEW_SCREENING")
    assert demo.window.current_page_id is PageId.SUBJECT_IDENTIFICATION

    demo.dispatch("CONFIRM_SUBJECT")
    assert demo.window.current_page_id is PageId.PROFILE

    demo.dispatch("SAVE_PROFILE")
    assert demo.window.current_page_id is PageId.CONSENT

    demo.dispatch("CONFIRM_CONSENT")
    assert demo.window.current_page_id is PageId.PREFLIGHT

    demo.dispatch("RECHECK")
    assert demo.window.current_page_id is PageId.PREFLIGHT

    demo.dispatch("ENTER_POSITION")
    assert demo.window.current_page_id is PageId.POSITION_GUIDANCE

    demo.dispatch("START_ACQUISITION")
    assert demo.window.current_page_id is PageId.ACQUIRING


def test_design_demo_seeds_the_operator_dashboard(qtbot) -> None:
    demo = DesignDemoController()
    qtbot.addWidget(demo.window)

    assert "安康" in demo.window.findChild(QLabel, "organizationName").text()
    recent = demo.window.page_widget(PageId.WORKBENCH).findChild(
        QTableWidget,
        "recentScreenings",
    )
    assert recent.rowCount() == 5


def test_design_demo_opens_a_versioned_report_preview(qtbot) -> None:
    demo = DesignDemoController()
    qtbot.addWidget(demo.window)

    demo.dispatch("VIEW_BASIC_REPORT")

    page = demo.window.page_widget(PageId.REPORT_PREVIEW)
    assert page.findChild(QLabel, "reportPreviewTitle").text() == "基础筛查报告"
    assert "v1" in page.findChild(QLabel, "reportVersionPillText").text()
    assert "基础分析" in page.findChild(QLabel, "reportPreviewSummary").text()


def test_design_demo_seeds_record_history_and_support_state(qtbot) -> None:
    demo = DesignDemoController()
    qtbot.addWidget(demo.window)

    records = demo.window.page_widget(PageId.RECORDS).findChild(
        QTableWidget,
        "recordsTable",
    )
    assert records.rowCount() == 5
    support = demo.window.page_widget(PageId.SUPPORT)
    assert "1.0.0-demo" in support.findChild(QLabel, "appVersion").text()
