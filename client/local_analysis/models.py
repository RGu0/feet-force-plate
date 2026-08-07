from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CalibrationState(StrEnum):
    RELATIVE_ONLY = "RELATIVE_ONLY"
    VERIFIED_PHYSICAL = "VERIFIED_PHYSICAL"
    MISSING = "MISSING"
    EXPIRED = "EXPIRED"


class LocalQualityStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    sample_rate_hz: float
    duration_seconds: float
    protocol_id: str
    protocol_version: str
    calibration_state: CalibrationState
    quality_status: LocalQualityStatus


@dataclass(frozen=True, slots=True)
class LocalMetricValue:
    key: str
    value: float
    unit: str
    definition_version: str


@dataclass(frozen=True, slots=True)
class WithheldMetric:
    key: str
    reason: str


@dataclass(frozen=True, slots=True)
class LocalStageProjection:
    stage_id: str
    relative_heatmap: tuple[tuple[float, ...], ...]
    metrics: tuple[LocalMetricValue, ...]

    @property
    def metric_map(self) -> dict[str, LocalMetricValue]:
        return {metric.key: metric for metric in self.metrics}


@dataclass(frozen=True, slots=True)
class LocalAnalysisResult:
    result_version: int
    algorithm_version: str
    protocol_id: str
    protocol_version: str
    source_frame_count: int
    quality_status: LocalQualityStatus
    raw_count_heatmap: tuple[tuple[float, ...], ...] | None
    relative_heatmap: tuple[tuple[float, ...], ...] | None
    customer_metrics: tuple[LocalMetricValue, ...]
    internal_metrics: tuple[LocalMetricValue, ...]
    withheld_metrics: tuple[WithheldMetric, ...]
    stage_projections: tuple[LocalStageProjection, ...] = ()

    @property
    def customer_metric_map(self) -> dict[str, LocalMetricValue]:
        return {metric.key: metric for metric in self.customer_metrics}

    @property
    def internal_metric_map(self) -> dict[str, LocalMetricValue]:
        return {metric.key: metric for metric in self.internal_metrics}

    @property
    def withheld_reason_map(self) -> dict[str, str]:
        return {metric.key: metric.reason for metric in self.withheld_metrics}
