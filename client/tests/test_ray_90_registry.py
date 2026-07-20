from __future__ import annotations

from client.local_analysis.registry import (
    CalibrationRequirement,
    MetricValidationStatus,
    default_metric_registry,
)


def test_every_metric_declares_definition_version_rate_calibration_and_validation() -> None:
    registry = default_metric_registry()

    assert registry.definitions
    for definition in registry.definitions:
        assert definition.key
        assert definition.definition
        assert definition.version
        assert definition.unit
        assert definition.required_sample_rate_hz > 0
        assert definition.calibration_requirement in CalibrationRequirement
        assert definition.validation_status in MetricValidationStatus
        assert definition.applicable_protocol_ids


def test_frequency_score_and_reference_range_are_not_customer_visible() -> None:
    registry = default_metric_registry()

    for key in (
        "cop_frequency_spectrum",
        "stability_score",
        "population_reference_range",
    ):
        definition = registry.get(key)
        assert not definition.customer_visible
        assert definition.validation_status is MetricValidationStatus.UNVALIDATED


def test_cop_path_amplitude_and_area_register_units_and_prerequisites() -> None:
    registry = default_metric_registry()

    assert registry.get("cop_path_length").unit == "sensor_index"
    assert registry.get("cop_x_amplitude").unit == "sensor_index"
    assert registry.get("cop_y_amplitude").unit == "sensor_index"
    assert registry.get("cop_bounding_area").unit == "sensor_index_squared"
    assert registry.get("cop_path_length").required_sample_rate_hz == 12.0
    assert registry.get("cop_path_length").required_duration_seconds == 30.0
    assert (
        registry.get("total_force_newton").calibration_requirement
        is CalibrationRequirement.VERIFIED_PHYSICAL
    )
