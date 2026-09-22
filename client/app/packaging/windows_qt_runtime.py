"""Windows DLL search-path setup used by the frozen Qt client."""

from __future__ import annotations

import os
from pathlib import Path


def add_windows_qt_dll_directories(bundle_root: Path) -> tuple[object, ...]:
    """Keep the PySide6 and Shiboken DLL directories registered for this process."""

    if os.name != "nt":
        return ()

    directories = (bundle_root / "PySide6", bundle_root / "shiboken6")
    missing = [str(directory) for directory in directories if not directory.is_dir()]
    if missing:
        raise RuntimeError(
            "Frozen Qt runtime is missing required DLL directories: " + ", ".join(missing)
        )
    return tuple(os.add_dll_directory(str(directory)) for directory in directories)
