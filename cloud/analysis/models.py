from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CalibrationLevel(StrEnum):
    NONE = "NONE"
    RELATIVE = "RELATIVE"
    FORCE = "FORCE"
    PRESSURE = "PRESSURE"


_CALIBRATION_RANK = {
    CalibrationLevel.NONE: 0,
    CalibrationLevel.RELATIVE: 1,
    CalibrationLevel.FORCE: 2,
    CalibrationLevel.PRESSURE: 3,
}


def calibration_rank(level: CalibrationLevel) -> int:
    return _CALIBRATION_RANK[level]


class ValidationStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class CapabilityStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    DEGRADED = "DEGRADED"
    UNSUPPORTED = "UNSUPPORTED"


class AnalysisRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class SessionContext:
    tenant_id: str
    session_id: str
    manifest_sha256: str
    device_model: str
    actual_sample_rate_hz: float
    calibration_level: CalibrationLevel
    calibration_version: str
    duration_seconds: float
    validity_status: str
    manifest_status: str
    cloud_quality_status: str
    quality_flags: frozenset[str]
    test_protocol_id: str
    profile_fields: frozenset[str]

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.session_id:
            raise ValueError("tenant_id and session_id are required")
        if len(self.manifest_sha256) != 64:
            raise ValueError("manifest_sha256 must be a hexadecimal SHA-256 digest")
        try:
            int(self.manifest_sha256, 16)
        except ValueError as exc:
            raise ValueError("manifest_sha256 must be a hexadecimal SHA-256 digest") from exc
        if self.actual_sample_rate_hz < 0 or self.duration_seconds < 0:
            raise ValueError("sample rate and duration cannot be negative")


@dataclass(frozen=True, slots=True)
class RawSession:
    context: SessionContext
    frames: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    status: str
    flags: frozenset[str]

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "FAIL", "DEGRADED"}:
            raise ValueError("quality status must be PASS, FAIL, or DEGRADED")


@dataclass(frozen=True, slots=True)
class SessionIngestedEvent:
    event_id: str
    event_type: str
    tenant_id: str
    session_id: str
    manifest_sha256: str
    payload_schema_version: str
    protocol_profile_version: str
    calibration_version: str
    correlation_id: str
    aggregate_version: int = 1

    def __post_init__(self) -> None:
        if not self.event_id or not self.correlation_id:
            raise ValueError("event_id and correlation_id are required")
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be positive")


@dataclass(frozen=True, slots=True)
class AlgorithmDescriptor:
    algorithm_id: str
    algorithm_version: str
    metric_id: str
    metric_definition_version: str
    definition: str
    unit: str
    input_schema_version: str
    output_schema_version: str
    required_sample_rate_hz: float
    required_calibration_level: CalibrationLevel
    required_duration_seconds: float
    required_test_protocols: frozenset[str]
    required_profile_fields: frozenset[str]
    supported_device_models: frozenset[str]
    blocked_quality_flags: frozenset[str]
    validation_status: ValidationStatus

    def __post_init__(self) -> None:
        required_text = {
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "metric_id": self.metric_id,
            "metric_definition_version": self.metric_definition_version,
            "definition": self.definition,
            "unit": self.unit,
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
        }
        for field_name, value in required_text.items():
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        if self.required_sample_rate_hz < 0 or self.required_duration_seconds < 0:
            raise ValueError("algorithm requirements cannot be negative")


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    metric_id: str
    status: CapabilityStatus
    internal_reason_codes: tuple[str, ...]

    @property
    def publishable(self) -> bool:
        return self.status is CapabilityStatus.SUPPORTED


@dataclass(frozen=True, slots=True)
class FeatureSet:
    tenant_id: str
    session_id: str
    manifest_sha256: str
    calibration_version: str
    pipeline_version: str
    parameters_sha256: str
    cache_key: str
    total_load_by_frame: tuple[float, ...]
    left_load_by_frame: tuple[float, ...]
    right_load_by_frame: tuple[float, ...]
    anterior_load_by_frame: tuple[float, ...]
    posterior_load_by_frame: tuple[float, ...]
    contact_area_by_frame: tuple[int, ...]
    cop_xy_by_frame: tuple[tuple[float | None, float | None], ...]
    actual_sample_rate_hz: float = 0.0
    mean_sensor_load: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisRunKey:
    tenant_id: str
    session_id: str
    pipeline_version: str
    algorithm_set_version: str
    model_set_version: str
    report_schema_version: str
    calibration_version: str
    payload_schema_version: str
    protocol_profile_version: str
    input_manifest_sha256: str
    parameters_sha256: str


@dataclass(frozen=True, slots=True)
class MetricResult:
    metric_id: str
    metric_definition_version: str
    definition: str
    unit: str
    algorithm_id: str
    algorithm_version: str
    value_numeric: float
    validation_status: ValidationStatus
    feature_cache_key: str


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    analysis_run_id: str
    key: AnalysisRunKey
    source_event_id: str
    correlation_id: str
    report_schema_version: str
    status: AnalysisRunStatus
    feature_set: FeatureSet | None
    metric_results: tuple[MetricResult, ...]
    capability_reasons: tuple[tuple[str, tuple[str, ...]], ...]
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PublishedEvent:
    event_type: str
    tenant_id: str
    aggregate_id: str
    correlation_id: str
    payload: tuple[tuple[str, str], ...]
