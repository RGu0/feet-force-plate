from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from .models import BasicReportDocument
from .pdf import BasicReportPdfRenderer


class PrintSpoolPort(Protocol):
    def print_pdf(self, pdf_path: Path, *, job_name: str) -> None: ...


@dataclass(frozen=True, slots=True)
class PrintConfirmation:
    report_id: str
    version: int
    subject_display_id: str
    captured_at: datetime


class ReportDeliveryService:
    def __init__(self, renderer: BasicReportPdfRenderer) -> None:
        self._renderer = renderer

    def export_pdf(
        self,
        report: BasicReportDocument,
        destination: Path,
    ) -> None:
        if destination.suffix.lower() != ".pdf":
            raise ValueError("PDF export destination must end with .pdf")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(f"{destination.name}.partial")
        try:
            self._renderer.render(report, partial)
            partial.replace(destination)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    def print_report(
        self,
        report: BasicReportDocument,
        *,
        spooler: PrintSpoolPort,
    ) -> PrintConfirmation:
        confirmation = PrintConfirmation(
            report_id=report.report_id,
            version=report.version,
            subject_display_id=report.subject_display_id,
            captured_at=report.captured_at,
        )
        with TemporaryDirectory(prefix="feetforceplate-print-") as directory:
            pdf_path = Path(directory) / (
                f"{report.report_id}-v{report.version}.pdf"
            )
            self._renderer.render(report, pdf_path)
            spooler.print_pdf(
                pdf_path,
                job_name=f"FeetForcePlate {report.report_id} v{report.version}",
            )
        return confirmation
