from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class FootPlacementWidget(QWidget):
    """The single, low-detail stance canvas shown on source screen P-06."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("footPlacementGuide")
        self.setAccessibleName("实时足印站位示意")
        self.setAccessibleDescription("蓝色双脚轮廓位于压力垫中央虚线区域")
        self.setMinimumSize(460, 380)

    def paintEvent(self, event) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#F6FAFD"))

        grid_pen = QPen(QColor(37, 105, 188, 20), 1.0)
        painter.setPen(grid_pen)
        grid = 28
        for x in range(0, self.width() + grid, grid):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height() + grid, grid):
            painter.drawLine(0, y, self.width(), y)

        inset = self.rect().adjusted(40, 40, -40, -40)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#B7D3F2"), 2.0, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(inset, 20, 20)

        painter.setBrush(QColor(23, 162, 196, 140))
        painter.setPen(QPen(QColor(23, 162, 196, 190), 2.0))
        scale_x = self.width() / 460.0
        scale_y = self.height() / 380.0
        for cx in (185, 275):
            painter.drawEllipse(
                int((cx - 42) * scale_x), int((150 - 38) * scale_y),
                int(84 * scale_x), int(76 * scale_y),
            )
            painter.drawRoundedRect(
                int((cx - 15) * scale_x), int(178 * scale_y),
                int(34 * scale_x), int(64 * scale_y),
                int(17 * scale_x), int(17 * scale_y),
            )
            painter.drawEllipse(
                int((cx - 30) * scale_x), int(214 * scale_y),
                int(60 * scale_x), int(76 * scale_y),
            )

        painter.setPen(QColor("#64748B"))
        painter.drawText(
            self.rect().adjusted(12, 8, -12, -8),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            "实时足印示意",
        )
