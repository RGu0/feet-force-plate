"""Generic array-to-board standardizer with explicit baseline and force gates."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .baseline import apply_zero_reference
from .calibration import VoltageToForceConverter
from .geometry import BoardCoordinateLayout
from .models import (
    BaselineReference,
    FrameQuality,
    MeasurementProfile,
    MeasurementUncertainty,
    PhysicalArrayFrame,
    PhysicalArraySession,
    StandardizationOutcome,
    StandardizationStatus,
)


@dataclass(frozen=True, slots=True)
class RawArrayFrame:
    """Device-neutral, already-decoded values ordered by the declared layout."""

    host_monotonic_ns: int
    values: tuple[int | float, ...]
    quality_flags: frozenset[str]

    def __post_init__(self) -> None:
        if self.host_monotonic_ns < 0:
            raise ValueError("host_monotonic_ns must be non-negative")
        if not self.values or any(not isfinite(float(value)) for value in self.values):
            raise ValueError("raw array values must be finite and non-empty")


@dataclass(frozen=True, slots=True)
class CalibratedArrayAdapter:
    """Applies only supplied, layout-matched references; it never invents force units."""

    layout: BoardCoordinateLayout
    adapter_version: str = "generic-physical-pressure/1"
    source_schema_version: str = "raw-array/1"
    raw_value_unit: str = "raw_count"
    measurement_profile_version: str = "physical-pressure-profile/1"
    geometry_validation: str = "DECLARED"
    force_validation: str = "UNVALIDATED"
    force_model: VoltageToForceConverter | None = None

    def standardize(
        self,
        *,
        session_id: str,
        frames: tuple[RawArrayFrame, ...],
        baseline_reference: BaselineReference | None = None,
    ) -> StandardizationOutcome:
        if not frames:
            raise ValueError("at least one decoded frame is required")
        if any(len(frame.values) != len(self.layout.cells) for frame in frames):
            raise ValueError("raw frame width must match declared layout")
        timestamps = tuple(frame.host_monotonic_ns for frame in frames)
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("host monotonic timestamps must be strictly increasing")
        if baseline_reference is not None and baseline_reference.layout_digest != self.layout.digest:
            raise ValueError("baseline reference layout digest does not match adapter layout")

        first_timestamp_ns = frames[0].host_monotonic_ns
        output_frames: list[PhysicalArrayFrame] = []
        for raw_frame in frames:
            flags = set(raw_frame.quality_flags)
            flags.add("ACTIVE_AREA_UNVALIDATED")
            if self.force_model is None:
                flags.add("FORCE_UNCALIBRATED")
            elif self.force_validation != "VALIDATED":
                flags.add("FORCE_PROVISIONAL")
            zero_corrected: tuple[float, ...] | None = None
            relative_load: tuple[float, ...] | None = None
            raw_voltage: tuple[float, ...] | None = None
            zero_corrected_voltage: tuple[float, ...] | None = None
            provisional_force: tuple[float | None, ...] | None = None
            if self.force_model is not None:
                raw_voltage = tuple(
                    self.force_model.code_to_voltage(value) for value in raw_frame.values
                )
            if baseline_reference is None:
                flags.add("BASELINE_MISSING")
            else:
                corrected = apply_zero_reference(raw_frame.values, baseline_reference)
                zero_corrected = corrected.zero_corrected_count
                relative_load = corrected.relative_load_count
                flags.update(corrected.quality_flags)
                if self.force_model is not None:
                    zero_corrected_voltage = tuple(
                        self.force_model.signed_count_to_voltage(value)
                        for value in zero_corrected
                    )
                    provisional_force = tuple(
                        self.force_model.force_from_voltage(max(value, 0.0))
                        for value in zero_corrected_voltage
                    )
                    if any(value is None for value in provisional_force):
                        flags.add("ADC_OR_FORCE_MODEL_SATURATED")
            output_frames.append(
                PhysicalArrayFrame(
                    timestamp_s=(raw_frame.host_monotonic_ns - first_timestamp_ns)
                    / 1_000_000_000,
                    raw_count=raw_frame.values,
                    zero_corrected_count=zero_corrected,
                    relative_load_count=relative_load,
                    normal_force_n=(None,) * len(raw_frame.values),
                    quality=FrameQuality.DEGRADED,
                    quality_flags=frozenset(flags),
                    raw_voltage_v=raw_voltage,
                    zero_corrected_voltage_v=zero_corrected_voltage,
                    provisional_force_n=provisional_force,
                )
            )

        profile = MeasurementProfile(
            profile_version=self.measurement_profile_version,
            geometry_validation=self.geometry_validation,
            baseline_validation=("VALIDATED" if baseline_reference else "UNVALIDATED"),
            force_validation=self.force_validation,
            timing_validation="HOST_MONOTONIC",
            active_area_validation="UNVALIDATED",
            uncertainty_profile_version="uncertainty/unknown/1",
        )
        session = PhysicalArraySession(
            schema_version="physical-sensor-observation/1.0",
            session_id=session_id,
            coordinate_frame=self.layout.coordinate_frame,
            coordinate_unit="mm",
            raw_value_unit=self.raw_value_unit,
            relative_value_unit="relative_count",
            force_unit="N",
            measurement_profile=profile,
            uncertainty=MeasurementUncertainty(
                profile_version="uncertainty/unknown/1",
                coordinate_mm=None,
                relative_count=None,
                force_n=None,
                timing_s=None,
                validation="UNVALIDATED",
            ),
            cells=self.layout.cells,
            frames=tuple(output_frames),
            adapter_version=self.adapter_version,
            geometry_version=self.layout.geometry_version,
            source_schema_version=self.source_schema_version,
        )
        return StandardizationOutcome(
            status=StandardizationStatus.DEGRADED,
            session=session,
            reasons=(
                (
                    "FORCE_UNCALIBRATED"
                    if self.force_model is None
                    else "FORCE_PROVISIONAL"
                ),
                "ACTIVE_AREA_UNVALIDATED",
            ),
        )
