from __future__ import annotations

from math import exp

import pytest

from client.hardware_standardization.calibration import (
    TwoSlopeMonotonicVoltageToForceModel,
    VoltageToForceModel,
)


def _model() -> VoltageToForceModel:
    return VoltageToForceModel(
        adc_bit_depth=8,
        adc_reference_voltage_v=4.096,
        r0=2.2,
        alpha=0.751,
        beta=2.657,
    )


def test_8_bit_adc_voltage_and_provisional_newton_model_follow_device_parameters() -> None:
    model = _model()

    assert model.code_to_voltage(0) == 0.0
    assert model.code_to_voltage(128) == pytest.approx(4.096 * 128 / 255)
    assert model.force_from_voltage(0.0) == 0.0

    voltage = 2.0
    expected_n = (10**2.657 * voltage / 2.2 / (4.096 - voltage)) ** (1 / 0.751) / 1000
    assert model.force_from_voltage(voltage) == pytest.approx(expected_n)


def test_voltage_at_reference_is_saturated_not_infinite_force() -> None:
    model = _model()

    assert model.force_from_voltage(4.096) is None
    assert model.force_from_voltage(4.2) is None


def test_two_slope_model_is_continuous_monotonic_and_saturates() -> None:
    model = TwoSlopeMonotonicVoltageToForceModel(
        adc_bit_depth=8,
        adc_reference_voltage_v=4.096,
        log_gain=-0.416054290108397,
        log_low_slope=-2.057009203457983,
        log_high_slope=-0.5532326211611178,
        knot_log_ratio=-0.6755514186685658,
    )
    knot_ratio = exp(model.knot_log_ratio)
    knot_voltage = model.adc_reference_voltage_v * knot_ratio / (1 + knot_ratio)

    assert model.code_to_voltage(128) == pytest.approx(4.096 * 128 / 255)
    assert model.force_from_voltage(knot_voltage * (1 - 1e-8)) == pytest.approx(
        model.force_from_voltage(knot_voltage * (1 + 1e-8)), rel=2e-8
    )
    assert model.force_from_voltage(0.5) < model.force_from_voltage(1.0)
    assert model.force_from_voltage(1.0) < model.force_from_voltage(2.0)
    assert model.force_from_voltage(4.096) is None
