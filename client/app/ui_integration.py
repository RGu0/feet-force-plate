"""Port-based connections between the application workflow and Qt presentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from client.local_analysis.display import DisplayRefreshController
from client.local_analysis.service import ProcessingOutcome, ProcessingStatus
from client.reporting.models import BasicReportDocument
from client.workflow.coordinator import ScreeningCoordinator
from client.workflow.models import QualityOutcome, QualityResult
from client.workflow.ports import (
    AcquisitionPort,
    PreflightPort,
    SessionPort,
    TelemetryPort,
)
from client.workflow.protocol import ScreeningProtocol

from .controller import ApplicationController
from .live_display import LiveDisplayProjection
from .pages import PageId


class LocalAnalysisProcessorPort(Protocol):
    def process(self, session_id: str) -> ProcessingOutcome: ...


class ReportDeliveryPort(Protocol):
    def export_pdf(
        self,
        report: BasicReportDocument,
        destination: Path,
    ) -> None: ...

    def print_report(
        self,
        report: BasicReportDocument,
        *,
        spooler: object,
    ) -> object: ...


class ReportDocumentPort(Protocol):
    def report_document(
        self,
        report_id: str,
        version: int,
    ) -> BasicReportDocument: ...


class PersistedReportPort(Protocol):
    def load_report(self, report_id: str, version: int) -> str: ...


class LocalReportWorkflowAdapter:
    """Expose local processing through workflow, UI, export, and print ports."""

    def __init__(
        self,
        *,
        processor: LocalAnalysisProcessorPort,
        delivery: ReportDeliveryPort,
        spooler: object,
        persisted_reports: PersistedReportPort | None = None,
    ) -> None:
        self._processor = processor
        self._delivery = delivery
        self._spooler = spooler
        self._persisted_reports = persisted_reports
        self._outcomes: dict[str, ProcessingOutcome] = {}
        self._documents: dict[tuple[str, int], BasicReportDocument] = {}

    def analyze(self, session_id: str) -> QualityResult:
        outcome = self._process_once(session_id)
        quality = (
            QualityOutcome.VALID
            if outcome.status is ProcessingStatus.BASIC_READY
            else QualityOutcome.INVALID
        )
        return QualityResult(outcome=quality)

    def create_basic_report(self, session_id: str) -> tuple[str, int]:
        outcome = self._process_once(session_id)
        if outcome.status is not ProcessingStatus.BASIC_READY or outcome.report is None:
            raise RuntimeError("local basic report is not available")
        return (outcome.report.report_id, outcome.report.version)

    def report_document(
        self,
        report_id: str,
        version: int,
    ) -> BasicReportDocument:
        try:
            return self._documents[(report_id, version)]
        except KeyError:
            pass
        if self._persisted_reports is None:
            raise LookupError("selected report version is not available")
        try:
            document = BasicReportDocument.from_json(
                self._persisted_reports.load_report(report_id, version)
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise LookupError("selected report version is not available") from exc
        if (document.report_id, document.version) != (report_id, version):
            raise LookupError("selected report version is not available")
        self._documents[(report_id, version)] = document
        return document

    def export_pdf(
        self,
        report_id: str,
        version: int,
        destination: Path,
    ) -> None:
        self._delivery.export_pdf(
            self.report_document(report_id, version),
            destination,
        )

    def print_report(self, report_id: str, version: int) -> None:
        self._delivery.print_report(
            self.report_document(report_id, version),
            spooler=self._spooler,
        )

    def _process_once(self, session_id: str) -> ProcessingOutcome:
        outcome = self._outcomes.get(session_id)
        if outcome is None:
            outcome = self._processor.process(session_id)
            self._outcomes[session_id] = outcome
        document = outcome.report
        if outcome.status is ProcessingStatus.BASIC_READY and document is None:
            raise RuntimeError("BASIC_READY requires a report document")
        if outcome.status is not ProcessingStatus.BASIC_READY and document is not None:
            raise RuntimeError(
                f"{outcome.status} cannot carry a report document"
            )
        if document is not None:
            reference = (document.report_id, document.version)
            existing = self._documents.get(reference)
            if existing is not None and existing != document:
                raise RuntimeError("report reference collision")
            self._documents[reference] = document
        return outcome


class ReportConnectedController(ApplicationController):
    """Application controller that presents the pinned workflow report in Qt."""

    def __init__(
        self,
        coordinator,
        *,
        report_documents: ReportDocumentPort,
        **controller_options,
    ) -> None:
        self._report_documents = report_documents
        self._selected_report_reference: tuple[str, int] | None = None
        super().__init__(coordinator, **controller_options)

    def dispatch(self, action: str) -> None:
        if action.startswith("OPEN_REPORT:"):
            _, report_id, raw_version = action.split(":", 2)
            try:
                self._present_report_reference(report_id, int(raw_version))
            except (ValueError, LookupError):
                self.window.show_form_error("所选报告暂不可用，请稍后重试")
            return
        if action in {"EXPORT_PDF", "PRINT_REPORT"} and self._selected_report_reference:
            report_id, version = self._selected_report_reference
            if action == "EXPORT_PDF":
                destination = self._export_destination()
                if destination is not None:
                    self._report_documents.export_pdf(report_id, version, destination)
            else:
                self._report_documents.print_report(report_id, version)
            return
        if action not in {"VIEW_BASIC_REPORT", "VIEW_SELECTED_REPORT"}:
            super().dispatch(action)
            return
        state = self._coordinator.state
        if state.report_id is None or state.report_version is None:
            self.window.show_form_error("基础报告暂不可用，请稍后重试")
            return
        self._present_report_reference(state.report_id, state.report_version)

    def _present_report_reference(self, report_id: str, version: int) -> None:
        try:
            document = self._report_documents.report_document(
                report_id,
                version,
            )
        except LookupError:
            self.window.show_form_error("基础报告暂不可用，请稍后重试")
            return
        if (document.report_id, document.version) != (report_id, version):
            self.window.show_form_error("报告版本已变化，请返回结果页重新打开")
            return
        self._selected_report_reference = (report_id, version)
        self._present_document(document)
        self.window.show_page(PageId.REPORT_PREVIEW)

    def _present_document(self, document: BasicReportDocument) -> None:
        presenter = getattr(self.window, "present_report_document", None)
        if callable(presenter):
            presenter(document)
            if document.kind.upper() == "BASIC":
                page = self.window.page_widget(PageId.REPORT_PREVIEW)
                footer = page.findChild(QLabel, "reportPreviewFooter")
                if footer is not None:
                    footer.setText(
                        f"报告编号 {document.report_id} · 基础 v{document.version} · "
                        f"生成 {document.generated_at:%Y-%m-%d %H:%M} · "
                        f"{document.disclaimer}"
                    )
            return
        page = self.window.page_widget(PageId.REPORT_PREVIEW)
        host = page.findChild(QFrame, "reportPreview")
        if host is None:
            raise RuntimeError("report preview host is missing")
        layout = host.layout()
        if layout is None:
            layout = QVBoxLayout(host)
        values = {
            "reportPreviewTitle": f"基础筛查报告 v{document.version}",
            "reportPreviewMeta": (
                f"受试者编号 {document.subject_display_id} · "
                f"测试时间 {document.captured_at:%Y-%m-%d %H:%M}"
            ),
            "reportPreviewSummary": document.summary,
            "reportPreviewMetrics": " · ".join(
                f"{metric.label} {metric.value:.1f}"
                f"{'%' if metric.unit == 'percent' else metric.unit}"
                for metric in document.metrics
            ),
            "reportPreviewFooter": (
                f"报告编号 {document.report_id} · v{document.version} · "
                f"{document.disclaimer}"
            ),
        }
        for object_name, text in values.items():
            label = host.findChild(QLabel, object_name)
            if label is None:
                label = QLabel(host)
                label.setObjectName(object_name)
                label.setWordWrap(True)
                layout.addWidget(label)
            label.setText(text)


@dataclass(frozen=True, slots=True)
class ConnectedUiRuntime:
    controller: ReportConnectedController
    coordinator: ScreeningCoordinator
    reports: LocalReportWorkflowAdapter


def build_connected_ui(
    *,
    preflight: PreflightPort,
    sessions: SessionPort,
    acquisition: AcquisitionPort,
    processor: LocalAnalysisProcessorPort,
    delivery: ReportDeliveryPort,
    spooler: object,
    telemetry: TelemetryPort,
    display_refresh: DisplayRefreshController | None = None,
    live_display: LiveDisplayProjection | None = None,
    export_destination: Callable[[], Path | None] | None = None,
    protocol: ScreeningProtocol | None = None,
    persisted_reports: PersistedReportPort | None = None,
    data_source_mode: str = "LIVE",
    controller_options: dict[str, object] | None = None,
) -> ConnectedUiRuntime:
    """Compose the UI with caller-provided device, storage, and support ports."""

    reports = LocalReportWorkflowAdapter(
        processor=processor,
        delivery=delivery,
        spooler=spooler,
        persisted_reports=persisted_reports,
    )
    coordinator = ScreeningCoordinator(
        preflight=preflight,
        sessions=sessions,
        acquisition=acquisition,
        analysis=reports,
        reports=reports,
        telemetry=telemetry,
        protocol=protocol,
        data_source_mode=data_source_mode,
    )
    options = dict(controller_options or {})
    if display_refresh is not None:
        options["display_refresh"] = display_refresh
    if live_display is not None:
        options["live_display"] = live_display
    if export_destination is not None:
        options["export_destination"] = export_destination
    controller = ReportConnectedController(
        coordinator,
        report_documents=reports,
        **options,
    )
    return ConnectedUiRuntime(
        controller=controller,
        coordinator=coordinator,
        reports=reports,
    )
