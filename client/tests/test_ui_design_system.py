from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from client.app.design_system import (
    STEADY_HEALTH_STYLESHEET,
    apply_design_system,
    bundled_font_paths,
)
from client.app.pages import PageId
from client.app.institution_access import InstitutionAccessWindow
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


def test_design_system_ships_the_fonts_required_by_the_ui_tokens() -> None:
    """The desktop build must not depend on fonts being preinstalled on Windows."""

    ui_font, numeric_font = bundled_font_paths()

    assert ui_font.is_file()
    assert numeric_font.is_file()
    assert ui_font.parent.name == "fonts"
    assert numeric_font.parent.name == "fonts"


def test_design_system_does_not_declare_a_system_font_fallback() -> None:
    """A fallback would make an installed client visually depend on its host OS."""

    assert 'font-family: "Noto Sans SC";' in STEADY_HEALTH_STYLESHEET
    assert "Microsoft YaHei UI" not in STEADY_HEALTH_STYLESHEET


def test_design_system_uses_the_bundled_family_for_ui_and_numeric_content(qtbot) -> None:
    """Qt must not fall back to the target computer's default Windows font."""

    window = QWidget()
    metric = QLabel("51.2%", window)
    metric.setProperty("numericText", True)
    qtbot.addWidget(window)

    apply_design_system(window)

    assert window.font().family() == "Noto Sans SC"
    assert metric.font().family() == "Noto Sans SC"
    metrics = QFontMetrics(metric.font())
    assert len({metrics.horizontalAdvance(digit) for digit in "0123456789"}) == 1


def test_screening_metric_labels_are_marked_for_the_numeric_font(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)

    for object_name in ("countdownLabel", "remainingTime", "remainingSeconds"):
        label = window.findChild(QLabel, object_name)
        assert label is not None
        assert label.property("numericText") is True


def test_institution_title_applies_the_design_weight_to_the_variable_font(qtbot) -> None:
    window = InstitutionAccessWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(0)

    title = window.findChild(QLabel, "accessTitle")
    weight_axis = QFont.Tag.fromString("wght")

    assert title is not None
    assert title.font().weight() == QFont.Weight.DemiBold
    assert title.font().pixelSize() == 32
    assert title.font().isVariableAxisSet(weight_axis)
    assert title.font().variableAxisValue(weight_axis) == 600.0


def test_countdown_keeps_its_design_weight_when_using_the_numeric_font(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(0)

    countdown = window.findChild(QLabel, "countdownLabel")
    weight_axis = QFont.Tag.fromString("wght")

    assert countdown is not None
    assert countdown.font().weight() == QFont.Weight.Bold
    assert countdown.font().isVariableAxisSet(weight_axis)
    assert countdown.font().variableAxisValue(weight_axis) == 700.0


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

    assert guidance.findChild(QWidget, "stageGuidance") is not None
    assert guidance.findChild(QLabel, "stageBodyGuide") is not None
    assert guidance.findChild(QLabel, "stageFeetGuide") is not None
    assert guidance.findChild(QLabel, "countdownLabel") is not None
    assert acquisition.findChild(QWidget, "acquisitionContent") is not None


def test_guidance_title_and_subtitle_inherit_design_tokens(qtbot) -> None:
    window = ScreeningWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    guidance = window.page_widget(PageId.POSITION_GUIDANCE)
    title = guidance.findChild(QLabel, "positionGuideTitle")
    subtitle = guidance.findChild(QLabel, "positionGuideSubtitle")

    assert title.font().weight() == QFont.Weight.DemiBold
    assert subtitle.font().pixelSize() == 16
    assert subtitle.palette().color(subtitle.foregroundRole()) == QColor("#475569")


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
