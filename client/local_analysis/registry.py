from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CalibrationRequirement(StrEnum):
    RELATIVE_ALLOWED = "RELATIVE_ALLOWED"
    VERIFIED_PHYSICAL = "VERIFIED_PHYSICAL"


class MetricValidationStatus(StrEnum):
    VERIFIED_BASIC = "VERIFIED_BASIC"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    UNVALIDATED = "UNVALIDATED"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    key: str
    definition: str
    version: str
    unit: str
    required_sample_rate_hz: float
    calibration_requirement: CalibrationRequirement
    required_duration_seconds: float
    applicable_protocol_ids: tuple[str, ...]
    validation_status: MetricValidationStatus
    customer_visible: bool


class MetricRegistry:
    def __init__(self, definitions: tuple[MetricDefinition, ...]) -> None:
        if len({definition.key for definition in definitions}) != len(definitions):
            raise ValueError("metric keys must be unique")
        self.definitions = definitions
        self._by_key = {definition.key: definition for definition in definitions}

    def get(self, key: str) -> MetricDefinition:
        return self._by_key[key]


_STANDARD = ("standard-static-bilateral",)


def _relative_basic(
    key: str,
    definition: str,
    unit: str,
) -> MetricDefinition:
    return MetricDefinition(
        key=key,
        definition=definition,
        version="1.0.0",
        unit=unit,
        required_sample_rate_hz=10.0,
        calibration_requirement=CalibrationRequirement.RELATIVE_ALLOWED,
        required_duration_seconds=10.0,
        applicable_protocol_ids=_STANDARD,
        validation_status=MetricValidationStatus.VERIFIED_BASIC,
        customer_visible=True,
    )


def _cop_internal(key: str, definition: str, unit: str) -> MetricDefinition:
    return MetricDefinition(
        key=key,
        definition=definition,
        version="1.0.0-pilot",
        unit=unit,
        required_sample_rate_hz=12.0,
        calibration_requirement=CalibrationRequirement.RELATIVE_ALLOWED,
        required_duration_seconds=30.0,
        applicable_protocol_ids=_STANDARD,
        validation_status=MetricValidationStatus.INTERNAL_ONLY,
        customer_visible=False,
    )


def _unvalidated(key: str, definition: str, unit: str) -> MetricDefinition:
    return MetricDefinition(
        key=key,
        definition=definition,
        version="0.0.0-unvalidated",
        unit=unit,
        required_sample_rate_hz=12.0,
        calibration_requirement=CalibrationRequirement.RELATIVE_ALLOWED,
        required_duration_seconds=30.0,
        applicable_protocol_ids=_STANDARD,
        validation_status=MetricValidationStatus.UNVALIDATED,
        customer_visible=False,
    )


def default_metric_registry() -> MetricRegistry:
    return MetricRegistry(
        (
            _relative_basic(
                "total_relative_load",
                "Mean per-frame sum of non-negative sensor counts.",
                "relative_count",
            ),
            _relative_basic(
                "left_load_percent",
                "Left half of the selected device grid divided by total relative load.",
                "percent",
            ),
            _relative_basic(
                "right_load_percent",
                "Right half of the selected device grid divided by total relative load.",
                "percent",
            ),
            _cop_internal(
                "cop_x_sensor_index",
                "Count-weighted center column on the selected device grid.",
                "sensor_index",
            ),
            _cop_internal(
                "cop_y_sensor_index",
                "Count-weighted center row on the selected device grid.",
                "sensor_index",
            ),
            _cop_internal(
                "cop_path_length",
                "Sum of consecutive COP point distances.",
                "sensor_index",
            ),
            _cop_internal(
                "cop_x_amplitude",
                "Maximum minus minimum COP column.",
                "sensor_index",
            ),
            _cop_internal(
                "cop_y_amplitude",
                "Maximum minus minimum COP row.",
                "sensor_index",
            ),
            _cop_internal(
                "cop_bounding_area",
                "COP x amplitude multiplied by y amplitude; not a clinical ellipse.",
                "sensor_index_squared",
            ),
            _unvalidated(
                "cop_frequency_spectrum",
                "Frequency-domain COP content pending sample-rate validation.",
                "unpublished",
            ),
            _unvalidated(
                "stability_score",
                "Composite stability score pending cohort validation.",
                "unpublished",
            ),
            _unvalidated(
                "population_reference_range",
                "Population comparison pending source and approval.",
                "unpublished",
            ),
            MetricDefinition(
                key="total_force_newton",
                definition="Calibrated total force; unavailable without verified calibration.",
                version="0.0.0-unvalidated",
                unit="N",
                required_sample_rate_hz=10.0,
                calibration_requirement=CalibrationRequirement.VERIFIED_PHYSICAL,
                required_duration_seconds=10.0,
                applicable_protocol_ids=_STANDARD,
                validation_status=MetricValidationStatus.UNVALIDATED,
                customer_visible=False,
            ),
        )
    )
