from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from client.app.startup_validation import StartupValidationWindow
from client.startup_validation.service import CollectionPhase, CollectionProgress
from client.startup_validation.workflow import (
    StartupValidationState,
    presentation_for,
)


def capture(output_dir: Path) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = StartupValidationWindow()
    captures = (
        (
            "connecting-1440x900.png",
            (1440, 900),
            presentation_for(StartupValidationState.CONNECTING),
        ),
        (
            "collecting-1440x900.png",
            (1440, 900),
            presentation_for(
                StartupValidationState.COLLECTING_BASELINE,
                progress=CollectionProgress(
                    CollectionPhase.COLLECTING_BASELINE,
                    2_500_000_000,
                    5_000_000_000,
                ),
            ),
        ),
        (
            "passed-1440x900.png",
            (1440, 900),
            presentation_for(StartupValidationState.PASSED),
        ),
        (
            "failure-1440x900.png",
            (1440, 900),
            presentation_for(StartupValidationState.DEVICE_NOT_FOUND),
        ),
        (
            "long-copy-1280x720.png",
            (1280, 720),
            replace(
                presentation_for(StartupValidationState.INTERNAL_ERROR),
                message=(
                    "请重新启动软件并再次完成设备检查；如果仍无法完成，请记录下方诊断编号，"
                    "联系现场负责人或技术支持协助处理。在启动检查通过前，工作台不会开放。"
                ),
            ),
        ),
    )
    saved: list[Path] = []
    window.show()
    for filename, size, presentation in captures:
        window.resize(*size)
        window.present(presentation)
        app.processEvents()
        QTest.qWait(40)
        destination = output_dir / filename
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
        default=Path("docs/evidence/linear/RAY-114/ui"),
    )
    args = parser.parse_args()
    for path in capture(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
