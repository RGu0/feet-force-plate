from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


def main() -> int:
    """Safe package smoke entry; production composition injects activation/device ports."""

    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("FeetForcePlate")
    layout = QVBoxLayout(window)
    title = QLabel("FeetForcePlate 足底压力健康筛查")
    title.setAccessibleName("FeetForcePlate 足底压力健康筛查")
    message = QLabel("正在检查终端激活与本地组件，请稍候")
    message.setAccessibleName("正在检查终端激活与本地组件")
    layout.addWidget(title)
    layout.addWidget(message)
    window.resize(800, 480)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
