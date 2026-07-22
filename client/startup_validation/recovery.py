from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from .models import DeviceValidationRun, ValidationOutcome, ValidationReason


@dataclass(frozen=True, slots=True)
class HistoricalValidationResult:
    validation_run_id: str
    outcome: ValidationOutcome
    reason: ValidationReason | None


class ValidationHistory(Protocol):
    def recent_results(
        self,
        device_ref: str,
        *,
        limit: int,
    ) -> tuple[HistoricalValidationResult, ...]: ...


_SIGNAL_REASONS = frozenset(
    {
        ValidationReason.SIGNAL_INVALID,
        ValidationReason.FIXED_VALUE_AREA,
        ValidationReason.SATURATION,
        ValidationReason.NO_VARIATION,
        ValidationReason.LOCAL_ANOMALY,
        ValidationReason.NOISE,
        ValidationReason.DRIFT,
    }
)


class FailureEscalationPolicy:
    """Escalate only consecutive signal failures, never recoverable I/O/load cases."""

    version = "startup-failure-escalation/1"

    def __init__(
        self,
        *,
        history: ValidationHistory,
        failure_threshold: int = 3,
    ) -> None:
        if failure_threshold < 2:
            raise ValueError("failure_threshold must be at least two")
        self._history = history
        self._failure_threshold = failure_threshold

    def apply(self, run: DeviceValidationRun) -> DeviceValidationRun:
        if (
            run.outcome is not ValidationOutcome.RETRYABLE_FAIL
            or run.reason not in _SIGNAL_REASONS
        ):
            return run
        history = self._history.recent_results(
            run.device_ref,
            limit=self._failure_threshold - 1,
        )
        consecutive = 1
        for result in history:
            if (
                result.outcome not in {
                    ValidationOutcome.RETRYABLE_FAIL,
                    ValidationOutcome.SERVICE_REQUIRED,
                }
                or result.reason not in _SIGNAL_REASONS
            ):
                break
            consecutive += 1
        if consecutive < self._failure_threshold:
            return run
        return replace(
            run,
            outcome=ValidationOutcome.SERVICE_REQUIRED,
            failure_policy_version=self.version,
            transition_names=run.transition_names + ("SERVICE_REQUIRED",),
        )
