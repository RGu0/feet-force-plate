from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from client.local_analysis.display import DisplayFrame


class HeatmapWidget(QWidget):
    """High-DPI vector overlay over a 64x48 display-only raster."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("heatmapHost")
        self.setAccessibleName("48×64 实时相对压力热力图与 COP")
        self.setAccessibleDescription(
            "颜色表示相对压力，同时在旁边以文字显示 COP 和左右负重"
        )
        self.setMinimumHeight(320)
        self._display_frame: DisplayFrame | None = None

    @property
    def display_frame(self) -> DisplayFrame | None:
        return self._display_frame

    def set_display_frame(self, frame: DisplayFrame) -> None:
        self._display_frame = frame
        self.update()

    def paintEvent(self, event) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0b1220"))
        frame = self._display_frame
        if frame is None:
            painter.setPen(QColor("#e2e8f0"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "等待设备压力帧",
            )
            return
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        for row, values in enumerate(frame.relative_heatmap):
            for column, value in enumerate(values):
                image.setPixelColor(column, row, _relative_color(value))
        target = QRectF(self.rect())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, image)
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.drawRect(target.adjusted(1, 1, -1, -1))
        if frame.cop_trail:
            painter.setPen(QPen(QColor("#ffffff"), 2.0))
            points = [self._sensor_point(x, y) for x, y in frame.cop_trail]
            for start, end in zip(points, points[1:]):
                painter.drawLine(start, end)
        if frame.cop_x is not None and frame.cop_y is not None:
            point = self._sensor_point(frame.cop_x, frame.cop_y)
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(QColor("#111827"), 2.0))
            painter.drawEllipse(point, 6.0, 6.0)

    def _sensor_point(self, x: float, y: float) -> QPointF:
        return QPointF(
            (x + 0.5) / 64.0 * self.width(),
            (y + 0.5) / 48.0 * self.height(),
        )


def _relative_color(value: float) -> QColor:
    bounded = max(0.0, min(1.0, value))
    if bounded < 0.5:
        ratio = bounded * 2.0
        return QColor.fromRgbF(0.03, 0.2 + 0.65 * ratio, 0.55 + 0.35 * ratio)
    ratio = (bounded - 0.5) * 2.0
    return QColor.fromRgbF(0.9 + 0.1 * ratio, 0.85 * (1.0 - ratio), 0.05)
