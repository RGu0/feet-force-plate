from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from client.app.design_system import apply_design_system
from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.reporting.models import BasicReportDocument, ReportMetric, ReportStatus as ReportDocumentStatus


def test_design_system_marks_primary_actions_and_preserves_target_size(qtbot) -> None:
    window = QWidget()
    primary = QPushButton("开始新的检测", window)
    primary.setProperty("importance", "primary")
    qtbot.addWidget(window)

    apply_design_system(window)

    assert window.property("uiTheme") == "steady-health"
    assert "#2569BC" in window.styleSheet()
    assert primary.minimumHeight() >= 44


def test_workbench_has_source_topbar_statuses_and_central_primary_action(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    assert window.findChild(QWidget, "appHeader") is not None
    assert window.findChild(QLabel, "organizationName").text()
    assert window.findChild(QWidget, "deviceStatusBadge") is not None
    assert window.findChild(QWidget, "syncStatusBadge") is not None
    assert "QFrame#appHeader" in window.styleSheet()
    assert window.findChild(QWidget, "appNavigation") is not None
    assert window.findChild(QPushButton, "navP-01") is not None
    assert not window.findChild(QWidget, "appHeader").isHidden()

    workbench = window.page_widget(PageId.WORKBENCH)
    primary = workbench.findChild(QPushButton, "START_NEW_SCREENING")
    assert primary.property("importance") == "primary"
    assert primary.minimumHeight() >= 64


def test_guidance_and_acquisition_pages_use_dedicated_operator_layouts(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    guidance = window.page_widget(PageId.POSITION_GUIDANCE)
    acquisition = window.page_widget(PageId.ACQUIRING)

    assert guidance.findChild(QWidget, "footPlacementGuide") is not None
    assert guidance.findChild(QLabel, "countdownLabel") is not None
    assert acquisition.findChild(QWidget, "acquisitionContent") is not None


def test_wizard_and_focus_pages_follow_the_source_screen_structure(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    subject = window.page_widget(PageId.SUBJECT_IDENTIFICATION)
    profile = window.page_widget(PageId.PROFILE)
    preflight = window.page_widget(PageId.PREFLIGHT)
    result = window.page_widget(PageId.RESULT)
    report = window.page_widget(PageId.REPORT_PREVIEW)

    assert subject.findChild(QWidget, "wizardStepBar") is not None
    assert profile.findChild(QPushButton, "SAVE_PROFILE") is not None
    assert preflight.findChild(QWidget, "checklistCard") is not None
    assert result.findChild(QWidget, "resultCard") is not None
    assert report.findChild(QWidget, "reportPaper") is not None


def test_report_preview_presents_the_selected_report_version(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    document = BasicReportDocument(
        report_id="report-1",
        version=2,
        status=ReportDocumentStatus.BASIC_READY,
        kind="basic",
        session_id="session-1",
        analysis_result_id="analysis-1",
        subject_display_id="**2781",
        captured_at=datetime(2026, 7, 21, 10, 30),
        generated_at=datetime(2026, 7, 21, 10, 31),
        protocol_id="standard-static-bilateral",
        protocol_version="1.0.0-pilot",
        metrics=(ReportMetric("left", "左侧相对负重", 51.2, "percent", "1"),),
        relative_heatmap=((0.0, 1.0),),
        summary="本次筛查已完成基础分析。",
        disclaimer="本报告不提供临床诊断。",
        provenance=("demo",),
    )

    window.present_report_document(document)

    page = window.page_widget(PageId.REPORT_PREVIEW)
    assert page.findChild(QLabel, "reportPreviewTitle").text() == "基础筛查报告"
    assert "v2" in page.findChild(QLabel, "reportVersionPillText").text()
    assert "本次筛查已完成" in page.findChild(QLabel, "reportPreviewSummary").text()
    assert page.findChild(QLabel, "reportAttentionText").text() == "基础分析完成"
    assert page.findChild(QLabel, "reportRetestText").text() == "不输出风险结论"
    assert "未经批准" in page.findChild(QLabel, "reportParameters").text()


def test_subject_and_consent_pages_group_operator_decisions_visually(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    subject = window.page_widget(PageId.SUBJECT_IDENTIFICATION)
    consent = window.page_widget(PageId.CONSENT)

    assert subject.findChild(QWidget, "subjectLookupRow") is not None
    assert "数据会加密上传" in consent.findChild(QLabel, "consentIntro").text()


def test_preflight_result_and_support_statuses_have_named_read_models(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    for page_id, label_name in (
        (PageId.PREFLIGHT, "deviceCheck"),
        (PageId.RESULT, "basicReportStatusText"),
        (PageId.SUPPORT, "deviceHealth"),
    ):
        label = window.page_widget(page_id).findChild(QLabel, label_name)
        assert label is not None
        assert label.accessibleName() or label.text()
