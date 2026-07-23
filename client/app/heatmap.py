from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from client.local_analysis.display import DisplayFrame

from .heatmap_display import HeatmapDisplayConfig, HeatmapDisplayRefiner


class HeatmapWidget(QWidget):
    """High-DPI vector overlay over a 64x48 display-only raster."""

    def __init__(self, *, display_config: HeatmapDisplayConfig | None = None) -> None:
        super().__init__()
        self.setObjectName("heatmapHost")
        self.setAccessibleName("48×64 实时相对压力热力图与 COP")
        self.setAccessibleDescription(
            "颜色表示相对压力，同时在旁边以文字显示 COP 和左右负重"
        )
        self.setMinimumHeight(320)
        self._display_frame: DisplayFrame | None = None
        self._refiner = HeatmapDisplayRefiner(display_config)
        self._rendered_heatmap: tuple[tuple[float, ...], ...] | None = None

    @property
    def display_frame(self) -> DisplayFrame | None:
        return self._display_frame

    @property
    def rendered_heatmap(self) -> tuple[tuple[float, ...], ...] | None:
        """The UI-only copy; never use it for COP, analysis, storage, or reports."""
        return self._rendered_heatmap

    def set_display_frame(self, frame: DisplayFrame) -> None:
        self._display_frame = frame
        self._rendered_heatmap = self._refiner.refine(frame.relative_heatmap)
        self.update()

    def paintEvent(self, event) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#F6FAFD"))
        painter.setPen(QPen(QColor(37, 105, 188, 20), 1.0))
        for x in range(0, self.width(), 28):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 28):
            painter.drawLine(0, y, self.width(), y)
        frame = self._display_frame
        if frame is None:
            painter.setPen(QColor("#64748B"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "等待设备压力帧",
            )
            return
        image = QImage(64, 48, QImage.Format.Format_RGBA8888)
        values_by_row = self._rendered_heatmap or frame.relative_heatmap
        for row, values in enumerate(values_by_row):
            for column, value in enumerate(values):
                image.setPixelColor(column, row, _relative_color(value))
        target = QRectF(self.rect())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, image)
        painter.setPen(QPen(QColor("#DCE7F2"), 1.5))
        painter.drawRect(target.adjusted(1, 1, -1, -1))
        self._draw_chart_legend(painter)
        if frame.cop_trail:
            painter.setPen(QPen(QColor("#0F172A"), 2.0))
            points = [self._sensor_point(x, y) for x, y in frame.cop_trail]
            for start, end in zip(points, points[1:]):
                painter.drawLine(start, end)
        if frame.cop_x is not None and frame.cop_y is not None:
            point = self._sensor_point(frame.cop_x, frame.cop_y)
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#0F172A"), 2.0))
            painter.drawEllipse(point, 6.0, 6.0)

    def _sensor_point(self, x: float, y: float) -> QPointF:
        return QPointF(
            (x + 0.5) / 64.0 * self.width(),
            (y + 0.5) / 48.0 * self.height(),
        )

    def _draw_chart_legend(self, painter: QPainter) -> None:
        """Draw the source design's chart annotation, not a synthetic asset."""
        if self.width() < 360 or self.height() < 240:
            return
        painter.save()
        painter.setPen(QPen(QColor("#64748B"), 1.0))
        painter.drawText(20, 32, "足底压力分布")

        card = QRectF(self.width() - 156, self.height() - 78, 140, 60)
        painter.setBrush(QColor(255, 255, 255, 236))
        painter.setPen(QPen(QColor("#DCE7F2"), 1.0))
        painter.drawRoundedRect(card, 8.0, 8.0)
        painter.setPen(QColor("#475569"))
        painter.drawText(card.left() + 12, card.top() + 20, "压力")

        heat_scale = QRectF(card.left() + 12, card.top() + 30, 112, 9)
        gradient = QLinearGradient(heat_scale.left(), heat_scale.top(), heat_scale.right(), heat_scale.top())
        for position, color in zip(
            (0.0, 0.25, 0.5, 0.75, 1.0),
            ("#2D4FA8", "#1F9FCE", "#63C685", "#F0C24A", "#E25539"),
        ):
            gradient.setColorAt(position, QColor(color))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(heat_scale, 4.5, 4.5)
        painter.setPen(QColor("#64748B"))
        painter.drawText(card.left() + 12, card.bottom() - 7, "低")
        painter.drawText(card.right() - 20, card.bottom() - 7, "高")
        painter.restore()


def _relative_color(value: float) -> QColor:
    """Interpolate the design-system-only pressure heat scale."""
    stops = (
        QColor("#2D4FA8"),
        QColor("#1F9FCE"),
        QColor("#63C685"),
        QColor("#F0C24A"),
        QColor("#E25539"),
    )
    bounded = max(0.0, min(1.0, value))
    if bounded <= 0.015:
        return QColor(246, 250, 253, 0)
    position = bounded * (len(stops) - 1)
    lower = int(position)
    upper = min(lower + 1, len(stops) - 1)
    ratio = position - lower
    start, end = stops[lower], stops[upper]
    color = QColor(
        round(start.red() + (end.red() - start.red()) * ratio),
        round(start.green() + (end.green() - start.green()) * ratio),
        round(start.blue() + (end.blue() - start.blue()) * ratio),
    )
    # Let weak contact fade into the light canvas, as prescribed by viz.css.
    color.setAlphaF(min(0.92, 0.18 + bounded**0.72 * 0.74))
    return color
