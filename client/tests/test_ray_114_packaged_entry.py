from __future__ import annotations

from PySide6.QtWidgets import QWidget

from client.app import packaged_entry
from client.app.packaged_entry import build_mandatory_startup_gate
from client.startup_validation.workflow import DeviceNotFound


class _AbsentConnector:
    def connect(self):
        raise DeviceNotFound("absent")


class _AuditTrail:
    def __init__(self) -> None:
        self.runs = []

    def record(self, run):
        self.runs.append(run)
        return f"event-{len(self.runs)}"

    def recent_results(self, _device_ref: str, *, limit: int):
        return ()


def test_packaged_composition_uses_the_mandatory_gate_before_workbench(qtbot) -> None:
    created: list[QWidget] = []
    audit = _AuditTrail()
    gate = build_mandatory_startup_gate(
        terminal_id="terminal-test",
        app_version="0.1.0-test",
        connector=_AbsentConnector(),
        workbench_factory=lambda: created.append(QWidget()) or created[-1],
        quit_application=lambda: None,
        audit_trail=audit,
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
    assert [run.reason.value for run in audit.runs] == ["DEVICE_NOT_FOUND"]


def test_formal_entry_starts_with_the_p00_institution_access_screen(qtbot) -> None:
    """Catch a regression that sends unregistered users straight to device checks."""

    window = packaged_entry.build_institution_access_screen()
    qtbot.addWidget(window)
    window.show()

    assert window.objectName() == "institutionAccessWindow"
    assert window.findChild(QWidget, "institutionLoginPage").isVisible()
