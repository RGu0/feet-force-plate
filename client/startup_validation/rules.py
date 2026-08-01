from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from client.device.protocol import RawFrame

from .models import ValidationOutcome, ValidationReason, ValidationStatistics

if TYPE_CHECKING:
    from client.hardware_standardization.device_specification import DeviceSpecification


@dataclass(frozen=True, slots=True)
class ValidationThresholds:
    version: str
    rules_version: str
    window_duration_ns: int
    observed_nominal_rate_hz: float
    minimum_rate_hz: float
    maximum_rate_hz: float
    maximum_gap_ns: int
    unloaded_frame_mean_max: float
    unloaded_active_count_max: int
    unloaded_active_threshold: int
    saturation_value: int
    saturation_fraction_max: float
    minimum_changed_sensor_count: int
    fixed_nonzero_fraction_max: float
    local_persistent_value_max: float
    temporal_noise_p95_max: float
    drift_mean_delta_max: float
    service_required_after: int
    matrix_shape: tuple[int, int]
    data_mode_version: str

    @classmethod
    def from_device_specification(
        cls, specification: "DeviceSpecification"
    ) -> "ValidationThresholds":
        configuration = specification.startup_validation
        return cls(
            version=configuration.threshold_version,
            rules_version=configuration.rules_version,
            window_duration_ns=round(specification.baseline_min_duration_s * 1_000_000_000),
            observed_nominal_rate_hz=specification.observed_frame_rate_hz,
            minimum_rate_hz=configuration.minimum_frame_rate_hz,
            maximum_rate_hz=configuration.maximum_frame_rate_hz,
            maximum_gap_ns=round(configuration.maximum_gap_ms * 1_000_000),
            unloaded_frame_mean_max=configuration.unloaded_frame_mean_max,
            unloaded_active_count_max=configuration.unloaded_active_count_max,
            unloaded_active_threshold=configuration.unloaded_active_threshold,
            saturation_value=configuration.saturation_value,
            saturation_fraction_max=configuration.saturation_fraction_max,
            minimum_changed_sensor_count=configuration.minimum_changed_sensor_count,
            fixed_nonzero_fraction_max=configuration.fixed_nonzero_fraction_max,
            local_persistent_value_max=configuration.local_persistent_value_max,
            temporal_noise_p95_max=configuration.temporal_noise_p95_max,
            drift_mean_delta_max=configuration.drift_mean_delta_max,
            service_required_after=configuration.service_required_after,
            matrix_shape=specification.matrix_shape,
            data_mode_version=specification.data_mode_version,
        )

    def __post_init__(self) -> None:
        if self.window_duration_ns <= 0:
            raise ValueError("window_duration_ns must be positive")
        if not 0 < self.minimum_rate_hz <= self.maximum_rate_hz:
            raise ValueError("receive-rate bounds are invalid")
        if self.maximum_gap_ns <= 0:
            raise ValueError("maximum_gap_ns must be positive")
        if self.minimum_changed_sensor_count < 1:
            raise ValueError("minimum_changed_sensor_count must be positive")
        if self.service_required_after <= 0:
            raise ValueError("service_required_after must be positive")


@dataclass(frozen=True, slots=True)
class ValidationEvaluation:
    outcome: ValidationOutcome
    reasons: tuple[ValidationReason, ...]
    unit: str = "raw_count"


@dataclass(frozen=True, slots=True)
class LoadDetectorObservation:
    """Non-identifying result of one frame's startup-load guard evaluation."""

    mean_guard_triggered: bool
    active_area_guard_triggered: bool

    @property
    def detected(self) -> bool:
        return self.mean_guard_triggered or self.active_area_guard_triggered


def observe_load_detector(
    frame: RawFrame,
    thresholds: ValidationThresholds,
) -> LoadDetectorObservation:
    """Evaluate the two public startup-load guards without retaining frame data."""

    values = frame.values
    if values.shape != thresholds.matrix_shape or values.dtype != np.uint8:
        return LoadDetectorObservation(False, False)
    return LoadDetectorObservation(
        mean_guard_triggered=(
            float(values.mean()) > thresholds.unloaded_frame_mean_max
        ),
        active_area_guard_triggered=(
            int(np.count_nonzero(values > thresholds.unloaded_active_threshold))
            > thresholds.unloaded_active_count_max
        ),
    )


def is_obviously_loaded(frame: RawFrame, thresholds: ValidationThresholds) -> bool:
    return observe_load_detector(frame, thresholds).detected


def evaluate_baseline(
    frames: tuple[RawFrame, ...],
    statistics: ValidationStatistics,
    thresholds: ValidationThresholds,
) -> ValidationEvaluation:
    if not frames:
        return _failed(ValidationReason.NO_DATA)
    if any(
        frame.values.shape != thresholds.matrix_shape or frame.values.dtype != np.uint8
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
    changed_sensor_count = int(np.count_nonzero(temporal_range))
    if changed_sensor_count < thresholds.minimum_changed_sensor_count:
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
