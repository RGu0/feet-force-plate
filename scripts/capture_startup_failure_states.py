from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from client.app.startup_validation import StartupValidationWindow
from client.startup_validation.workflow import (
    StartupValidationState,
    presentation_for,
)


_FAILURE_STATES = (
    StartupValidationState.DEVICE_NOT_FOUND,
    StartupValidationState.DEVICE_BUSY,
    StartupValidationState.LOAD_NOT_EMPTY,
    StartupValidationState.STREAM_INTERRUPTED,
    StartupValidationState.SIGNAL_INVALID,
    StartupValidationState.SERVICE_REQUIRED,
    StartupValidationState.INTERNAL_ERROR,
)


def capture(output_dir: Path) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = StartupValidationWindow()
    window.resize(1440, 900)
    window.show()
    saved: list[Path] = []
    for state in _FAILURE_STATES:
        window.present(presentation_for(state))
        app.processEvents()
        QTest.qWait(40)
        destination = output_dir / f"{state.value.lower().replace('_', '-')}.png"
        if not window.grab().save(str(destination), "PNG"):
            raise RuntimeError(f"could not save {destination}")
        saved.append(destination)
    window.close()
    return tuple(saved)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/evidence/linear/RAY-115/ui"),
    )
    args = parser.parse_args()
    for path in capture(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
