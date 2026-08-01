"""Versioned, device-owned specifications used to configure hardware adapters."""

from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path
from typing import Any

from .calibration import (
    TwoSlopeMonotonicVoltageToForceModel,
    VoltageToForceConverter,
    VoltageToForceModel,
)
from .geometry import BoardCoordinateLayout


@dataclass(frozen=True, slots=True)
class StartupValidationConfiguration:
    """Device-owned startup collection and empty-board quality parameters."""

    rules_version: str
    threshold_version: str
    maximum_no_valid_signal_s: float
    minimum_frame_rate_hz: float
    maximum_frame_rate_hz: float
    maximum_gap_ms: float
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

    def __post_init__(self) -> None:
        if not self.rules_version or not self.threshold_version:
            raise ValueError("startup validation versions are required")
        if self.maximum_no_valid_signal_s <= 0 or self.maximum_gap_ms <= 0:
            raise ValueError("startup validation timing must be positive")
        if not 0 < self.minimum_frame_rate_hz <= self.maximum_frame_rate_hz:
            raise ValueError("startup validation frame-rate bounds are invalid")
        if self.unloaded_active_count_max < 0 or self.unloaded_active_threshold < 0:
            raise ValueError("startup unloaded thresholds must be non-negative")
        if not 0 <= self.saturation_value <= 255:
            raise ValueError("startup saturation value must fit uint8")
        if self.minimum_changed_sensor_count < 1 or self.service_required_after < 1:
            raise ValueError("startup count thresholds must be positive")


@dataclass(frozen=True, slots=True)
class DeviceSpecification:
    """All device-dependent physical acquisition configuration, without analysis logic."""

    specification_id: str
    device_family: str
    adapter_version: str
    source_schema_version: str
    raw_value_unit: str
    decoded_value_dtype: str
    payload_value_order: str
    data_mode_version: str
    measurement_profile_version: str
    layout: BoardCoordinateLayout
    rows: int
    columns: int
    physical_region_width_mm: float
    physical_region_height_mm: float
    geometry_validation: str
    baseline_profile_version: str
    baseline_min_duration_s: float
    observed_frame_rate_hz: float
    serial_baud_rate: int
    serial_data_bits: int
    serial_parity: str
    serial_stop_bits: int
    startup_validation: StartupValidationConfiguration
    force_calibration_profile_version: str
    force_validation: str
    force_model: VoltageToForceConverter
    quality_policy_version: str
    checksum_policy: str

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.specification_id,
                self.device_family,
                self.adapter_version,
                self.source_schema_version,
                self.raw_value_unit,
                self.decoded_value_dtype,
                self.payload_value_order,
                self.data_mode_version,
                self.measurement_profile_version,
                self.geometry_validation,
                self.baseline_profile_version,
                self.force_calibration_profile_version,
                self.force_validation,
                self.quality_policy_version,
                self.checksum_policy,
            )
        ):
            raise ValueError("device specification identifiers and policies are required")
        if self.rows <= 0 or self.columns <= 0:
            raise ValueError("device specification rows and columns must be positive")
        if self.serial_baud_rate <= 0 or self.serial_data_bits <= 0 or self.serial_stop_bits <= 0:
            raise ValueError("serial transport parameters must be positive")
        if self.serial_parity not in {"N", "E", "O"}:
            raise ValueError("serial parity must be N, E or O")
        if self.payload_value_order not in {"COLUMN_MAJOR", "ROW_MAJOR"}:
            raise ValueError("payload_value_order must be COLUMN_MAJOR or ROW_MAJOR")
        for name, value in (
            ("physical_region_width_mm", self.physical_region_width_mm),
            ("physical_region_height_mm", self.physical_region_height_mm),
            ("baseline_min_duration_s", self.baseline_min_duration_s),
            ("observed_frame_rate_hz", self.observed_frame_rate_hz),
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite value")

    @property
    def matrix_shape(self) -> tuple[int, int]:
        return (self.rows, self.columns)

    def make_adapter(self):
        """Create the generic standardizer configured only by this specification."""

        from .calibrated_array import CalibratedArrayAdapter

        return CalibratedArrayAdapter(
            layout=self.layout,
            adapter_version=self.adapter_version,
            source_schema_version=self.source_schema_version,
            raw_value_unit=self.raw_value_unit,
            measurement_profile_version=self.measurement_profile_version,
            geometry_validation=self.geometry_validation,
            force_validation=self.force_validation,
            force_model=self.force_model,
        )


def load_device_specification(path: Path) -> DeviceSpecification:
    """Load one JSON device specification and build its declared board geometry."""

    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("device specification must be a JSON object")
    if payload.get("schema_version") != "hardware-device-specification/1.0":
        raise ValueError("unsupported device specification schema version")

    geometry = _object(payload, "geometry")
    if geometry.get("kind") != "top_left_grid":
        raise ValueError("only top_left_grid device geometry is supported")
    if geometry.get("coordinate_frame") != "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN":
        raise ValueError("device specification must use the board-local coordinate frame")
    layout = BoardCoordinateLayout.top_left_grid(
        rows=_int(geometry, "rows"),
        columns=_int(geometry, "columns"),
        pitch_x_mm=_number(geometry, "pitch_x_mm"),
        pitch_y_mm=_number(geometry, "pitch_y_mm"),
        geometry_version=_string(geometry, "geometry_version"),
        nominal_active_area_mm2=_optional_number(geometry, "nominal_active_area_mm2"),
        origin_x_mm=_number(geometry, "origin_x_mm"),
        origin_y_mm=_number(geometry, "origin_y_mm"),
    )
    baseline = _object(payload, "baseline")
    timing = _object(payload, "timing")
    serial_transport = _object(payload, "serial_transport")
    startup_validation = _object(payload, "startup_validation")
    force_calibration = _object(payload, "force_calibration")
    adc = _object(payload, "adc")
    force_parameters = _object(force_calibration, "parameters")
    quality_policy = _object(payload, "quality_policy")
    return DeviceSpecification(
        specification_id=_string(payload, "specification_id"),
        device_family=_string(payload, "device_family"),
        adapter_version=_string(payload, "adapter_version"),
        source_schema_version=_string(payload, "source_schema_version"),
        raw_value_unit=_string(payload, "raw_value_unit"),
        decoded_value_dtype=_string(payload, "decoded_value_dtype"),
        payload_value_order=_string(payload, "payload_value_order"),
        data_mode_version=_string(payload, "data_mode_version"),
        measurement_profile_version=_string(payload, "measurement_profile_version"),
        layout=layout,
        rows=_int(geometry, "rows"),
        columns=_int(geometry, "columns"),
        physical_region_width_mm=_number(geometry, "physical_region_width_mm"),
        physical_region_height_mm=_number(geometry, "physical_region_height_mm"),
        geometry_validation=_string(geometry, "geometry_validation"),
        baseline_profile_version=_string(baseline, "profile_version"),
        baseline_min_duration_s=_number(baseline, "minimum_duration_s"),
        observed_frame_rate_hz=_number(timing, "observed_frame_rate_hz"),
        serial_baud_rate=_int(serial_transport, "baud_rate"),
        serial_data_bits=_int(serial_transport, "data_bits"),
        serial_parity=_string(serial_transport, "parity"),
        serial_stop_bits=_int(serial_transport, "stop_bits"),
        startup_validation=StartupValidationConfiguration(
            rules_version=_string(startup_validation, "rules_version"),
            threshold_version=_string(startup_validation, "threshold_version"),
            maximum_no_valid_signal_s=_number(startup_validation, "maximum_no_valid_signal_s"),
            minimum_frame_rate_hz=_number(startup_validation, "minimum_frame_rate_hz"),
            maximum_frame_rate_hz=_number(startup_validation, "maximum_frame_rate_hz"),
            maximum_gap_ms=_number(startup_validation, "maximum_gap_ms"),
            unloaded_frame_mean_max=_number(startup_validation, "unloaded_frame_mean_max"),
            unloaded_active_count_max=_int(startup_validation, "unloaded_active_count_max"),
            unloaded_active_threshold=_int(startup_validation, "unloaded_active_threshold"),
            saturation_value=_int(startup_validation, "saturation_value"),
            saturation_fraction_max=_number(startup_validation, "saturation_fraction_max"),
            minimum_changed_sensor_count=_int(startup_validation, "minimum_changed_sensor_count"),
            fixed_nonzero_fraction_max=_number(startup_validation, "fixed_nonzero_fraction_max"),
            local_persistent_value_max=_number(startup_validation, "local_persistent_value_max"),
            temporal_noise_p95_max=_number(startup_validation, "temporal_noise_p95_max"),
            drift_mean_delta_max=_number(startup_validation, "drift_mean_delta_max"),
            service_required_after=_int(startup_validation, "service_required_after"),
        ),
        force_calibration_profile_version=_string(force_calibration, "profile_version"),
        force_validation=_string(force_calibration, "validation"),
        force_model=_load_voltage_to_force_model(adc, force_calibration, force_parameters),
        quality_policy_version=_string(quality_policy, "profile_version"),
        checksum_policy=_string(quality_policy, "checksum_policy"),
    )


def _load_voltage_to_force_model(
    adc: dict[str, Any],
    force_calibration: dict[str, Any],
    parameters: dict[str, Any],
) -> VoltageToForceConverter:
    if adc.get("coding") != "UNIPOLAR_STRAIGHT_BINARY":
        raise ValueError("only unipolar straight-binary ADC coding is supported")
    if force_calibration.get("input") != "ZERO_CORRECTED_VOLTAGE_V":
        raise ValueError("force model input must be ZERO_CORRECTED_VOLTAGE_V")
    model = force_calibration.get("model")
    common = {
        "adc_bit_depth": _int(adc, "resolution_bits"),
        "adc_reference_voltage_v": _number(adc, "reference_voltage_v"),
        "output_unit": _string(force_calibration, "output_unit"),
    }
    if model == "voltage-to-force/power-ratio/1":
        return VoltageToForceModel(
            **common,
            r0=_number(parameters, "r0"),
            alpha=_number(parameters, "alpha"),
            beta=_number(parameters, "beta"),
        )
    if model == "voltage-to-force/two-slope-monotonic/1":
        return TwoSlopeMonotonicVoltageToForceModel(
            **common,
            log_gain=_number(parameters, "log_gain"),
            log_low_slope=_number(parameters, "log_low_slope"),
            log_high_slope=_number(parameters, "log_high_slope"),
            knot_log_ratio=_number(parameters, "knot_log_ratio"),
        )
    raise ValueError("unsupported voltage-to-force model")


def _object(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _number(payload: dict[str, Any], name: str) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _optional_number(payload: dict[str, Any], name: str) -> float | None:
    value = payload.get(name)
    if value is None:
        return None
    return _number(payload, name)


def _int(payload: dict[str, Any], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value
