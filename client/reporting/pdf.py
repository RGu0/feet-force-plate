from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPageSize, QPdfWriter, QPen

from client.app.heatmap_display import (
    HeatmapDisplayConfig,
    HeatmapDisplayRefiner,
    relative_color_rgba,
)

from .models import BasicReportDocument, ReportMetric, ReportStage


_FONT_FAMILY = "PingFang SC"


def build_stage_heatmap_image(
    heatmap: tuple[tuple[float, ...], ...],
) -> QImage:
    """Render a stage mean using the same cleanup and color policy as the UI."""

    if not heatmap or not heatmap[0]:
        raise ValueError("report heatmap cannot be empty")
    columns = len(heatmap[0])
    if any(len(row) != columns for row in heatmap):
        raise ValueError("report heatmap rows must have equal length")
    refined = np.asarray(
        HeatmapDisplayRefiner(
            HeatmapDisplayConfig(temporal_window=1),
            matrix_shape=(len(heatmap), columns),
        ).refine(heatmap),
        dtype=np.float64,
    )
    image = QImage(columns, len(heatmap), QImage.Format.Format_RGB32)
    for row in range(refined.shape[0]):
        for column in range(refined.shape[1]):
            red, green, blue, alpha = relative_color_rgba(refined[row, column])
            if alpha == 0:
                color = QColor("#000000")
            else:
                opacity = alpha / 255.0
                color = QColor(
                    round(red * opacity),
                    round(green * opacity),
                    round(blue * opacity),
                )
            image.setPixelColor(column, row, color)
    return image


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
            self._draw_overview_page(painter, writer, report)
            if report.stages:
                for page_index, start in enumerate(range(0, len(report.stages), 2), 2):
                    writer.newPage()
                    self._draw_stage_page(
                        painter,
                        writer,
                        report,
                        report.stages[start : start + 2],
                        page_index=page_index,
                    )
            else:
                self._draw_legacy_heatmap(painter, writer, report)
        finally:
            painter.end()

    def _draw_overview_page(
        self,
        painter: QPainter,
        writer: QPdfWriter,
        report: BasicReportDocument,
    ) -> None:
        width, height = writer.width(), writer.height()
        margin = 90
        content_width = width - margin * 2
        painter.fillRect(0, 0, width, height, QColor("#ffffff"))
        y = margin
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont(_FONT_FAMILY, 20, QFont.Weight.Bold))
        painter.drawText(
            QRect(margin, y, content_width, 60),
            Qt.AlignmentFlag.AlignLeft,
            "V1 回放调试报告"
            if report.kind == "V1_REPLAY_DEBUG"
            else "基础筛查报告",
        )
        y += 78
        if report.kind == "V1_REPLAY_DEBUG":
            painter.setPen(QColor("#b45309"))
            painter.setFont(QFont(_FONT_FAMILY, 10, QFont.Weight.Bold))
            painter.drawText(margin, y, "回放调试数据，不代表本次受试者真实测量")
            y += 34
            painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont(_FONT_FAMILY, 10))
        for line in (
            f"报告编号：{report.report_id}  版本：{report.version}",
            f"受试者：{report.subject_display_id}",
            f"检测时间：{report.captured_at.isoformat()}",
            f"协议：{report.protocol_id}@{report.protocol_version}",
        ):
            painter.drawText(margin, y, line)
            y += 34
        y += 20
        y = self._draw_section_title(painter, margin, y, "筛查摘要")
        painter.setFont(QFont(_FONT_FAMILY, 10))
        painter.drawText(
            QRect(margin, y, content_width, 92),
            Qt.TextFlag.TextWordWrap,
            report.summary,
        )
        y += 106
        y = self._draw_section_title(painter, margin, y, "基础相对指标")
        painter.setFont(QFont(_FONT_FAMILY, 10))
        for metric in report.metrics:
            painter.drawText(margin + 20, y, self._metric_text(metric))
            y += 32
        if report.stages:
            y += 24
            y = self._draw_section_title(painter, margin, y, "四阶段图表")
            painter.setFont(QFont(_FONT_FAMILY, 10))
            painter.setPen(QColor("#334155"))
            for stage in report.stages:
                painter.drawText(margin + 20, y, f"• {stage.title}")
                y += 30
            y += 14
            painter.setPen(QColor("#475569"))
            painter.drawText(
                QRect(margin, y, content_width, 110),
                Qt.TextFlag.TextWordWrap,
                "后续页面分别展示每一阶段有效帧的平均相对压力分布，以及该阶段的"
                "前后左右相对负载与描述性 COP 参数。COP ML 表示左右方向，COP AP "
                "表示前后方向；本报告不提供正常范围或风险分级。",
            )
        painter.setPen(QColor("#334155"))
        painter.setFont(QFont(_FONT_FAMILY, 9))
        painter.drawText(
            QRect(margin, height - 215, content_width, 96),
            Qt.TextFlag.TextWordWrap,
            report.disclaimer,
        )
        self._draw_footer(painter, writer, report, page_index=1)

    def _draw_stage_page(
        self,
        painter: QPainter,
        writer: QPdfWriter,
        report: BasicReportDocument,
        stages: tuple[ReportStage, ...],
        *,
        page_index: int,
    ) -> None:
        width, height = writer.width(), writer.height()
        painter.fillRect(0, 0, width, height, QColor("#ffffff"))
        margin = 72
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont(_FONT_FAMILY, 15, QFont.Weight.Bold))
        painter.drawText(margin, 72, "四阶段平均压力分布与描述性参数")
        painter.setFont(QFont(_FONT_FAMILY, 9))
        painter.setPen(QColor("#64748b"))
        painter.drawText(margin, 103, "热图按各阶段有效帧取均值，并采用与实时 UI 一致的显示精修。")
        section_top = 132
        section_height = 675
        for index, stage in enumerate(stages):
            top = section_top + index * section_height
            self._draw_stage_section(
                painter,
                stage,
                QRectF(margin, top, width - margin * 2, section_height - 28),
            )
        self._draw_footer(painter, writer, report, page_index=page_index)

    def _draw_stage_section(
        self,
        painter: QPainter,
        stage: ReportStage,
        bounds: QRectF,
    ) -> None:
        painter.setPen(QPen(QColor("#dce7f2"), 1.2))
        painter.setBrush(QColor("#f8fbfe"))
        painter.drawRoundedRect(bounds, 10.0, 10.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont(_FONT_FAMILY, 12, QFont.Weight.Bold))
        painter.drawText(
            QRectF(bounds.left() + 20, bounds.top() + 16, bounds.width() - 40, 34),
            Qt.AlignmentFlag.AlignLeft,
            stage.title,
        )
        chart = QRectF(bounds.left() + 20, bounds.top() + 58, 500, 375)
        self._draw_heatmap(painter, stage.relative_heatmap, chart)
        painter.setFont(QFont(_FONT_FAMILY, 8))
        painter.setPen(QColor("#64748b"))
        painter.drawText(
            QRectF(chart.left(), chart.bottom() + 8, chart.width(), 25),
            Qt.AlignmentFlag.AlignLeft,
            "阶段有效帧均值 · 相对压力 · 设备平面视角",
        )
        metrics_left = chart.right() + 28
        metrics_top = bounds.top() + 63
        painter.setFont(QFont(_FONT_FAMILY, 9, QFont.Weight.Bold))
        painter.setPen(QColor("#334155"))
        painter.drawText(metrics_left, metrics_top, "阶段参数")
        painter.setFont(QFont(_FONT_FAMILY, 8))
        y = metrics_top + 31
        for metric in stage.metrics:
            painter.setPen(QColor("#475569"))
            painter.drawText(
                QRectF(metrics_left, y, bounds.right() - metrics_left - 18, 24),
                Qt.AlignmentFlag.AlignLeft,
                self._metric_text(metric),
            )
            y += 27

    def _draw_legacy_heatmap(
        self,
        painter: QPainter,
        writer: QPdfWriter,
        report: BasicReportDocument,
    ) -> None:
        target = QRectF(90, writer.height() - 690, writer.width() - 180, 480)
        self._draw_heatmap(painter, report.relative_heatmap, target)

    @staticmethod
    def _draw_heatmap(
        painter: QPainter,
        heatmap: tuple[tuple[float, ...], ...],
        target: QRectF,
    ) -> None:
        image = build_stage_heatmap_image(heatmap)
        image_ratio = image.width() / image.height()
        target_ratio = target.width() / target.height()
        if target_ratio > image_ratio:
            height = target.height()
            width = height * image_ratio
        else:
            width = target.width()
            height = width / image_ratio
        fitted = QRectF(
            target.center().x() - width / 2,
            target.center().y() - height / 2,
            width,
            height,
        )
        painter.fillRect(fitted, QColor("#000000"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(fitted, image)
        painter.setPen(QPen(QColor("#64748b"), 1))
        painter.drawRect(fitted)

    @staticmethod
    def _draw_section_title(
        painter: QPainter,
        x: int,
        y: int,
        title: str,
    ) -> int:
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont(_FONT_FAMILY, 13, QFont.Weight.Bold))
        painter.drawText(x, y, title)
        return y + 38

    @staticmethod
    def _metric_text(metric: ReportMetric) -> str:
        unit = "%" if metric.unit == "percent" else metric.unit.replace("mm2", "mm²")
        return f"{metric.label}：{metric.value:.1f} {unit}".rstrip()

    @staticmethod
    def _draw_footer(
        painter: QPainter,
        writer: QPdfWriter,
        report: BasicReportDocument,
        *,
        page_index: int,
    ) -> None:
        margin = 72
        width, height = writer.width(), writer.height()
        painter.setPen(QPen(QColor("#94a3b8"), 1))
        painter.drawLine(margin, height - 95, width - margin, height - 95)
        painter.setPen(QColor("#475569"))
        painter.setFont(QFont(_FONT_FAMILY, 8))
        painter.drawText(
            QRect(margin, height - 78, width - margin * 2, 38),
            Qt.AlignmentFlag.AlignLeft,
            f"{report.report_id} · v{report.version} · 生成 {report.generated_at.isoformat()}",
        )
        painter.drawText(
            QRect(margin, height - 78, width - margin * 2, 38),
            Qt.AlignmentFlag.AlignRight,
            f"第 {page_index} 页",
        )
