from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton

from client.app.startup_validation import StartupValidationWindow
from client.startup_validation.service import CollectionPhase, CollectionProgress
from client.startup_validation.workflow import (
    StartupValidationState,
    presentation_for,
)


def _primary_buttons(window: StartupValidationWindow) -> list[QPushButton]:
    return [
        button
        for button in window.findChildren(QPushButton)
        if button.isVisible() and button.property("importance") == "primary"
    ]


def test_connecting_is_indeterminate_and_collecting_is_monotonic_determinate(qtbot) -> None:
    window = StartupValidationWindow()
    qtbot.addWidget(window)
    window.show()
    progress = window.findChild(QProgressBar, "startupProgress")

    window.present(presentation_for(StartupValidationState.CONNECTING))
    assert (progress.minimum(), progress.maximum()) == (0, 0)
    assert window.findChild(QLabel, "startupTitle").text() == "正在连接压力设备"

    window.present(
        presentation_for(
            StartupValidationState.COLLECTING_BASELINE,
            progress=CollectionProgress(
                CollectionPhase.COLLECTING_BASELINE,
                2_500_000_000,
                5_000_000_000,
            ),
        )
    )

    assert (progress.minimum(), progress.maximum()) == (0, 100)
    assert progress.value() == 50
    assert window.findChild(QLabel, "startupCountdown").text() == "3 秒"
    assert window.findChild(QLabel, "startupProgressText").text() == "已完成 50%"


def test_failure_has_plain_copy_one_primary_recovery_and_safe_exit(qtbot) -> None:
    retried: list[bool] = []
    exited: list[bool] = []
    window = StartupValidationWindow(
        on_retry=lambda: retried.append(True),
        on_exit=lambda: exited.append(True),
    )
    qtbot.addWidget(window)
    window.show()

    window.present(presentation_for(StartupValidationState.DEVICE_BUSY))

    primary = _primary_buttons(window)
    assert [button.text() for button in primary] == ["关闭占用程序后重试"]
    exit_button = window.findChild(QPushButton, "EXIT_APPLICATION")
    assert exit_button.isVisible()
    assert exit_button.property("importance") == "ghost"
    assert window.findChild(QLabel, "startupErrorCode").text() == "诊断编号 E-DEV-102"
    all_copy = " ".join(label.text() for label in window.findChildren(QLabel))
    assert all(term not in all_copy for term in ("CheckSum", "checksum", "阈值", "坏点", "堆栈", "串口"))
    assert primary[0].hasFocus()

    qtbot.mouseClick(primary[0], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(exit_button, Qt.MouseButton.LeftButton)
    assert retried == [True]
    assert exited == [True]


def test_passed_state_uses_existing_success_asset_and_has_no_skip_action(qtbot) -> None:
    window = StartupValidationWindow()
    qtbot.addWidget(window)
    window.show()

    window.present(presentation_for(StartupValidationState.PASSED))

    assert window.findChild(QLabel, "startupTitle").text() == "设备已准备就绪"
    assert _primary_buttons(window) == []
    assert window.findChild(QProgressBar, "startupProgress").value() == 100
    assert window.findChild(QPushButton, "SKIP_VALIDATION") is None
    assert window.minimumWidth() >= 1280
    assert window.minimumHeight() >= 720


def test_long_public_copy_wraps_inside_reading_width(qtbot) -> None:
    window = StartupValidationWindow()
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()

    window.present(presentation_for(StartupValidationState.INTERNAL_ERROR))

    message = window.findChild(QLabel, "startupMessage")
    assert message.wordWrap()
    assert message.width() <= 720
    assert window.findChild(QPushButton, "startupPrimaryAction").accessibleName()


def test_packaged_startup_assets_are_runtime_files_not_design_document_links() -> None:
    assets = Path(__file__).parents[1] / "app" / "assets"
    packaging_spec = (
        Path(__file__).parents[1] / "app" / "packaging" / "FeetForcePlate.spec"
    ).read_text(encoding="utf-8")

    assert (assets / "logo-horizontal-trimmed.png").is_file()
    assert (assets / "status-success.svg").is_file()
    assert (assets / "status-warning.svg").is_file()
    assert 'Tree("client/app/assets"' in packaging_spec
