"""PyInstaller runtime hook for the Windows Qt DLL dependency graph."""

from __future__ import annotations

import sys
from pathlib import Path

from client.app.packaging.windows_qt_runtime import add_windows_qt_dll_directories


if sys.platform == "win32" and hasattr(sys, "_MEIPASS"):
    _WINDOWS_QT_DLL_DIRECTORIES = add_windows_qt_dll_directories(Path(sys._MEIPASS))
