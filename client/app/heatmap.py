from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from client.local_analysis.display import DisplayFrame

from .heatmap_display import HeatmapDisplayConfig, HeatmapDisplayRefiner


@dataclass(frozen=True, slots=True)
class PhysicalGridOverlay:
    """Declared board-local dimensions used only for a visual coordinate grid."""

    width_mm: float = 509.3
    height_mm: float = 381.3
    minor_interval_mm: float = 10.0
    major_interval_mm: float = 50.0

    def _positions(self, *, extent_mm: float, interval_mm: float) -> tuple[float, ...]:
        count = int(extent_mm // interval_mm)
        return tuple(index * interval_mm for index in range(count + 1))

    @property
    def minor_x_mm(self) -> tuple[float, ...]:
        return self._positions(
            extent_mm=self.width_mm, interval_mm=self.minor_interval_mm
        )

    @property
    def minor_y_mm(self) -> tuple[float, ...]:
        return self._positions(
            extent_mm=self.height_mm, interval_mm=self.minor_interval_mm
        )

    @property
    def major_x_mm(self) -> tuple[float, ...]:
        return self._positions(
            extent_mm=self.width_mm, interval_mm=self.major_interval_mm
        )

    @property
    def major_y_mm(self) -> tuple[float, ...]:
        return self._positions(
            extent_mm=self.height_mm, interval_mm=self.major_interval_mm
        )


class HeatmapWidget(QWidget):
    """High-DPI vector overlay over a 64x48 display-only raster."""

    def __init__(
        self,
        *,
        display_config: HeatmapDisplayConfig | None = None,
        physical_grid: PhysicalGridOverlay = PhysicalGridOverlay(),
    ) -> None:
        super().__init__()
        self.setObjectName("heatmapHost")
        self.setAccessibleName("48×64 实时相对压力热力图与 COP")
        self.setAccessibleDescription(
            "颜色表示相对压力；显示 1 厘米物理网格、5 厘米主刻度，以及 COP 和左右负重"
        )
        self.setMinimumHeight(320)
        self._display_frame: DisplayFrame | None = None
        self._refiner = HeatmapDisplayRefiner(display_config)
        self._rendered_heatmap: tuple[tuple[float, ...], ...] | None = None
        self._physical_grid = physical_grid

    @property
    def display_frame(self) -> DisplayFrame | None:
        return self._display_frame

    @property
    def rendered_heatmap(self) -> tuple[tuple[float, ...], ...] | None:
        """The UI-only copy; never use it for COP, analysis, storage, or reports."""
        return self._rendered_heatmap

    @property
    def physical_grid(self) -> PhysicalGridOverlay:
        """The declared board dimensions used by the visual overlay only."""
        return self._physical_grid

    def set_display_frame(self, frame: DisplayFrame) -> None:
        self._display_frame = frame
        self._rendered_heatmap = self._refiner.refine(frame.relative_heatmap)
        self.update()

    def paintEvent(self, event) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#F6FAFD"))
        target = self._board_rect()
        frame = self._display_frame
        if frame is None:
            self._draw_physical_grid(painter, target)
            painter.setPen(QPen(QColor("#DCE7F2"), 1.5))
            painter.drawRect(target.adjusted(1, 1, -1, -1))
            painter.setPen(QColor("#64748B"))
            painter.drawText(
                target,
                Qt.AlignmentFlag.AlignCenter,
                "等待设备压力帧",
            )
            return
        image = QImage(64, 48, QImage.Format.Format_RGBA8888)
        values_by_row = self._rendered_heatmap or frame.relative_heatmap
        for row, values in enumerate(values_by_row):
            for column, value in enumerate(values):
                image.setPixelColor(column, row, _relative_color(value))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, image)
        self._draw_physical_grid(painter, target)
        painter.setPen(QPen(QColor("#DCE7F2"), 1.5))
        painter.drawRect(target.adjusted(1, 1, -1, -1))
        self._draw_chart_legend(painter)
        if frame.cop_trail:
            painter.setPen(QPen(QColor("#0F172A"), 2.0))
            points = [self._sensor_point(x, y, target) for x, y in frame.cop_trail]
            for start, end in zip(points, points[1:]):
                painter.drawLine(start, end)
        if frame.cop_x is not None and frame.cop_y is not None:
            point = self._sensor_point(frame.cop_x, frame.cop_y, target)
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#0F172A"), 2.0))
            painter.drawEllipse(point, 6.0, 6.0)

    def _board_rect(self) -> QRectF:
        """Letterbox the raster so visual mm axes retain the board aspect ratio."""
        available = QRectF(self.rect())
        board_ratio = self._physical_grid.width_mm / self._physical_grid.height_mm
        available_ratio = available.width() / available.height()
        if available_ratio > board_ratio:
            height = available.height()
            width = height * board_ratio
        else:
            width = available.width()
            height = width / board_ratio
        return QRectF(
            available.center().x() - width / 2.0,
            available.center().y() - height / 2.0,
            width,
            height,
        )

    def _sensor_point(self, x: float, y: float, target: QRectF) -> QPointF:
        return QPointF(
            target.left() + (x + 0.5) / 64.0 * target.width(),
            target.top() + (y + 0.5) / 48.0 * target.height(),
        )

    def _draw_physical_grid(self, painter: QPainter, target: QRectF) -> None:
        """Overlay 1 cm grid lines and 5 cm labelled lines in board coordinates."""
        painter.save()
        painter.setClipRect(target)
        grid = self._physical_grid
        x_at = lambda mm: target.left() + mm / grid.width_mm * target.width()
        y_at = lambda mm: target.top() + mm / grid.height_mm * target.height()
        painter.setPen(QPen(QColor(15, 23, 42, 30), 0.8))
        for x_mm in grid.minor_x_mm:
            painter.drawLine(QPointF(x_at(x_mm), target.top()), QPointF(x_at(x_mm), target.bottom()))
        for y_mm in grid.minor_y_mm:
            painter.drawLine(QPointF(target.left(), y_at(y_mm)), QPointF(target.right(), y_at(y_mm)))
        painter.setPen(QPen(QColor(15, 23, 42, 82), 1.2))
        for x_mm in grid.major_x_mm:
            painter.drawLine(QPointF(x_at(x_mm), target.top()), QPointF(x_at(x_mm), target.bottom()))
        for y_mm in grid.major_y_mm:
            painter.drawLine(QPointF(target.left(), y_at(y_mm)), QPointF(target.right(), y_at(y_mm)))
        if target.width() >= 360 and target.height() >= 240:
            painter.setPen(QColor(15, 23, 42, 155))
            for x_mm in grid.major_x_mm:
                painter.drawText(QPointF(x_at(x_mm) + 3.0, target.top() + 14.0), f"{x_mm / 10:.0f}")
            for y_mm in grid.major_y_mm:
                if y_mm == 0:
                    continue
                painter.drawText(QPointF(target.left() + 3.0, y_at(y_mm) - 3.0), f"{y_mm / 10:.0f}")
        painter.restore()

    def _draw_chart_legend(self, painter: QPainter) -> None:
        """Draw the source design's chart annotation, not a synthetic asset."""
        if self.width() < 360 or self.height() < 240:
            return
        painter.save()
        painter.setPen(QPen(QColor("#64748B"), 1.0))
        painter.drawText(20, 32, "足底压力分布 · 1 cm 网格 / 5 cm 主刻度")

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
