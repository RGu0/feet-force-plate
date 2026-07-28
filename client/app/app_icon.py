"""Shared application icon for source runs and packaged builds."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


def application_icon() -> QIcon:
    """Return the bundled ScanAnalytics icon without depending on the CWD."""

    return QIcon(str(Path(__file__).with_name("assets") / "app-icon.png"))
