from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QLabel

from client.app import ui_integration
from client.app.heatmap import HeatmapWidget
from client.app.pages import PageId
from client.local_analysis.display import (
    DisplayRefreshController,
    LatestDisplayFrameMailbox,
    build_display_frame,
)
from client.local_analysis.service import ProcessingOutcome, ProcessingStatus
from client.reporting.models import (
    BasicReportDocument,
    ReportMetric,
    ReportStage,
    ReportStatus,
)
from client.workflow.models import (
    PreflightCheck,
    PreflightSummary,
    QualityOutcome,
    ReportStatus as WorkflowReportStatus,
    WorkflowState,
)
from client.workflow.state_machine import ScreeningStep


def test_ui_integration_module_is_available_for_the_real_composition_root() -> None:
    assert find_spec("client.app.ui_integration") is not None


def _report() -> BasicReportDocument:
    stage_heatmap = tuple(
        tuple(
            1.0 if (row, column) in {(20, 10), (20, 53)} else 0.0
            for column in range(64)
        )
        for row in range(48)
    )
    return BasicReportDocument(
        report_id="report-ui-1",
        version=2,
        status=ReportStatus.BASIC_READY,
        kind="BASIC",
        session_id="session-ui-1",
        analysis_result_id="analysis-ui-1",
        subject_display_id="受试者 **8842",
        captured_at=datetime(2026, 7, 21, 9, 30, tzinfo=UTC),
        generated_at=datetime(2026, 7, 21, 9, 31, tzinfo=UTC),
        protocol_id="standard-static-bilateral",
        protocol_version="1.0.0-pilot",
        metrics=(
            ReportMetric(
                "left_load_percent",
                "左侧相对负重",
                51.0,
                "percent",
                "1.0.0",
            ),
            ReportMetric(
                "right_load_percent",
                "右侧相对负重",
                49.0,
                "percent",
                "1.0.0",
            ),
        ),
        relative_heatmap=((0.0, 1.0),),
        summary="基础相对压力分布已生成。",
        disclaimer="本报告用于健康筛查与风险提示，不作疾病诊断。",
        provenance=("local-basic/1.0.0", "report-schema/2.0.0"),
        stages=tuple(
            ReportStage(
                stage_id=stage_id,
                title=title,
                relative_heatmap=stage_heatmap,
                metrics=(
                    ReportMetric(
                        "cop_path_mm",
                        "COP 路径长度",
                        float(index + 1),
                        "mm",
                        "2.0.0",
                    ),
                ),
            )
            for index, (stage_id, title) in enumerate(
                (
                    ("BILATERAL_EYES_OPEN", "第一段：并足睁眼"),
                    ("BILATERAL_EYES_CLOSED", "第二段：并足闭眼"),
                    ("SEMI_TANDEM_LEFT_FORWARD", "第三段：左脚在前半串联"),
                    ("SEMI_TANDEM_RIGHT_FORWARD", "第四段：右脚在前半串联"),
                )
            )
        ),
    )


class _Processor:
    def __init__(self, report: BasicReportDocument | None) -> None:
        self.report = report
        self.calls: list[str] = []

    def process(self, session_id: str) -> ProcessingOutcome:
        self.calls.append(session_id)
        return ProcessingOutcome(
            ProcessingStatus.BASIC_READY
            if self.report is not None
            else ProcessingStatus.RETRY_REQUIRED,
            None,
            self.report,
        )


class _Delivery:
    def __init__(self) -> None:
        self.exports: list[tuple[BasicReportDocument, Path]] = []
        self.prints: list[tuple[BasicReportDocument, object]] = []

    def export_pdf(self, report: BasicReportDocument, destination: Path) -> None:
        self.exports.append((report, destination))

    def print_report(self, report: BasicReportDocument, *, spooler: object) -> None:
        self.prints.append((report, spooler))


class _PersistedReports:
    def __init__(self, report: BasicReportDocument) -> None:
        self.report = report
        self.lookups: list[tuple[str, int]] = []

    def load_report(self, report_id: str, version: int) -> str:
        self.lookups.append((report_id, version))
        if (report_id, version) != (self.report.report_id, self.report.version):
            raise KeyError(report_id)
        return self.report.to_json()


class _InconsistentProcessor:
    def process(self, session_id: str) -> ProcessingOutcome:
        _ = session_id
        return ProcessingOutcome(ProcessingStatus.BASIC_READY, None, None)


class _InvalidProcessorWithReport:
    def process(self, session_id: str) -> ProcessingOutcome:
        _ = session_id
        return ProcessingOutcome(ProcessingStatus.RETRY_REQUIRED, None, _report())


def test_local_report_adapter_pins_one_document_for_analysis_preview_export_and_print() -> None:
    adapter_type = getattr(ui_integration, "LocalReportWorkflowAdapter", None)
    assert adapter_type is not None
    report = _report()
    processor = _Processor(report)
    delivery = _Delivery()
    spooler = object()
    adapter = adapter_type(processor=processor, delivery=delivery, spooler=spooler)

    quality = adapter.analyze("session-ui-1")
    reference = adapter.create_basic_report("session-ui-1")
    selected = adapter.report_document(*reference)
    destination = Path("/tmp/report-ui-1-v2.pdf")
    adapter.export_pdf(*reference, destination)
    adapter.print_report(*reference)

    assert quality.outcome is QualityOutcome.VALID
    assert reference == ("report-ui-1", 2)
    assert selected is report
    assert processor.calls == ["session-ui-1"]
    assert delivery.exports == [(report, destination)]
    assert delivery.prints == [(report, spooler)]


def test_local_report_adapter_reloads_the_exact_persisted_report_version() -> None:
    adapter_type = getattr(ui_integration, "LocalReportWorkflowAdapter", None)
    assert adapter_type is not None
    report = _report()
    persisted = _PersistedReports(report)
    adapter = adapter_type(
        processor=_Processor(None),
        delivery=_Delivery(),
        spooler=object(),
        persisted_reports=persisted,
    )

    restored = adapter.report_document(report.report_id, report.version)

    assert restored == report
    assert persisted.lookups == [(report.report_id, report.version)]


def test_basic_ready_without_a_versioned_document_is_rejected() -> None:
    adapter_type = getattr(ui_integration, "LocalReportWorkflowAdapter", None)
    assert adapter_type is not None
    adapter = adapter_type(
        processor=_InconsistentProcessor(),
        delivery=_Delivery(),
        spooler=object(),
    )

    with pytest.raises(RuntimeError, match="requires a report document"):
        adapter.analyze("session-ui-1")


def test_retry_required_outcome_cannot_expose_a_customer_report() -> None:
    adapter_type = getattr(ui_integration, "LocalReportWorkflowAdapter", None)
    assert adapter_type is not None
    adapter = adapter_type(
        processor=_InvalidProcessorWithReport(),
        delivery=_Delivery(),
        spooler=object(),
    )

    with pytest.raises(RuntimeError, match="cannot carry a report document"):
        adapter.analyze("session-ui-1")


class _ReportCoordinator:
    def __init__(self) -> None:
        self._state = WorkflowState(
            step=ScreeningStep.BASIC_REPORT,
            report_status=WorkflowReportStatus.BASIC_READY,
            report_id="report-ui-1",
            report_version=2,
        )

    @property
    def state(self) -> WorkflowState:
        return self._state


def test_connected_controller_loads_the_exact_report_document_into_p10(qtbot) -> None:
    controller_type = getattr(ui_integration, "ReportConnectedController", None)
    adapter_type = getattr(ui_integration, "LocalReportWorkflowAdapter", None)
    assert controller_type is not None
    assert adapter_type is not None
    report = _report()
    reports = adapter_type(
        processor=_Processor(report),
        delivery=_Delivery(),
        spooler=object(),
    )
    reports.analyze("session-ui-1")
    controller = controller_type(_ReportCoordinator(), report_documents=reports)
    qtbot.addWidget(controller.window)

    controller.dispatch("VIEW_BASIC_REPORT")

    page = controller.window.page_widget(PageId.REPORT_PREVIEW)
    assert controller.window.current_page_id is PageId.REPORT_PREVIEW
    report_page = controller.window.page_widget(PageId.REPORT_PREVIEW)
    stage_maps = [
        report_page.findChild(HeatmapWidget, f"reportStageHeatmap{index}")
        for index in range(4)
    ]
    assert all(stage_map is not None for stage_map in stage_maps)
    assert all(stage_map.display_frame is not None for stage_map in stage_maps)
    parameters = page.findChild(QLabel, "reportParameters").text()
    assert "第一段：并足睁眼" in parameters
    assert "COP 路径 1.0mm" in parameters
    assert page.findChild(QLabel, "reportPreviewSummary").text() == report.summary
    assert page.findChild(QLabel, "reportPreviewTitle").text() == "基础筛查报告"
    assert "v2" in page.findChild(QLabel, "reportVersionPillText").text()
    footer = page.findChild(QLabel, "reportPreviewFooter").text()
    assert "v2" in footer
    assert "完整 v2" not in footer


def test_connected_controller_opens_an_explicit_historic_report_reference(qtbot) -> None:
    controller_type = getattr(ui_integration, "ReportConnectedController", None)
    adapter_type = getattr(ui_integration, "LocalReportWorkflowAdapter", None)
    assert controller_type is not None
    report = _report()
    reports = adapter_type(
        processor=_Processor(report),
        delivery=_Delivery(),
        spooler=object(),
    )
    reports.analyze("session-ui-1")
    controller = controller_type(_ReportCoordinator(), report_documents=reports)
    qtbot.addWidget(controller.window)

    controller.dispatch(f"OPEN_REPORT:{report.report_id}:{report.version}")

    assert controller.window.current_page_id is PageId.REPORT_PREVIEW
    assert "报告编号 report-ui-1" in controller.window.page_widget(
        PageId.REPORT_PREVIEW
    ).findChild(QLabel, "reportPreviewFooter").text()


def test_historic_selection_pins_export_to_that_report_version(qtbot, tmp_path: Path) -> None:
    controller_type = getattr(ui_integration, "ReportConnectedController", None)
    adapter_type = getattr(ui_integration, "LocalReportWorkflowAdapter", None)
    current = _report()
    historic = replace(current, report_id="historic-42", version=7)
    delivery = _Delivery()
    reports = adapter_type(processor=_Processor(current), delivery=delivery, spooler=object())
    reports.analyze(current.session_id)
    reports._documents[(historic.report_id, historic.version)] = historic
    controller = controller_type(
        _ReportCoordinator(),
        report_documents=reports,
        export_destination=lambda: tmp_path / "historic.pdf",
    )
    qtbot.addWidget(controller.window)

    controller.dispatch("OPEN_REPORT:historic-42:7")
    controller.dispatch("EXPORT_PDF")

    assert delivery.exports == [(historic, tmp_path / "historic.pdf")]


class _Preflight:
    def run_preflight(self) -> PreflightSummary:
        return PreflightSummary((PreflightCheck("generic", True),))


class _Sessions:
    def __init__(self) -> None:
        self.finalized: list[str] = []

    def create_session(self, context, protocol) -> str:
        _ = context, protocol
        return "session-ui-1"

    def mark_incomplete(self, session_id: str) -> None:
        _ = session_id

    def finalize(self, session_id: str) -> None:
        self.finalized.append(session_id)


class _Acquisition:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start(self, session_id: str) -> None:
        self.started.append(session_id)

    def stop(self, session_id: str) -> None:
        _ = session_id


class _Telemetry:
    def record_error(self, **event) -> None:
        raise AssertionError(f"unexpected integration error: {event}")


def test_connected_composition_runs_ui_to_local_report_heatmap_export_and_print(
    qtbot,
    tmp_path: Path,
) -> None:
    builder = getattr(ui_integration, "build_connected_ui", None)
    assert builder is not None
    report = _report()
    processor = _Processor(report)
    delivery = _Delivery()
    spooler = object()
    sessions = _Sessions()
    acquisition = _Acquisition()
    mailbox = LatestDisplayFrameMailbox()
    destination = tmp_path / "report-ui-1-v2.pdf"
    runtime = builder(
        preflight=_Preflight(),
        sessions=sessions,
        acquisition=acquisition,
        processor=processor,
        delivery=delivery,
        spooler=spooler,
        telemetry=_Telemetry(),
        display_refresh=DisplayRefreshController(
            mailbox,
            maximum_refresh_hz=30.0,
        ),
        export_destination=lambda: destination,
    )
    controller = runtime.controller
    qtbot.addWidget(controller.window)
    runtime.coordinator.bind_participant(
        subject_uuid="subject-ui-1",
        consent_record_id="consent-ui-1",
    )

    controller.dispatch("START_NEW_SCREENING")
    controller.dispatch("CONFIRM_SUBJECT")
    controller.dispatch("SKIP_PROFILE")
    controller.dispatch("CONFIRM_CONSENT")
    qtbot.waitUntil(
        lambda: runtime.coordinator.state.preflight_ready
    )
    assert controller.window.current_page_id is PageId.PREFLIGHT
    controller.dispatch("ENTER_POSITION")
    assert controller.window.current_page_id is PageId.POSITION_GUIDANCE
    controller.on_position_observation(
        now_seconds=0.0,
        contact_ready=True,
        in_valid_area=True,
    )
    controller.on_position_observation(
        now_seconds=3.0,
        contact_ready=True,
        in_valid_area=True,
    )
    assert controller.window.current_page_id is PageId.POSITION_GUIDANCE
    controller.dispatch("START_ACQUISITION")
    assert controller.window.current_page_id is PageId.ACQUIRING

    counts = np.zeros((48, 64), dtype=np.float64)
    counts[20, 10] = 1_000.0
    counts[20, 53] = 1_000.0
    mailbox.publish(
        build_display_frame(
            counts,
            sequence=7,
            captured_monotonic_seconds=1.0,
            cop_trail=(),
            total_trend=(),
        )
    )
    assert controller.on_display_tick(1.0)
    assert "左 50.0%" in controller.window.page_widget(
        PageId.ACQUIRING
    ).findChild(QLabel, "loadSummary").text()

    controller.on_acquisition_completed()
    assert controller.window.current_page_id is PageId.RESULT
    controller.dispatch("VIEW_BASIC_REPORT")
    controller.dispatch("EXPORT_PDF")
    controller.dispatch("PRINT_REPORT")

    assert sessions.finalized == ["session-ui-1"]
    assert acquisition.started == ["session-ui-1"]
    assert processor.calls == ["session-ui-1"]
    assert delivery.exports == [(report, destination)]
    assert delivery.prints == [(report, spooler)]
    assert controller.window.current_page_id is PageId.REPORT_PREVIEW
