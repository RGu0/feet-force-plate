"""Device-configured ADC voltage restoration and provisional force conversion."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log


@dataclass(frozen=True, slots=True)
class VoltageToForceModel:
    """The configured V→N transfer model; its validation is carried by the spec."""

    adc_bit_depth: int
    adc_reference_voltage_v: float
    r0: float
    alpha: float
    beta: float
    output_unit: str = "N"

    def __post_init__(self) -> None:
        if self.adc_bit_depth <= 0:
            raise ValueError("adc_bit_depth must be positive")
        for name, value in (
            ("adc_reference_voltage_v", self.adc_reference_voltage_v),
            ("r0", self.r0),
            ("alpha", self.alpha),
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite value")
        if not isfinite(self.beta):
            raise ValueError("beta must be finite")
        if self.output_unit != "N":
            raise ValueError("the voltage-to-force model output unit must be N")

    @property
    def max_code(self) -> int:
        return (1 << self.adc_bit_depth) - 1

    def code_to_voltage(self, code: int | float) -> float:
        """Restore an unsigned straight-binary ADC code to volts."""

        if not isfinite(float(code)) or code < 0 or code > self.max_code:
            raise ValueError("ADC code is outside the configured range")
        return float(code) * self.adc_reference_voltage_v / self.max_code

    def signed_count_to_voltage(self, count_delta: int | float) -> float:
        """Convert a zero-corrected count residual to a signed voltage residual."""

        if not isfinite(float(count_delta)):
            raise ValueError("ADC count delta must be finite")
        return float(count_delta) * self.adc_reference_voltage_v / self.max_code

    def force_from_voltage(self, voltage_v: float) -> float | None:
        """Apply the supplied model; reference-or-above voltage is saturation."""

        if not isfinite(voltage_v):
            raise ValueError("voltage must be finite")
        if voltage_v <= 0:
            return 0.0
        if voltage_v >= self.adc_reference_voltage_v:
            return None
        return (
            (10**self.beta * voltage_v / self.r0 / (self.adc_reference_voltage_v - voltage_v))
            ** (1 / self.alpha)
            / 1000
        )


@dataclass(frozen=True, slots=True)
class TwoSlopeMonotonicVoltageToForceModel:
    """Continuous monotonic empirical V→N curve fitted to one device profile.

    The two positive slopes are stored in log space, so a device specification
    cannot configure a decreasing transfer curve. Validation remains explicit
    in the device specification; this class only evaluates its supplied curve.
    """

    adc_bit_depth: int
    adc_reference_voltage_v: float
    log_gain: float
    log_low_slope: float
    log_high_slope: float
    knot_log_ratio: float
    output_unit: str = "N"

    def __post_init__(self) -> None:
        if self.adc_bit_depth <= 0:
            raise ValueError("adc_bit_depth must be positive")
        for name, value in (
            ("adc_reference_voltage_v", self.adc_reference_voltage_v),
            ("log_gain", self.log_gain),
            ("log_low_slope", self.log_low_slope),
            ("log_high_slope", self.log_high_slope),
            ("knot_log_ratio", self.knot_log_ratio),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.adc_reference_voltage_v <= 0:
            raise ValueError("adc_reference_voltage_v must be positive")
        if self.output_unit != "N":
            raise ValueError("the voltage-to-force model output unit must be N")

    @property
    def max_code(self) -> int:
        return (1 << self.adc_bit_depth) - 1

    def code_to_voltage(self, code: int | float) -> float:
        if not isfinite(float(code)) or code < 0 or code > self.max_code:
            raise ValueError("ADC code is outside the configured range")
        return float(code) * self.adc_reference_voltage_v / self.max_code

    def signed_count_to_voltage(self, count_delta: int | float) -> float:
        if not isfinite(float(count_delta)):
            raise ValueError("ADC count delta must be finite")
        return float(count_delta) * self.adc_reference_voltage_v / self.max_code

    def force_from_voltage(self, voltage_v: float) -> float | None:
        """Evaluate the curve; reference-or-above voltage is saturation."""

        if not isfinite(voltage_v):
            raise ValueError("voltage must be finite")
        if voltage_v <= 0:
            return 0.0
        if voltage_v >= self.adc_reference_voltage_v:
            return None
        log_ratio = log(voltage_v / (self.adc_reference_voltage_v - voltage_v))
        log_force = (
            self.log_gain
            + exp(self.log_low_slope) * min(log_ratio, self.knot_log_ratio)
            + exp(self.log_high_slope) * max(log_ratio - self.knot_log_ratio, 0.0)
        )
        try:
            return exp(log_force)
        except OverflowError:
            return None


VoltageToForceConverter = VoltageToForceModel | TwoSlopeMonotonicVoltageToForceModel
