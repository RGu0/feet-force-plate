from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from .models import (
    AnalysisContext,
    CalibrationState,
    LocalAnalysisResult,
    LocalMetricValue,
    LocalQualityStatus,
    WithheldMetric,
)
from .registry import (
    CalibrationRequirement,
    MetricDefinition,
    MetricValidationStatus,
    default_metric_registry,
)


FloatArray = NDArray[np.float64]


def analyze_local(
    frames: NDArray[np.number],
    context: AnalysisContext,
) -> LocalAnalysisResult:
    source = _validated_frames(frames)
    registry = default_metric_registry()
    if context.quality_status is not LocalQualityStatus.VALID:
        return LocalAnalysisResult(
            result_version=1,
            algorithm_version="local-basic/1.0.0",
            protocol_id=context.protocol_id,
            protocol_version=context.protocol_version,
            source_frame_count=source.shape[0],
            quality_status=context.quality_status,
            raw_count_heatmap=None,
            relative_heatmap=None,
            customer_metrics=(),
            internal_metrics=(),
            withheld_metrics=tuple(
                WithheldMetric(definition.key, "QUALITY_NOT_VALID")
                for definition in registry.definitions
            ),
        )

    mean_frame = np.mean(source, axis=0, dtype=np.float64)
    total = float(np.sum(mean_frame))
    relative_heatmap = _relative_heatmap(mean_frame)
    cop_x, cop_y = _cop_trajectory(source)
    calculators: dict[str, Callable[[], float]] = {
        "total_relative_load": lambda: total,
        "left_load_percent": lambda: _load_percent(
            mean_frame[:, : mean_frame.shape[1] // 2], total
        ),
        "right_load_percent": lambda: _load_percent(
            mean_frame[:, mean_frame.shape[1] // 2 :], total
        ),
        "cop_x_sensor_index": lambda: float(np.mean(cop_x)),
        "cop_y_sensor_index": lambda: float(np.mean(cop_y)),
        "cop_path_length": lambda: _cop_path_length(cop_x, cop_y),
        "cop_x_amplitude": lambda: float(np.ptp(cop_x)),
        "cop_y_amplitude": lambda: float(np.ptp(cop_y)),
        "cop_bounding_area": lambda: float(np.ptp(cop_x) * np.ptp(cop_y)),
    }
    customer: list[LocalMetricValue] = []
    internal: list[LocalMetricValue] = []
    withheld: list[WithheldMetric] = []
    for definition in registry.definitions:
        reason = _prerequisite_failure(definition, context)
        calculator = calculators.get(definition.key)
        if reason is not None:
            withheld.append(WithheldMetric(definition.key, reason))
            continue
        if calculator is None:
            withheld.append(
                WithheldMetric(definition.key, "NOT_IMPLEMENTED_AND_UNVALIDATED")
            )
            continue
        try:
            value = calculator()
        except ValueError:
            withheld.append(WithheldMetric(definition.key, "INSUFFICIENT_CONTACT"))
            continue
        metric = LocalMetricValue(
            key=definition.key,
            value=value,
            unit=definition.unit,
            definition_version=definition.version,
        )
        internal.append(metric)
        if (
            definition.customer_visible
            and definition.validation_status is MetricValidationStatus.VERIFIED_BASIC
        ):
            customer.append(metric)
        else:
            withheld.append(
                WithheldMetric(definition.key, "NOT_CUSTOMER_VALIDATED")
            )
    return LocalAnalysisResult(
        result_version=1,
        algorithm_version="local-basic/1.0.0",
        protocol_id=context.protocol_id,
        protocol_version=context.protocol_version,
        source_frame_count=source.shape[0],
        quality_status=context.quality_status,
        raw_count_heatmap=_matrix_tuple(mean_frame),
        relative_heatmap=relative_heatmap,
        customer_metrics=tuple(customer),
        internal_metrics=tuple(internal),
        withheld_metrics=tuple(withheld),
    )


def _validated_frames(frames: NDArray[np.number]) -> FloatArray:
    source = np.asarray(frames, dtype=np.float64)
    if source.ndim != 3 or 0 in source.shape:
        raise ValueError("frames must be a non-empty three-dimensional sequence")
    if not np.all(np.isfinite(source)):
        raise ValueError("frames must contain finite counts")
    if np.any(source < 0):
        raise ValueError("frames cannot contain negative counts")
    return source


def _relative_heatmap(mean_frame: FloatArray) -> tuple[tuple[float, ...], ...]:
    peak = float(np.max(mean_frame))
    normalized = np.zeros_like(mean_frame) if peak <= 0 else mean_frame / peak
    return tuple(tuple(float(value) for value in row) for row in normalized)


def _matrix_tuple(matrix: FloatArray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in matrix)


def _load_percent(region: FloatArray, total: float) -> float:
    if total <= 0:
        raise ValueError("total contact is zero")
    return float(np.sum(region) / total * 100.0)


def _cop_trajectory(source: FloatArray) -> tuple[FloatArray, FloatArray]:
    totals = np.sum(source, axis=(1, 2))
    valid = totals > 0
    if not np.any(valid):
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    rows, columns = source.shape[1:]
    x_coordinates = np.arange(columns, dtype=np.float64)[None, None, :]
    y_coordinates = np.arange(rows, dtype=np.float64)[None, :, None]
    x = np.sum(source * x_coordinates, axis=(1, 2))[valid] / totals[valid]
    y = np.sum(source * y_coordinates, axis=(1, 2))[valid] / totals[valid]
    return x, y


def _cop_path_length(x: FloatArray, y: FloatArray) -> float:
    if x.size == 0:
        raise ValueError("COP requires contact")
    if x.size == 1:
        return 0.0
    return float(np.sum(np.hypot(np.diff(x), np.diff(y))))


def _prerequisite_failure(
    definition: MetricDefinition,
    context: AnalysisContext,
) -> str | None:
    if context.protocol_id not in definition.applicable_protocol_ids:
        return "PROTOCOL_NOT_SUPPORTED"
    if context.sample_rate_hz < definition.required_sample_rate_hz:
        return "SAMPLE_RATE_TOO_LOW"
    if context.duration_seconds < definition.required_duration_seconds:
        return "DURATION_TOO_SHORT"
    if (
        definition.calibration_requirement
        is CalibrationRequirement.VERIFIED_PHYSICAL
        and context.calibration_state is not CalibrationState.VERIFIED_PHYSICAL
    ):
        return "CALIBRATION_NOT_VERIFIED"
    return None
