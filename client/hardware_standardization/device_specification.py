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
class DeviceSpecification:
    """All device-dependent physical acquisition configuration, without analysis logic."""

    specification_id: str
    device_family: str
    adapter_version: str
    source_schema_version: str
    raw_value_unit: str
    decoded_value_dtype: str
    payload_value_order: str
    measurement_profile_version: str
    layout: BoardCoordinateLayout
    rows: int
    columns: int
    physical_region_width_mm: float
    physical_region_height_mm: float
    geometry_validation: str
    baseline_profile_version: str
    baseline_min_duration_s: float
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
        if self.payload_value_order not in {"COLUMN_MAJOR", "ROW_MAJOR"}:
            raise ValueError("payload_value_order must be COLUMN_MAJOR or ROW_MAJOR")
        for name, value in (
            ("physical_region_width_mm", self.physical_region_width_mm),
            ("physical_region_height_mm", self.physical_region_height_mm),
            ("baseline_min_duration_s", self.baseline_min_duration_s),
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
        measurement_profile_version=_string(payload, "measurement_profile_version"),
        layout=layout,
        rows=_int(geometry, "rows"),
        columns=_int(geometry, "columns"),
        physical_region_width_mm=_number(geometry, "physical_region_width_mm"),
        physical_region_height_mm=_number(geometry, "physical_region_height_mm"),
        geometry_validation=_string(geometry, "geometry_validation"),
        baseline_profile_version=_string(baseline, "profile_version"),
        baseline_min_duration_s=_number(baseline, "minimum_duration_s"),
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
