from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPageSize, QPdfWriter, QPen

from .models import BasicReportDocument


class BasicReportPdfRenderer:
    def render(self, report: BasicReportDocument, destination: Path) -> None:
        writer = QPdfWriter(str(destination))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setResolution(144)
        writer.setTitle(f"FeetForcePlate {report.report_id} v{report.version}")
        writer.setCreator("FeetForcePlate local reporting")
        painter = QPainter(writer)
        if not painter.isActive():
            raise RuntimeError("unable to initialize PDF painter")
        try:
            width = writer.width()
            height = writer.height()
            margin = 90
            content_width = width - margin * 2
            y = margin
            painter.fillRect(0, 0, width, height, QColor("#ffffff"))
            painter.setPen(QColor("#0f172a"))
            painter.setFont(QFont("Noto Sans CJK SC", 20, QFont.Weight.Bold))
            painter.drawText(
                QRect(margin, y, content_width, 60),
                Qt.AlignmentFlag.AlignLeft,
                "V1 回放调试报告" if report.kind == "V1_REPLAY_DEBUG" else "基础筛查报告",
            )
            y += 75
            if report.kind == "V1_REPLAY_DEBUG":
                painter.setPen(QColor("#b45309"))
                painter.setFont(QFont("Noto Sans CJK SC", 10, QFont.Weight.Bold))
                painter.drawText(margin, y, "回放调试数据，不代表本次受试者真实测量")
                y += 32
                painter.setPen(QColor("#0f172a"))
            painter.setFont(QFont("Noto Sans CJK SC", 10))
            for line in (
                f"报告编号：{report.report_id}  版本：{report.version}",
                f"受试者：{report.subject_display_id}",
                f"检测时间：{report.captured_at.isoformat()}",
                f"协议：{report.protocol_id}@{report.protocol_version}",
            ):
                painter.drawText(margin, y, line)
                y += 34
            y += 18
            painter.setFont(QFont("Noto Sans CJK SC", 13, QFont.Weight.Bold))
            painter.drawText(margin, y, "筛查摘要")
            y += 36
            painter.setFont(QFont("Noto Sans CJK SC", 10))
            painter.drawText(
                QRect(margin, y, content_width, 60),
                Qt.TextFlag.TextWordWrap,
                report.summary,
            )
            y += 72
            painter.setFont(QFont("Noto Sans CJK SC", 13, QFont.Weight.Bold))
            painter.drawText(margin, y, "基础相对指标")
            y += 36
            painter.setFont(QFont("Noto Sans CJK SC", 10))
            for metric in report.metrics:
                unit = "%" if metric.unit == "percent" else metric.unit
                painter.drawText(
                    margin + 20,
                    y,
                    f"{metric.label}：{metric.value:.1f} {unit}",
                )
                y += 32
            y += 20
            heatmap_height = min(480, height - y - 220)
            self._draw_heatmap(
                painter,
                report.relative_heatmap,
                QRectF(margin, y, content_width, heatmap_height),
            )
            y += heatmap_height + 28
            painter.setPen(QColor("#334155"))
            painter.setFont(QFont("Noto Sans CJK SC", 9))
            painter.drawText(
                QRect(margin, y, content_width, 80),
                Qt.TextFlag.TextWordWrap,
                report.disclaimer,
            )
            painter.setPen(QPen(QColor("#94a3b8"), 1))
            painter.drawLine(margin, height - 95, width - margin, height - 95)
            painter.setPen(QColor("#475569"))
            painter.drawText(
                QRect(margin, height - 78, content_width, 38),
                Qt.AlignmentFlag.AlignLeft,
                f"{report.report_id} · v{report.version} · "
                f"生成 {report.generated_at.isoformat()}",
            )
            painter.drawText(
                QRect(margin, height - 78, content_width, 38),
                Qt.AlignmentFlag.AlignRight,
                "第 1 页",
            )
        finally:
            painter.end()

    @staticmethod
    def _draw_heatmap(
        painter: QPainter,
        heatmap: tuple[tuple[float, ...], ...],
        target: QRectF,
    ) -> None:
        if not heatmap or not heatmap[0]:
            raise ValueError("report heatmap cannot be empty")
        rows = len(heatmap)
        columns = len(heatmap[0])
        image = QImage(columns, rows, QImage.Format.Format_RGB32)
        for row, values in enumerate(heatmap):
            if len(values) != columns:
                raise ValueError("report heatmap rows must have equal length")
            for column, value in enumerate(values):
                bounded = max(0.0, min(1.0, value))
                image.setPixelColor(
                    column,
                    row,
                    QColor.fromHsvF((0.66 * (1.0 - bounded)), 0.9, 0.95),
                )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, image)
        painter.setPen(QPen(QColor("#64748b"), 1))
        painter.drawRect(target)
