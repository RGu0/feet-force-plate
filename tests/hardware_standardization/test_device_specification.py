from __future__ import annotations

from pathlib import Path

from client.hardware_standardization.calibrated_array import RawArrayFrame
from client.hardware_standardization.device_specification import load_device_specification
from client.hardware_standardization.models import BaselineReference, StandardizationStatus


SPECIFICATION_PATH = (
    Path(__file__).parents[2]
    / "docs/hardware/device-specifications/do-p4864/1.0.json"
)


def test_do_p4864_specification_owns_device_geometry_and_measurement_configuration() -> None:
    specification = load_device_specification(SPECIFICATION_PATH)

    assert specification.specification_id == "do-p4864/1.0"
    assert specification.raw_value_unit == "uint8_count"
    assert specification.decoded_value_dtype == "uint8"
    assert specification.payload_value_order == "COLUMN_MAJOR"
    assert specification.matrix_shape == (48, 64)
    assert specification.layout.coordinate_frame == "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"
    assert len(specification.layout.cells) == 48 * 64
    assert specification.layout.cell_by_source_index(0).board_x_mm == 0.0
    assert specification.layout.cell_by_source_index(0).board_y_mm == 0.0
    assert specification.layout.cell_by_source_index(48).board_x_mm == 7.99
    assert specification.baseline_min_duration_s == 5.0
    assert specification.observed_frame_rate_hz == 20.7
    assert specification.serial_baud_rate == 1_000_000
    assert specification.serial_data_bits == 8
    assert specification.serial_parity == "N"
    assert specification.serial_stop_bits == 1
    assert specification.startup_validation.minimum_frame_rate_hz == 12.0
    assert specification.startup_validation.maximum_no_valid_signal_s == 5.0
    assert specification.force_validation == "MVP_SCREENING_ESTIMATED_V1"
    assert specification.quality_policy_version == "do-p4864-quality/1"
    assert specification.force_model.output_unit == "N"


def test_specification_creates_a_matching_adapter_without_hard_coding_device_values() -> None:
    specification = load_device_specification(SPECIFICATION_PATH)
    adapter = specification.make_adapter()

    outcome = adapter.standardize(
        session_id="device-spec-session",
        frames=(RawArrayFrame(0, (0,) * 3072, frozenset()),),
    )

    assert outcome.status is StandardizationStatus.DEGRADED
    assert outcome.session is not None
    assert outcome.session.adapter_version == "adapter/do-p4864/1.0"
    assert outcome.session.geometry_version == "geometry/do-p4864/1"
    assert outcome.session.raw_value_unit == "uint8_count"
    assert outcome.session.measurement_profile.profile_version == "physical-pressure-profile/do-p4864/1"


def test_specification_restores_adc_voltage_and_applies_v1_estimated_newton_model_after_baseline() -> None:
    specification = load_device_specification(SPECIFICATION_PATH)
    adapter = specification.make_adapter()
    reference = BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="zero-code",
        layout_digest=specification.layout.digest,
        zero_offset_count=(0.0,) * 3072,
        noise_mad_count=(0.0,) * 3072,
        rules_version="baseline/1",
        threshold_version="threshold/1",
        source_digest="a" * 64,
    )

    outcome = adapter.standardize(
        session_id="voltage-force-session",
        frames=(RawArrayFrame(0, (128,) * 3072, frozenset()),),
        baseline_reference=reference,
    )

    assert outcome.session is not None
    frame = outcome.session.frames[0]
    expected_voltage = 4.096 * 128 / 255
    expected_force = specification.force_model.force_from_voltage(expected_voltage)
    assert frame.raw_voltage_v is not None
    assert frame.zero_corrected_voltage_v is not None
    assert frame.estimated_force_n is not None
    assert frame.raw_voltage_v[0] == expected_voltage
    assert frame.zero_corrected_voltage_v[0] == expected_voltage
    assert frame.estimated_force_n[0] == expected_force
    assert "ESTIMATED_FORCE_V1" in frame.quality_flags


def test_specification_marks_reference_voltage_as_saturated() -> None:
    specification = load_device_specification(SPECIFICATION_PATH)
    adapter = specification.make_adapter()
    reference = BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="zero-code",
        layout_digest=specification.layout.digest,
        zero_offset_count=(0.0,) * 3072,
        noise_mad_count=(0.0,) * 3072,
        rules_version="baseline/1",
        threshold_version="threshold/1",
        source_digest="a" * 64,
    )

    outcome = adapter.standardize(
        session_id="saturated-session",
        frames=(RawArrayFrame(0, (255,) * 3072, frozenset()),),
        baseline_reference=reference,
    )

    assert outcome.session is not None
    frame = outcome.session.frames[0]
    assert frame.estimated_force_n is None
    assert "ADC_OR_FORCE_MODEL_SATURATED" in frame.quality_flags
