from __future__ import annotations

from dataclasses import replace

from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
)
from client.startup_validation.service import CollectionPhase, CollectionProgress
from client.startup_validation.workflow import (
    DeviceBusy,
    DeviceNotFound,
    StartupProgressMode,
    StartupValidationCoordinator,
    StartupValidationState,
    ValidationConnection,
    presentation_for,
)


def _run(
    *,
    outcome: ValidationOutcome = ValidationOutcome.PASS,
    reason: ValidationReason | None = None,
    run_id: str = "run-1",
) -> DeviceValidationRun:
    return DeviceValidationRun(
        validation_run_id=run_id,
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


class _Connector:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls = 0

    def connect(self) -> ValidationConnection:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return ValidationConnection("device-opaque", object(), object())


class _Service:
    def __init__(self, result: DeviceValidationRun) -> None:
        self.result = result
        self.requests = []

    def run(self, request, *, on_progress=None):
        self.requests.append(request)
        on_progress(CollectionProgress(CollectionPhase.WAITING_FOR_EMPTY, 0, 5_000_000_000))
        on_progress(CollectionProgress(CollectionPhase.COLLECTING_BASELINE, 2_500_000_000, 5_000_000_000))
        on_progress(CollectionProgress(CollectionPhase.VALIDATING, 5_000_000_000, 5_000_000_000))
        return replace(
            self.result,
            previous_validation_run_id=request.previous_validation_run_id,
            attempt_number=request.attempt_number,
        )


def _coordinator(
    *,
    connector: _Connector | None = None,
    result: DeviceValidationRun | None = None,
    run_policy=None,
    run_sink=None,
):
    service = _Service(result or _run())
    observed = []
    coordinator = StartupValidationCoordinator(
        connector=connector or _Connector(),
        service_factory=lambda _connection: service,
        terminal_id="terminal-1",
        app_version="0.1.0-test",
        on_presentation=observed.append,
        run_policy=run_policy,
        run_sink=run_sink,
    )
    return coordinator, service, observed


def test_success_path_is_linear_and_workbench_gate_opens_only_after_pass() -> None:
    coordinator, _service, observed = _coordinator()

    assert not coordinator.can_enter_workbench
    run = coordinator.run()

    assert run.outcome is ValidationOutcome.PASS
    assert coordinator.can_enter_workbench
    assert [item.state for item in observed] == [
        StartupValidationState.BOOTSTRAPPING,
        StartupValidationState.CONNECTING,
        StartupValidationState.WAITING_FOR_EMPTY,
        StartupValidationState.COLLECTING_BASELINE,
        StartupValidationState.VALIDATING,
        StartupValidationState.PASSED,
    ]
    collecting = observed[3]
    assert collecting.progress_mode is StartupProgressMode.DETERMINATE
    assert collecting.progress_fraction == 0.5
    assert collecting.countdown_seconds == 3


def test_each_failure_blocks_workbench_and_has_one_plain_recovery_action() -> None:
    cases = {
        ValidationReason.LOAD_NOT_EMPTY: (StartupValidationState.LOAD_NOT_EMPTY, "清空设备"),
        ValidationReason.STREAM_INTERRUPTED: (StartupValidationState.STREAM_INTERRUPTED, "重新校验"),
        ValidationReason.NO_DATA: (StartupValidationState.STREAM_INTERRUPTED, "重新校验"),
        ValidationReason.SIGNAL_INVALID: (StartupValidationState.SIGNAL_INVALID, "重新校验"),
        ValidationReason.NOISE: (StartupValidationState.SIGNAL_INVALID, "重新校验"),
    }
    for reason, (expected_state, expected_action) in cases.items():
        coordinator, _service, _observed = _coordinator(
            result=_run(outcome=ValidationOutcome.RETRYABLE_FAIL, reason=reason)
        )

        coordinator.run()
        presentation = coordinator.presentation

        assert not coordinator.can_enter_workbench
        assert presentation.state is expected_state
        assert presentation.primary_action == expected_action
        assert presentation.error_code
        public_text = f"{presentation.title}{presentation.message}{presentation.primary_action}"
        assert all(term not in public_text for term in ("CheckSum", "阈值", "坏点", "堆栈", "串口"))


def test_connector_failures_have_stable_public_states_and_actions() -> None:
    for failure, state, action in (
        (DeviceNotFound("none"), StartupValidationState.DEVICE_NOT_FOUND, "重新连接"),
        (DeviceBusy("busy"), StartupValidationState.DEVICE_BUSY, "关闭占用程序后重试"),
    ):
        coordinator, _service, _observed = _coordinator(
            connector=_Connector([failure])
        )

        run = coordinator.run()

        assert run.reason.value == state.value
        assert coordinator.presentation.primary_action == action
        assert not coordinator.can_enter_workbench


def test_retry_creates_a_fresh_connection_and_run_context() -> None:
    connector = _Connector()
    coordinator, service, _observed = _coordinator(connector=connector)
    first = coordinator.run()
    service.result = _run(run_id="run-2")

    second = coordinator.retry()

    assert connector.calls == 2
    assert second.validation_run_id == "run-2"
    assert second.previous_validation_run_id == first.validation_run_id
    assert second.attempt_number == 2
    assert service.requests[1].previous_validation_run_id == first.validation_run_id


def test_public_presentation_requires_real_progress_not_fake_percentage() -> None:
    connecting = presentation_for(StartupValidationState.CONNECTING)
    collecting = presentation_for(
        StartupValidationState.COLLECTING_BASELINE,
        progress=CollectionProgress(
            CollectionPhase.COLLECTING_BASELINE,
            1_000_000_000,
            5_000_000_000,
        ),
    )

    assert connecting.progress_mode is StartupProgressMode.INDETERMINATE
    assert connecting.progress_fraction is None
    assert collecting.progress_mode is StartupProgressMode.DETERMINATE
    assert collecting.progress_fraction == 0.2
    assert collecting.countdown_seconds == 4


def test_policy_runs_before_audit_and_service_required_stays_blocked() -> None:
    recorded = []

    def escalate(run: DeviceValidationRun) -> DeviceValidationRun:
        return replace(run, outcome=ValidationOutcome.SERVICE_REQUIRED)

    coordinator, _service, observed = _coordinator(
        result=_run(
            outcome=ValidationOutcome.RETRYABLE_FAIL,
            reason=ValidationReason.SIGNAL_INVALID,
        ),
        run_policy=escalate,
        run_sink=recorded.append,
    )

    run = coordinator.run()

    assert run.outcome is ValidationOutcome.SERVICE_REQUIRED
    assert recorded == [run]
    assert observed[-1].state is StartupValidationState.SERVICE_REQUIRED
    assert "联系" in observed[-1].message
    assert not coordinator.can_enter_workbench


def test_connection_failures_are_also_written_to_the_audit_sink() -> None:
    recorded = []
    coordinator, _service, _observed = _coordinator(
        connector=_Connector([DeviceNotFound("none")]),
        run_sink=recorded.append,
    )

    run = coordinator.run()

    assert recorded == [run]
    assert run.reason is ValidationReason.DEVICE_NOT_FOUND


def test_unexpected_errors_use_stable_public_code_and_unique_diagnostic_ids() -> None:
    ids = iter(("run-1", "diagnostic-1", "run-2", "diagnostic-2"))
    observed = []
    connector = _Connector([RuntimeError("private stack one"), RuntimeError("private stack two")])
    coordinator = StartupValidationCoordinator(
        connector=connector,
        service_factory=lambda _connection: _Service(_run()),
        terminal_id="terminal-1",
        app_version="0.1.0-test",
        on_presentation=observed.append,
        id_factory=lambda: next(ids),
    )

    first = coordinator.run()
    second = coordinator.retry()

    assert first.error_code == second.error_code == "E-INI-006"
    assert first.diagnostic_id != second.diagnostic_id
    assert observed[-1].state is StartupValidationState.INTERNAL_ERROR
    public_text = f"{observed[-1].title} {observed[-1].message}"
    assert "private stack" not in public_text
