from __future__ import annotations

import ast
import inspect
from pathlib import Path
import textwrap

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton

from client.app.startup_validation import StartupValidationWindow
from client.app.position_guide import GUIDANCE_ASSETS
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


def _startup_window_functions() -> dict[str, list[ast.FunctionDef]]:
    source = textwrap.dedent(inspect.getsource(StartupValidationWindow))
    module = ast.parse(source)
    window_class = next(
        node for node in module.body if isinstance(node, ast.ClassDef)
    )
    functions: dict[str, list[ast.FunctionDef]] = {}
    for node in window_class.body:
        if isinstance(node, ast.FunctionDef):
            functions.setdefault(node.name, []).append(node)
    return functions


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_self_method(call: ast.Call, name: str) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == name
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
    )


def _is_primary_action_focus(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "setFocus"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "_primary_action"
        and isinstance(call.func.value.value, ast.Name)
        and call.func.value.value.id == "self"
    )


def _is_deferred_primary_focus(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "singleShot"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "QTimer"
        and len(call.args) == 2
        and isinstance(call.args[1], ast.Attribute)
        and isinstance(call.args[1].value, ast.Name)
        and call.args[1].value.id == "self"
        and call.args[1].attr == "_focus_primary_action"
    )


def _assert_startup_focus_helper_structure() -> None:
    functions = _startup_window_functions()
    focus_helpers = functions.get("_focus_primary_action", [])
    assert len(focus_helpers) == 1
    helper = focus_helpers[0]

    assert not any(
        _call_name(call) == "singleShot"
        for call in ast.walk(helper)
        if isinstance(call, ast.Call)
    )

    guard = helper.body[0]
    assert isinstance(guard, ast.If)
    calls = [
        statement.value
        for statement in guard.body
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    ]
    assert len(calls) == 3
    assert _is_self_method(calls[0], "raise_")
    assert _is_self_method(calls[1], "activateWindow")
    assert _is_primary_action_focus(calls[2])

    present_functions = functions.get("present", [])
    assert len(present_functions) == 1
    present = present_functions[0]
    deferred_focus_calls = [
        call
        for call in ast.walk(present)
        if isinstance(call, ast.Call)
        and _is_deferred_primary_focus(call)
    ]
    assert len(deferred_focus_calls) == 1


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
    qtbot.waitUntil(lambda: window.focusWidget() is primary[0], timeout=1_000)
    assert window.focusWidget() is primary[0]

    qtbot.mouseClick(primary[0], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(exit_button, Qt.MouseButton.LeftButton)
    assert retried == [True]
    assert exited == [True]


def test_startup_focus_helper_has_one_deferred_activation_aware_implementation() -> None:
    _assert_startup_focus_helper_structure()


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
    assert (assets / "app-icon.png").is_file()
    assert (assets / "FeetForcePlate.icns").is_file()
    assert {
        asset_name
        for asset_pair in GUIDANCE_ASSETS.values()
        for asset_name in asset_pair
    } == {
        "stage-1-body.png",
        "stage-1-feet.png",
        "stage-2-body.png",
        "stage-2-feet.png",
        "stage-3-body.png",
        "stage-3-feet.png",
        "stage-4-body.png",
        "stage-4-feet.jpg",
    }
    for asset_pair in GUIDANCE_ASSETS.values():
        for asset_name in asset_pair:
            assert (assets / "position-guidance" / asset_name).is_file()
    assert 'datas = [(str(assets), "client/app/assets")]' in packaging_spec
    assert 'icon = assets / "FeetForcePlate.icns"' in packaging_spec


def test_repeated_signal_failure_prompts_support_without_technical_leak(qtbot) -> None:
    window = StartupValidationWindow()
    qtbot.addWidget(window)
    window.show()

    window.present(presentation_for(StartupValidationState.SERVICE_REQUIRED))

    assert window.findChild(QLabel, "startupTitle").text() == "设备需要技术支持"
    assert "联系技术支持" in window.findChild(QLabel, "startupMessage").text()
    assert [button.text() for button in _primary_buttons(window)] == ["再次校验"]
    public_copy = " ".join(label.text() for label in window.findChildren(QLabel))
    assert all(
        term not in public_copy
        for term in ("CheckSum", "阈值", "坏点", "堆栈", "串口", "Traceback")
    )


def test_every_failure_state_has_one_primary_action_and_safe_public_copy(qtbot) -> None:
    window = StartupValidationWindow()
    qtbot.addWidget(window)
    window.show()

    for state in (
        StartupValidationState.DEVICE_NOT_FOUND,
        StartupValidationState.DEVICE_BUSY,
        StartupValidationState.LOAD_NOT_EMPTY,
        StartupValidationState.STREAM_INTERRUPTED,
        StartupValidationState.SIGNAL_INVALID,
        StartupValidationState.SERVICE_REQUIRED,
        StartupValidationState.INTERNAL_ERROR,
    ):
        window.present(presentation_for(state))

        assert len(_primary_buttons(window)) == 1
        assert window.findChild(QPushButton, "EXIT_APPLICATION").isVisible()
        assert window.findChild(QLabel, "startupErrorCode").text().startswith(
            "诊断编号 E-"
        )
        public_copy = " ".join(label.text() for label in window.findChildren(QLabel))
        assert all(
            term not in public_copy
            for term in (
                "CheckSum",
                "checksum",
                "阈值",
                "坏点",
                "堆栈",
                "串口",
                "Traceback",
                "/dev/",
                "COM7",
            )
        )
