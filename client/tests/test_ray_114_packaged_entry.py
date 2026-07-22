from __future__ import annotations

from PySide6.QtWidgets import QWidget

from client.app.packaged_entry import build_mandatory_startup_gate
from client.startup_validation.workflow import DeviceNotFound


class _AbsentConnector:
    def connect(self):
        raise DeviceNotFound("absent")


def test_packaged_composition_uses_the_mandatory_gate_before_workbench(qtbot) -> None:
    created: list[QWidget] = []
    gate = build_mandatory_startup_gate(
        terminal_id="terminal-test",
        app_version="0.1.0-test",
        connector=_AbsentConnector(),
        workbench_factory=lambda: created.append(QWidget()) or created[-1],
        quit_application=lambda: None,
    )
    qtbot.addWidget(gate.window)

    gate.start()
    qtbot.waitUntil(
        lambda: gate.window.presentation.error_code == "E-DEV-101",
        timeout=2_000,
    )

    assert created == []
    assert gate.workbench is None
    assert gate.window.isVisible()
