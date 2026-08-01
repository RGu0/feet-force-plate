"""Capture deterministic simulated seed-access UI evidence without network/hardware."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from client.app.institution_access import InstitutionAccessWindow
from client.app.pages import PageId
from client.app.qt_shell import ScreeningWindow
from client.app.session_lock import SessionLockController


SIMULATED_HARDWARE_ID = "usb-serial-0123456789abcdef0123"


def _commit_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _save(window: QWidget, destination: Path, app: QApplication) -> tuple[int, int]:
    window.show()
    app.processEvents()
    if not window.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"unable to save {destination}")
    dimensions = (window.width(), window.height())
    window.close()
    app.processEvents()
    return dimensions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    captures: list[dict[str, object]] = []

    login = InstitutionAccessWindow(environment_label="联调环境")
    login.resize(1440, 900)
    width, height = _save(login, args.output / "login.png", app)
    captures.append({"state": "login", "file": "login.png", "width": width, "height": height})

    activation = InstitutionAccessWindow(
        stable_hardware_id=SIMULATED_HARDWARE_ID,
        environment_label="联调环境",
    )
    activation.resize(1440, 900)
    activation.show()
    activation.findChild(QPushButton, "OPEN_LICENSE_REGISTRATION").click()
    app.processEvents()
    width, height = _save(activation, args.output / "activation.png", app)
    captures.append(
        {"state": "activation", "file": "activation.png", "width": width, "height": height}
    )

    lock_controller = SessionLockController(lambda _password: False)
    lock_controller.lock_now()
    locked = ScreeningWindow(session_lock_controller=lock_controller)
    locked.resize(1440, 900)
    locked.show()
    locked.evaluate_session_lock()
    app.processEvents()
    width, height = _save(locked, args.output / "locked.png", app)
    captures.append({"state": "locked", "file": "locked.png", "width": width, "height": height})

    suspended = ScreeningWindow()
    suspended.resize(1280, 720)
    workbench = suspended.page_widget(PageId.WORKBENCH)
    start = workbench.findChild(QPushButton, "START_NEW_SCREENING")
    start.setText("暂不可开始新检测")
    start.setFixedWidth(280)
    start.setEnabled(False)
    start.setToolTip("可继续查看报告与上传既有数据；恢复 License 后可开始新检测")
    workbench.findChild(QLabel, "pageSubtitle").setText(
        "当前 License 已暂停：不能开始新的检测。既有报告仍可查看，待上传数据会继续同步。"
    )
    suspended.findChild(QLabel, "syncStatusBadgeText").setText("既有数据继续同步")
    width, height = _save(
        suspended,
        args.output / "license-suspended.png",
        app,
    )
    captures.append(
        {
            "state": "license-suspended-long-copy",
            "file": "license-suspended.png",
            "width": width,
            "height": height,
        }
    )

    manifest = {
        "evidence_scope": "simulated-access-ui",
        "commit_sha": _commit_sha(),
        "network_used": False,
        "physical_hardware_used": False,
        "captures": captures,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
