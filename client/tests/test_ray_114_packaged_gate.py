from __future__ import annotations

from PySide6.QtWidgets import QWidget

from client.app.startup_validation import MandatoryStartupGate
from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
)
from client.startup_validation.workflow import StartupValidationState, presentation_for


def _run(
    *,
    outcome: ValidationOutcome = ValidationOutcome.PASS,
    reason: ValidationReason | None = None,
) -> DeviceValidationRun:
    return DeviceValidationRun(
        validation_run_id="run-1",
        previous_validation_run_id=None,
        terminal_id="terminal-1",
        device_ref="device-1",
        attempt_number=1,
        app_version="0.1.0-test",
        protocol_version="do-p4864/test",
        data_mode_version="48x64-uint8-column-major/1",
        rules_version="startup-baseline/1",
        threshold_version="startup-baseline-thresholds/1",
        started_at_wall_ns=1,
        completed_at_wall_ns=2,
        outcome=outcome,
        reason=reason,
        error_code=None if reason is None else "E-TEST-001",
        diagnostic_id="diagnostic-1",
        statistics=None,
        transition_names=(),
        partial_window_discarded=reason is not None,
    )


class _Coordinator:
    def __init__(self, callback, *, passes: bool) -> None:
        self.callback = callback
        self.passes = passes
        self.can_enter_workbench = False
        self.calls = 0

    def run(self):
        self.calls += 1
        self.callback(presentation_for(StartupValidationState.CONNECTING))
        if self.passes:
            self.can_enter_workbench = True
            self.callback(presentation_for(StartupValidationState.PASSED))
            return _run(outcome=ValidationOutcome.PASS)
        self.callback(presentation_for(StartupValidationState.DEVICE_NOT_FOUND))
        return _run(
            outcome=ValidationOutcome.RETRYABLE_FAIL,
            reason=ValidationReason.DEVICE_NOT_FOUND,
        )

    def retry(self):
        return self.run()


def test_workbench_factory_is_not_called_until_passed(qtbot) -> None:
    created: list[QWidget] = []

    def workbench_factory() -> QWidget:
        widget = QWidget()
        created.append(widget)
        return widget

    gate = MandatoryStartupGate(
        coordinator_factory=lambda callback: _Coordinator(callback, passes=True),
        workbench_factory=workbench_factory,
        quit_application=lambda: None,
    )
    qtbot.addWidget(gate.window)

    gate.start()

    assert created == []
    qtbot.waitUntil(lambda: len(created) == 1, timeout=2_000)
    assert created[0].isVisible()
    assert not gate.window.isVisible()


def test_failure_never_creates_workbench_and_retry_starts_a_new_attempt(qtbot) -> None:
    coordinators = []

    def factory(callback):
        coordinator = _Coordinator(callback, passes=False)
        coordinators.append(coordinator)
        return coordinator

    created = []
    gate = MandatoryStartupGate(
        coordinator_factory=factory,
        workbench_factory=lambda: created.append(QWidget()) or created[-1],
        quit_application=lambda: None,
    )
    qtbot.addWidget(gate.window)

    gate.start()
    qtbot.waitUntil(
        lambda: gate.window.presentation.state is StartupValidationState.DEVICE_NOT_FOUND,
        timeout=2_000,
    )
    assert created == []
    first_calls = coordinators[0].calls

    gate.retry()
    qtbot.waitUntil(lambda: coordinators[0].calls > first_calls, timeout=2_000)
    assert created == []
