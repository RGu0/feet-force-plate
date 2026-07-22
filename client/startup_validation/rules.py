from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from client.device.protocol import RawFrame

from .models import ValidationOutcome, ValidationReason, ValidationStatistics


@dataclass(frozen=True, slots=True)
class ValidationThresholds:
    version: str = "startup-baseline-thresholds/1"
    rules_version: str = "startup-baseline/1"
    window_duration_ns: int = 5_000_000_000
    observed_nominal_rate_hz: float = 20.7
    minimum_rate_hz: float = 12.0
    maximum_rate_hz: float = 35.0
    maximum_gap_ns: int = 250_000_000
    unloaded_frame_mean_max: float = 4.0
    unloaded_active_count_max: int = 64
    unloaded_active_threshold: int = 8
    saturation_value: int = 255
    saturation_fraction_max: float = 0.001
    unchanged_sensor_fraction_max: float = 0.995
    fixed_nonzero_fraction_max: float = 0.20
    local_persistent_value_max: float = 32.0
    temporal_noise_p95_max: float = 2.0
    drift_mean_delta_max: float = 2.0
    service_required_after: int = 3

    def __post_init__(self) -> None:
        if self.window_duration_ns <= 0:
            raise ValueError("window_duration_ns must be positive")
        if not 0 < self.minimum_rate_hz <= self.maximum_rate_hz:
            raise ValueError("receive-rate bounds are invalid")
        if self.maximum_gap_ns <= 0:
            raise ValueError("maximum_gap_ns must be positive")
        if self.service_required_after <= 0:
            raise ValueError("service_required_after must be positive")


@dataclass(frozen=True, slots=True)
class ValidationEvaluation:
    outcome: ValidationOutcome
    reasons: tuple[ValidationReason, ...]
    unit: str = "raw_count"


def is_obviously_loaded(frame: RawFrame, thresholds: ValidationThresholds) -> bool:
    values = frame.values
    if values.shape != (48, 64) or values.dtype != np.uint8:
        return False
    return bool(
        float(values.mean()) > thresholds.unloaded_frame_mean_max
        or int(np.count_nonzero(values > thresholds.unloaded_active_threshold))
        > thresholds.unloaded_active_count_max
    )


def evaluate_baseline(
    frames: tuple[RawFrame, ...],
    statistics: ValidationStatistics,
    thresholds: ValidationThresholds,
) -> ValidationEvaluation:
    if not frames:
        return _failed(ValidationReason.NO_DATA)
    if any(
        frame.values.shape != (48, 64) or frame.values.dtype != np.uint8
        for frame in frames
    ):
        return _failed(ValidationReason.SIGNAL_INVALID)

    reasons: list[ValidationReason] = []
    if statistics.duration_ns < thresholds.window_duration_ns:
        reasons.append(ValidationReason.WINDOW_INCOMPLETE)
    if not (
        thresholds.minimum_rate_hz
        <= statistics.received_rate_hz
        <= thresholds.maximum_rate_hz
    ):
        reasons.append(ValidationReason.RATE_OUT_OF_RANGE)
    if statistics.maximum_host_gap_ns > thresholds.maximum_gap_ns:
        reasons.append(ValidationReason.GAP_TOO_LARGE)

    values = np.stack([frame.values for frame in frames]).astype(np.float64)
    if any(is_obviously_loaded(frame, thresholds) for frame in frames):
        reasons.append(ValidationReason.LOAD_NOT_EMPTY)

    saturation_fraction = float(
        np.count_nonzero(values >= thresholds.saturation_value) / values.size
    )
    if saturation_fraction > thresholds.saturation_fraction_max:
        reasons.append(ValidationReason.SATURATION)

    temporal_range = np.ptp(values, axis=0)
    sensor_means = np.mean(values, axis=0)
    unchanged_fraction = float(np.mean(temporal_range == 0))
    if unchanged_fraction > thresholds.unchanged_sensor_fraction_max:
        reasons.append(ValidationReason.NO_VARIATION)
    fixed_nonzero_fraction = float(
        np.mean(
            (temporal_range == 0)
            & (sensor_means >= thresholds.unloaded_active_threshold)
        )
    )
    if fixed_nonzero_fraction > thresholds.fixed_nonzero_fraction_max:
        reasons.append(ValidationReason.FIXED_VALUE_AREA)
    if float(np.max(np.median(values, axis=0))) > thresholds.local_persistent_value_max:
        reasons.append(ValidationReason.LOCAL_ANOMALY)

    temporal_noise_p95 = float(np.percentile(np.std(values, axis=0), 95))
    if temporal_noise_p95 > thresholds.temporal_noise_p95_max:
        reasons.append(ValidationReason.NOISE)

    sample_width = max(1, len(frames) // 5)
    drift_delta = abs(
        float(np.mean(values[-sample_width:]))
        - float(np.mean(values[:sample_width]))
    )
    if drift_delta > thresholds.drift_mean_delta_max:
        reasons.append(ValidationReason.DRIFT)

    unique_reasons = tuple(dict.fromkeys(reasons))
    return ValidationEvaluation(
        outcome=(
            ValidationOutcome.PASS
            if not unique_reasons
            else ValidationOutcome.RETRYABLE_FAIL
        ),
        reasons=unique_reasons,
    )


def _failed(reason: ValidationReason) -> ValidationEvaluation:
    return ValidationEvaluation(
        outcome=ValidationOutcome.RETRYABLE_FAIL,
        reasons=(reason,),
    )
