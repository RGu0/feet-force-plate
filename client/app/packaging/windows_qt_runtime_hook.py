"""PyInstaller runtime hook for the Windows Qt DLL dependency graph.

This file intentionally imports only the standard library.  Importing anything
under ``client.app`` would initialize that package, which imports Qt before
this hook can configure the Windows DLL search path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


if sys.platform == "win32" and hasattr(sys, "_MEIPASS"):
    _bundle_root = Path(sys._MEIPASS)
    _directories = (_bundle_root / "PySide6", _bundle_root / "shiboken6")
    _missing = [str(directory) for directory in _directories if not directory.is_dir()]
    if _missing:
        raise RuntimeError(
            "Frozen Qt runtime is missing required DLL directories: "
            + ", ".join(_missing)
        )
    _WINDOWS_QT_DLL_DIRECTORIES = tuple(
        os.add_dll_directory(str(directory)) for directory in _directories
    )
