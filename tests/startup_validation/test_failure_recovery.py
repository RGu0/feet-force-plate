from __future__ import annotations

from client.startup_validation.models import (
    DeviceValidationRun,
    ValidationOutcome,
    ValidationReason,
)
from client.startup_validation.recovery import (
    FailureEscalationPolicy,
    HistoricalValidationResult,
)


def _run(reason: ValidationReason) -> DeviceValidationRun:
    return DeviceValidationRun(
        validation_run_id="current",
        previous_validation_run_id="previous",
        terminal_id="terminal-1",
        device_ref="ch340-0123456789abcdef0123",
        attempt_number=3,
        app_version="0.1.0-test",
        protocol_version="do-p4864-observed-compact-8bit/1",
        data_mode_version="48x64-uint8-column-major/1",
        rules_version="startup-baseline/1",
        threshold_version="startup-baseline-thresholds/1",
        started_at_wall_ns=1,
        completed_at_wall_ns=2,
        outcome=ValidationOutcome.RETRYABLE_FAIL,
        reason=reason,
        error_code="E-DEV-109",
        diagnostic_id="diagnostic-current",
        statistics=None,
        transition_names=("SIGNAL_INVALID",),
        partial_window_discarded=True,
    )


class _History:
    def __init__(self, results) -> None:
        self.results = tuple(results)

    def recent_results(self, _device_ref: str, *, limit: int):
        return self.results[:limit]


def _historical(
    outcome: ValidationOutcome,
    reason: ValidationReason | None,
) -> HistoricalValidationResult:
    return HistoricalValidationResult("old", outcome, reason)


def test_third_consecutive_signal_failure_escalates_to_service_required() -> None:
    history = _History(
        [
            _historical(ValidationOutcome.RETRYABLE_FAIL, ValidationReason.NOISE),
            _historical(ValidationOutcome.RETRYABLE_FAIL, ValidationReason.SATURATION),
        ]
    )
    policy = FailureEscalationPolicy(history=history, failure_threshold=3)

    result = policy.apply(_run(ValidationReason.SIGNAL_INVALID))

    assert result.outcome is ValidationOutcome.SERVICE_REQUIRED
    assert result.reason is ValidationReason.SIGNAL_INVALID
    assert policy.version == "startup-failure-escalation/1"


def test_pass_or_non_signal_failure_breaks_the_consecutive_chain() -> None:
    for interrupting in (
        _historical(ValidationOutcome.PASS, None),
        _historical(
            ValidationOutcome.RETRYABLE_FAIL,
            ValidationReason.STREAM_INTERRUPTED,
        ),
    ):
        policy = FailureEscalationPolicy(
            history=_History(
                [
                    _historical(
                        ValidationOutcome.RETRYABLE_FAIL,
                        ValidationReason.NOISE,
                    ),
                    interrupting,
                    _historical(
                        ValidationOutcome.RETRYABLE_FAIL,
                        ValidationReason.SATURATION,
                    ),
                ]
            ),
            failure_threshold=3,
        )

        result = policy.apply(_run(ValidationReason.SIGNAL_INVALID))

        assert result.outcome is ValidationOutcome.RETRYABLE_FAIL


def test_recoverable_device_and_load_failures_never_escalate() -> None:
    history = _History(
        [
            _historical(
                ValidationOutcome.RETRYABLE_FAIL,
                ValidationReason.LOAD_NOT_EMPTY,
            )
        ]
        * 10
    )
    policy = FailureEscalationPolicy(history=history, failure_threshold=3)

    for reason in (
        ValidationReason.DEVICE_NOT_FOUND,
        ValidationReason.DEVICE_BUSY,
        ValidationReason.LOAD_NOT_EMPTY,
        ValidationReason.STREAM_INTERRUPTED,
    ):
        assert policy.apply(_run(reason)).outcome is ValidationOutcome.RETRYABLE_FAIL
