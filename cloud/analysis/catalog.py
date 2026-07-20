from __future__ import annotations

from collections.abc import Iterable

from cloud.analysis.models import (
    AlgorithmDescriptor,
    CalibrationLevel,
    ValidationStatus,
)


class MetricCatalog:
    def __init__(self, descriptors: Iterable[AlgorithmDescriptor]) -> None:
        registry: dict[tuple[str, str], AlgorithmDescriptor] = {}
        for item in descriptors:
            key = (item.metric_id, item.metric_definition_version)
            if key in registry:
                raise ValueError(
                    "duplicate metric definition: "
                    f"{item.metric_id}@{item.metric_definition_version}"
                )
            registry[key] = item
        self._registry = registry

    def get(self, metric_id: str, metric_definition_version: str) -> AlgorithmDescriptor:
        return self._registry[(metric_id, metric_definition_version)]

    def all(self) -> tuple[AlgorithmDescriptor, ...]:
        return tuple(self._registry[key] for key in sorted(self._registry))


def _draft_metric(
    *,
    metric_id: str,
    definition: str,
    unit: str,
    required_sample_rate_hz: float,
    required_calibration_level: CalibrationLevel,
    required_duration_seconds: float,
    test_protocol: str = "standard-screening",
    blocked_quality_flags: frozenset[str] = frozenset(),
) -> AlgorithmDescriptor:
    return AlgorithmDescriptor(
        algorithm_id=f"cloud-{metric_id}",
        algorithm_version="0.1.0",
        metric_id=metric_id,
        metric_definition_version="1.0.0",
        definition=definition,
        unit=unit,
        input_schema_version="features/1",
        output_schema_version="metric/1",
        required_sample_rate_hz=required_sample_rate_hz,
        required_calibration_level=required_calibration_level,
        required_duration_seconds=required_duration_seconds,
        required_test_protocols=frozenset({test_protocol}),
        required_profile_fields=frozenset(),
        supported_device_models=frozenset({"DO-P4864"}),
        blocked_quality_flags=blocked_quality_flags,
        validation_status=ValidationStatus.DRAFT,
    )


def default_metric_catalog() -> MetricCatalog:
    """Return the default-closed catalog pending real sample validation.

    A descriptor being present means the requirement is explicit and auditable. It does
    not authorize publication: every entry remains DRAFT until external validation and
    release approval update the immutable registered version.
    """

    static_quality_flags = frozenset({"PAUSE_DETECTED", "POSITION_UNSTABLE"})
    return MetricCatalog(
        (
            _draft_metric(
                metric_id="relative_total_load",
                definition="采集期间所有有效传感点的相对载荷总和",
                unit="relative_count",
                required_sample_rate_hz=1.0,
                required_calibration_level=CalibrationLevel.RELATIVE,
                required_duration_seconds=5.0,
                blocked_quality_flags=static_quality_flags,
            ),
            _draft_metric(
                metric_id="left_right_load_balance",
                definition="左右区域相对载荷占比差异",
                unit="%",
                required_sample_rate_hz=10.0,
                required_calibration_level=CalibrationLevel.RELATIVE,
                required_duration_seconds=20.0,
                blocked_quality_flags=static_quality_flags,
            ),
            _draft_metric(
                metric_id="anterior_posterior_load_balance",
                definition="前后区域相对载荷占比差异",
                unit="%",
                required_sample_rate_hz=10.0,
                required_calibration_level=CalibrationLevel.RELATIVE,
                required_duration_seconds=20.0,
                blocked_quality_flags=static_quality_flags,
            ),
            _draft_metric(
                metric_id="cop_path_length",
                definition="压力中心轨迹在传感点坐标系内的累计路径长度",
                unit="sensor_cell",
                required_sample_rate_hz=12.0,
                required_calibration_level=CalibrationLevel.RELATIVE,
                required_duration_seconds=20.0,
                blocked_quality_flags=static_quality_flags,
            ),
            _draft_metric(
                metric_id="gait_temporal_spatial",
                definition="动态步态事件产生的版本化时空参数集合",
                unit="versioned_metric_set",
                required_sample_rate_hz=100.0,
                required_calibration_level=CalibrationLevel.FORCE,
                required_duration_seconds=30.0,
                test_protocol="dynamic-gait",
                blocked_quality_flags=frozenset(
                    {"ABNORMAL_GAIT", "PAUSE_DETECTED", "INCOMPLETE_CYCLE"}
                ),
            ),
        )
    )
