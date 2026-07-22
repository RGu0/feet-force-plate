"""Immutable physical-array data structures with no body-coordinate semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
import string


class CellStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXCLUDED = "EXCLUDED"


class FrameQuality(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class StandardizationStatus(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class PhysicalArrayCell:
    """One fixed sensor-point centre in a board-local coordinate frame."""

    cell_id: str
    source_index: int
    board_x_mm: float
    board_y_mm: float
    nominal_active_area_mm2: float | None
    status: CellStatus

    def __post_init__(self) -> None:
        if not self.cell_id:
            raise ValueError("cell_id is required")
        if self.source_index < 0:
            raise ValueError("source_index must be non-negative")
        if not isfinite(self.board_x_mm) or not isfinite(self.board_y_mm):
            raise ValueError("board coordinates must be finite")
        if self.nominal_active_area_mm2 is not None and (
            not isfinite(self.nominal_active_area_mm2)
            or self.nominal_active_area_mm2 <= 0
        ):
            raise ValueError("nominal_active_area_mm2 must be positive when declared")


@dataclass(frozen=True, slots=True)
class MeasurementProfile:
    profile_version: str
    geometry_validation: str
    baseline_validation: str
    force_validation: str
    timing_validation: str
    active_area_validation: str
    uncertainty_profile_version: str

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.profile_version,
                self.geometry_validation,
                self.baseline_validation,
                self.force_validation,
                self.timing_validation,
                self.active_area_validation,
                self.uncertainty_profile_version,
            )
        ):
            raise ValueError("measurement profile versions and validation states are required")


@dataclass(frozen=True, slots=True)
class MeasurementUncertainty:
    """Per-session uncertainty declarations; null means not yet established."""

    profile_version: str
    coordinate_mm: float | None
    relative_count: float | None
    force_n: float | None
    timing_s: float | None
    validation: str

    def __post_init__(self) -> None:
        if not self.profile_version or not self.validation:
            raise ValueError("uncertainty profile version and validation are required")
        for name, value in (
            ("coordinate_mm", self.coordinate_mm),
            ("relative_count", self.relative_count),
            ("force_n", self.force_n),
            ("timing_s", self.timing_s),
        ):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative when declared")


@dataclass(frozen=True, slots=True)
class PhysicalArrayFrame:
    timestamp_s: float
    raw_count: tuple[int | float, ...]
    zero_corrected_count: tuple[float, ...] | None
    relative_load_count: tuple[float, ...] | None
    normal_force_n: tuple[float | None, ...]
    quality: FrameQuality
    quality_flags: frozenset[str]

    def __post_init__(self) -> None:
        if not isfinite(self.timestamp_s) or self.timestamp_s < 0:
            raise ValueError("timestamp_s must be finite and non-negative")
        if not self.raw_count:
            raise ValueError("raw_count must not be empty")
        if any(not isfinite(float(value)) for value in self.raw_count):
            raise ValueError("raw_count values must be finite")
        expected = len(self.raw_count)
        for field_name, values in (
            ("zero_corrected_count", self.zero_corrected_count),
            ("relative_load_count", self.relative_load_count),
        ):
            if values is not None and (
                len(values) != expected or any(not isfinite(value) for value in values)
            ):
                raise ValueError(f"{field_name} must be finite and match raw_count length")
        if (self.zero_corrected_count is None) != (self.relative_load_count is None):
            raise ValueError("zero-corrected and relative values must be present together")
        if self.relative_load_count is not None and any(
            value < 0 for value in self.relative_load_count
        ):
            raise ValueError("relative_load_count must be non-negative")
        if len(self.normal_force_n) != expected or any(
            value is not None and not isfinite(value) for value in self.normal_force_n
        ):
            raise ValueError("normal_force_n must match raw_count length and be finite or null")


@dataclass(frozen=True, slots=True)
class PhysicalArraySession:
    schema_version: str
    session_id: str
    coordinate_frame: str
    coordinate_unit: str
    raw_value_unit: str
    relative_value_unit: str
    force_unit: str
    measurement_profile: MeasurementProfile
    uncertainty: MeasurementUncertainty
    cells: tuple[PhysicalArrayCell, ...]
    frames: tuple[PhysicalArrayFrame, ...]
    adapter_version: str
    geometry_version: str
    source_schema_version: str

    def __post_init__(self) -> None:
        if self.schema_version != "physical-array-session/1.0":
            raise ValueError("unsupported physical-array schema version")
        if not self.session_id:
            raise ValueError("session_id is required")
        if self.coordinate_frame != "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN":
            raise ValueError("physical-array sessions use the board coordinate frame")
        if self.coordinate_unit != "mm" or self.force_unit != "N":
            raise ValueError("coordinate and force units must be mm and N")
        if not self.raw_value_unit or not self.relative_value_unit:
            raise ValueError("raw and relative units are required")
        if not self.cells:
            raise ValueError("at least one cell is required")
        if len({cell.cell_id for cell in self.cells}) != len(self.cells):
            raise ValueError("cell_id values must be unique")
        if len({cell.source_index for cell in self.cells}) != len(self.cells):
            raise ValueError("source_index values must be unique")
        timestamps = tuple(frame.timestamp_s for frame in self.frames)
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("frame timestamps must be strictly increasing")
        if any(len(frame.raw_count) != len(self.cells) for frame in self.frames):
            raise ValueError("frame vector length must match cells")
        if any(
            not version
            for version in (
                self.adapter_version,
                self.geometry_version,
                self.source_schema_version,
            )
        ):
            raise ValueError("adapter, geometry, and source schema versions are required")


@dataclass(frozen=True, slots=True)
class BaselineSample:
    host_monotonic_ns: int
    values: tuple[int | float, ...]

    def __post_init__(self) -> None:
        if self.host_monotonic_ns < 0:
            raise ValueError("host_monotonic_ns must be non-negative")
        if not self.values or any(not isfinite(float(value)) for value in self.values):
            raise ValueError("baseline sample values must be finite and non-empty")


@dataclass(frozen=True, slots=True)
class UnloadedBaselineWindow:
    schema_version: str
    baseline_window_id: str
    validation_run_id: str
    validation_outcome: str
    layout_digest: str
    rules_version: str
    threshold_version: str
    source_digest: str
    samples: tuple[BaselineSample, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "unloaded-baseline-window/1":
            raise ValueError("unsupported unloaded baseline window schema version")
        if any(
            not value
            for value in (
                self.baseline_window_id,
                self.validation_run_id,
                self.validation_outcome,
                self.layout_digest,
                self.rules_version,
                self.threshold_version,
                self.source_digest,
            )
        ):
            raise ValueError("baseline identifiers, versions, and digests are required")
        digest = self.source_digest.lower()
        if len(digest) != 64 or any(character not in string.hexdigits for character in digest):
            raise ValueError("source_digest must be a SHA-256 hexadecimal digest")
        if len(self.samples) < 2:
            raise ValueError("at least two baseline samples are required")
        timestamps = tuple(sample.host_monotonic_ns for sample in self.samples)
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("baseline sample timestamps must be strictly increasing")
        width = len(self.samples[0].values)
        if any(len(sample.values) != width for sample in self.samples):
            raise ValueError("baseline sample widths must match")

    @property
    def duration_ns(self) -> int:
        return self.samples[-1].host_monotonic_ns - self.samples[0].host_monotonic_ns


@dataclass(frozen=True, slots=True)
class BaselineReference:
    schema_version: str
    baseline_window_id: str
    layout_digest: str
    zero_offset_count: tuple[float, ...]
    noise_mad_count: tuple[float, ...]
    rules_version: str
    threshold_version: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class ZeroCorrectedValues:
    zero_corrected_count: tuple[float, ...]
    relative_load_count: tuple[float, ...]
    quality_flags: frozenset[str]


@dataclass(frozen=True, slots=True)
class StandardizationOutcome:
    status: StandardizationStatus
    session: PhysicalArraySession | None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is StandardizationStatus.INVALID and self.session is not None:
            raise ValueError("invalid standardization outcomes must not contain a session")
        if self.status is not StandardizationStatus.INVALID and self.session is None:
            raise ValueError("valid and degraded outcomes require a session")
