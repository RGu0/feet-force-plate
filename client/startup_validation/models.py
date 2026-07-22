from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from client.device.protocol import RawFrame


class ValidationOutcome(StrEnum):
    PASS = "PASS"
    RETRYABLE_FAIL = "RETRYABLE_FAIL"
    SERVICE_REQUIRED = "SERVICE_REQUIRED"


class ValidationReason(StrEnum):
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_BUSY = "DEVICE_BUSY"
    LOAD_NOT_EMPTY = "LOAD_NOT_EMPTY"
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
    NO_DATA = "NO_DATA"
    WINDOW_INCOMPLETE = "WINDOW_INCOMPLETE"
    RATE_OUT_OF_RANGE = "RATE_OUT_OF_RANGE"
    GAP_TOO_LARGE = "GAP_TOO_LARGE"
    FIXED_VALUE_AREA = "FIXED_VALUE_AREA"
    SATURATION = "SATURATION"
    NO_VARIATION = "NO_VARIATION"
    LOCAL_ANOMALY = "LOCAL_ANOMALY"
    NOISE = "NOISE"
    DRIFT = "DRIFT"
    SIGNAL_INVALID = "SIGNAL_INVALID"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ValidationStatistics:
    start_monotonic_ns: int
    end_monotonic_ns: int
    start_wall_time_ns: int
    end_wall_time_ns: int
    start_source_index: int
    end_source_index: int
    valid_frame_count: int
    invalid_candidate_count: int
    resynchronization_count: int
    received_rate_hz: float
    maximum_host_gap_ns: int

    @classmethod
    def from_frames(
        cls,
        frames: tuple[RawFrame, ...],
        *,
        invalid_candidate_count: int,
        resynchronization_count: int,
    ) -> ValidationStatistics:
        if not frames:
            raise ValueError("at least one valid frame is required")
        timestamps = tuple(frame.host_monotonic_ns for frame in frames)
        gaps = tuple(
            current - previous
            for previous, current in zip(timestamps, timestamps[1:])
        )
        if any(gap < 0 for gap in gaps):
            raise ValueError("host monotonic timestamps cannot go backwards")
        duration_ns = timestamps[-1] - timestamps[0]
        rate_hz = (
            (len(frames) - 1) * 1_000_000_000 / duration_ns
            if duration_ns > 0 and len(frames) > 1
            else 0.0
        )
        return cls(
            start_monotonic_ns=timestamps[0],
            end_monotonic_ns=timestamps[-1],
            start_wall_time_ns=frames[0].host_wall_time_ns,
            end_wall_time_ns=frames[-1].host_wall_time_ns,
            start_source_index=frames[0].source_index,
            end_source_index=frames[-1].source_index,
            valid_frame_count=len(frames),
            invalid_candidate_count=invalid_candidate_count,
            resynchronization_count=resynchronization_count,
            received_rate_hz=rate_hz,
            maximum_host_gap_ns=max(gaps, default=0),
        )

    @property
    def duration_ns(self) -> int:
        return self.end_monotonic_ns - self.start_monotonic_ns

    def safe_summary(self) -> dict[str, int | float]:
        return {
            "start_monotonic_ns": self.start_monotonic_ns,
            "end_monotonic_ns": self.end_monotonic_ns,
            "duration_ns": self.duration_ns,
            "start_source_index": self.start_source_index,
            "end_source_index": self.end_source_index,
            "valid_frame_count": self.valid_frame_count,
            "invalid_candidate_count": self.invalid_candidate_count,
            "resynchronization_count": self.resynchronization_count,
            "received_rate_hz": round(self.received_rate_hz, 6),
            "maximum_host_gap_ns": self.maximum_host_gap_ns,
        }


@dataclass(frozen=True, slots=True)
class DeviceValidationRun:
    validation_run_id: str
    previous_validation_run_id: str | None
    terminal_id: str
    device_ref: str
    attempt_number: int
    app_version: str
    protocol_version: str
    data_mode_version: str
    rules_version: str
    threshold_version: str
    started_at_wall_ns: int
    completed_at_wall_ns: int
    outcome: ValidationOutcome
    reason: ValidationReason | None
    error_code: str | None
    diagnostic_id: str
    statistics: ValidationStatistics | None
    transition_names: tuple[str, ...]
    partial_window_discarded: bool = False
    failure_policy_version: str = "startup-failure-escalation/1"
    schema_version: str = field(default="device-validation-run/1", init=False)

    def __post_init__(self) -> None:
        required = (
            self.validation_run_id,
            self.terminal_id,
            self.device_ref,
            self.app_version,
            self.protocol_version,
            self.data_mode_version,
            self.rules_version,
            self.threshold_version,
            self.failure_policy_version,
            self.diagnostic_id,
        )
        if any(not value for value in required):
            raise ValueError("validation run identifiers and versions are required")
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        if self.completed_at_wall_ns < self.started_at_wall_ns:
            raise ValueError("completed wall time cannot precede start")
        if self.outcome is ValidationOutcome.PASS and self.reason is not None:
            raise ValueError("passing validation runs cannot have a failure reason")
        if self.outcome is not ValidationOutcome.PASS and self.reason is None:
            raise ValueError("failed validation runs require a reason")

    def safe_summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "validation_run_id": self.validation_run_id,
            "previous_validation_run_id": self.previous_validation_run_id,
            "terminal_id": self.terminal_id,
            "device_ref": self.device_ref,
            "attempt_number": self.attempt_number,
            "versions": {
                "app": self.app_version,
                "protocol": self.protocol_version,
                "data_mode": self.data_mode_version,
                "rules": self.rules_version,
                "threshold": self.threshold_version,
                "failure_policy": self.failure_policy_version,
            },
            "started_at_wall_ns": self.started_at_wall_ns,
            "completed_at_wall_ns": self.completed_at_wall_ns,
            "outcome": self.outcome.value,
            "reason": None if self.reason is None else self.reason.value,
            "error_code": self.error_code,
            "diagnostic_id": self.diagnostic_id,
            "statistics": None if self.statistics is None else self.statistics.safe_summary(),
            "transitions": self.transition_names,
            "partial_window_discarded": self.partial_window_discarded,
        }
