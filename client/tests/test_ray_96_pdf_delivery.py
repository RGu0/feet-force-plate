from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PySide6.QtPdf import QPdfDocument
from PySide6.QtGui import QColor

from client.reporting import pdf as report_pdf
from client.reporting.delivery import ReportDeliveryService
from client.reporting.models import (
    BasicReportDocument,
    ReportMetric,
    ReportStage,
    ReportStatus,
)
from client.reporting.pdf import BasicReportPdfRenderer


def _report() -> BasicReportDocument:
    heatmap = tuple(
        tuple(1.0 if (row, column) in {(20, 10), (20, 53)} else 0.0 for column in range(64))
        for row in range(48)
    )
    return BasicReportDocument(
        report_id="report-1",
        version=1,
        status=ReportStatus.BASIC_READY,
        kind="BASIC",
        session_id="session-1",
        analysis_result_id="analysis-1",
        subject_display_id="受试者 **1234",
        captured_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        generated_at=datetime(2026, 7, 20, 10, 1, tzinfo=UTC),
        protocol_id="standard-static-bilateral",
        protocol_version="1.0.0-pilot",
        metrics=(
            ReportMetric("left_load_percent", "左侧相对负重", 50.0, "percent", "1.0.0"),
            ReportMetric("right_load_percent", "右侧相对负重", 50.0, "percent", "1.0.0"),
        ),
        relative_heatmap=heatmap,
        summary="基础相对压力分布已生成。",
        disclaimer="本报告用于健康筛查与风险提示，不作疾病诊断。",
        provenance=("local-basic/1.0.0", "report-schema/2.0.0"),
        stages=tuple(
            ReportStage(
                stage_id=stage_id,
                title=title,
                relative_heatmap=heatmap,
                metrics=(
                    ReportMetric(
                        "cop_path_mm",
                        "COP 路径长度",
                        float(index + 1),
                        "mm",
                        "2.0.0",
                    ),
                    ReportMetric(
                        "cop_ml_range_90_mm",
                        "COP ML 90% 范围",
                        float(index + 2),
                        "mm",
                        "2.0.0",
                    ),
                    ReportMetric(
                        "cop_ap_range_90_mm",
                        "COP AP 90% 范围",
                        float(index + 3),
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


def test_a4_pdf_renderer_creates_readable_versioned_pdf(qtbot, tmp_path: Path) -> None:
    _ = qtbot
    destination = tmp_path / "report-1-v1.pdf"

    BasicReportPdfRenderer().render(_report(), destination)

    assert destination.read_bytes().startswith(b"%PDF")
    document = QPdfDocument()
    assert document.load(str(destination)) is QPdfDocument.Error.None_
    assert document.pageCount() == 3
    assert destination.stat().st_size > 5_000


def test_report_heatmap_uses_ui_noise_cleanup_and_black_zero_background() -> None:
    builder = getattr(report_pdf, "build_stage_heatmap_image", None)
    assert callable(builder)
    values = np.zeros((48, 64), dtype=np.float64)
    values[20:25, 26:31] = 0.7
    values[5, 5] = 1.0

    image = builder(tuple(tuple(float(value) for value in row) for row in values))

    assert image.pixelColor(0, 0) == QColor("#000000")
    assert image.pixelColor(5, 5) == QColor("#000000")
    assert image.pixelColor(28, 22) != QColor("#000000")


class _Spooler:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, str, bytes]] = []

    def print_pdf(self, pdf_path: Path, *, job_name: str) -> None:
        self.jobs.append((pdf_path.name, job_name, pdf_path.read_bytes()))


def test_delivery_exports_atomically_and_prints_safe_temporary_name_with_confirmation(qtbot, tmp_path: Path) -> None:
    _ = qtbot
    report = _report()
    service = ReportDeliveryService(BasicReportPdfRenderer())
    destination = tmp_path / "机构筛查-report-1-v1.pdf"

    service.export_pdf(report, destination)
    spooler = _Spooler()
    confirmation = service.print_report(report, spooler=spooler)

    assert destination.exists()
    assert not (tmp_path / "机构筛查-report-1-v1.pdf.partial").exists()
    assert "**1234" in confirmation.subject_display_id
    assert confirmation.captured_at == report.captured_at
    assert spooler.jobs[0][0] == "report-1-v1.pdf"
    assert spooler.jobs[0][1] == "FeetForcePlate report-1 v1"
    assert spooler.jobs[0][2].startswith(b"%PDF")
