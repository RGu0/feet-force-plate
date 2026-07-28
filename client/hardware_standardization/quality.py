"""Hardware validity gate: baseline bad-point assessment, repair, and V1 force output."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from client.device.protocol import RawFrame

from .defect_repair import SensorDefectRepairPolicy, repair_sensor_defects
from .dynamic_defect_mask import (
    DeviceHealthStatus,
    DynamicDefectMask,
    DynamicDefectPolicy,
)
from .do_p4864 import DoP4864StandardizationAdapter
from .models import BaselineReference, PhysicalArraySession, StandardizationStatus


class HardwareDataValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class BadPointPolicy:
    """DO-P4864 binding of the generic pre-interpolation repair policy."""

    version: str = "quality-policy/do-p4864-mvp/3"
    maximum_bad_cells: int = 2
    maximum_baseline_mad_count: float = 1.0
    known_bad_source_indices: frozenset[int] = frozenset()
    median_window: int = 3
    line_minimum_supported_cells: int = 8
    line_missing_ratio: float = 0.85
    line_support_relative_threshold: float = 0.08
    line_minimum_persistent_frames: int = 3
    maximum_detected_lines_per_frame: int = 1
    maximum_repaired_fraction_per_frame: float = 0.03

    def __post_init__(self) -> None:
        if self.maximum_bad_cells < 0:
            raise ValueError("maximum_bad_cells must not be negative")
        if self.maximum_baseline_mad_count < 0:
            raise ValueError("maximum_baseline_mad_count must not be negative")
        if any(not 0 <= value < 48 * 64 for value in self.known_bad_source_indices):
            raise ValueError("known bad source indexes must fit the 48x64 matrix")

    def sensor_defect_repair_policy(self) -> SensorDefectRepairPolicy:
        return SensorDefectRepairPolicy(
            version=self.version,
            median_window=self.median_window,
            maximum_isolated_bad_cells=self.maximum_bad_cells,
            line_minimum_supported_cells=self.line_minimum_supported_cells,
            line_missing_ratio=self.line_missing_ratio,
            line_support_relative_threshold=self.line_support_relative_threshold,
            line_minimum_persistent_frames=self.line_minimum_persistent_frames,
            maximum_detected_lines_per_frame=self.maximum_detected_lines_per_frame,
            maximum_repaired_fraction_per_frame=self.maximum_repaired_fraction_per_frame,
        )


@dataclass(frozen=True, slots=True)
class HardwareQualityEvaluation:
    validity: HardwareDataValidity
    reasons: tuple[str, ...]
    repaired_source_indices: tuple[int, ...] = ()
    physical_session: PhysicalArraySession | None = None
    processing_metadata: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.validity is HardwareDataValidity.VALID and self.physical_session is None:
            raise ValueError("valid hardware quality requires a physical observation session")
        if self.validity is HardwareDataValidity.INVALID and self.physical_session is not None:
            raise ValueError("invalid hardware quality must not emit derived data")


class DoP4864HardwareQualityGate:
    """Accept only repairable captures and emit board-local estimated-force observations.

    The raw immutable frames remain untouched.  The separate processing matrix is
    repaired before zero correction and V1 force conversion by the layout-neutral
    policy (isolated-cell spatial median, or a single-frame robust directional
    interpolation of a detected line).
    """

    def __init__(
        self,
        *,
        baseline_reference: BaselineReference,
        policy: BadPointPolicy = BadPointPolicy(),
        adapter: DoP4864StandardizationAdapter | None = None,
        dynamic_defect_mask: DynamicDefectMask | None = None,
        dynamic_defect_policy: DynamicDefectPolicy = DynamicDefectPolicy(),
    ) -> None:
        self._adapter = adapter or DoP4864StandardizationAdapter.observed_compact_8bit()
        if baseline_reference.layout_digest != self._adapter.layout.digest:
            raise ValueError("baseline reference does not match the DO-P4864 layout")
        if len(baseline_reference.zero_offset_count) != 48 * 64:
            raise ValueError("baseline reference must contain 48x64 values")
        self._baseline_reference = baseline_reference
        self._policy = policy
        self._dynamic_defect_mask = dynamic_defect_mask
        self._dynamic_defect_policy = dynamic_defect_policy
        if dynamic_defect_mask is not None and dynamic_defect_mask.shape != (48, 64):
            raise ValueError("dynamic defect mask must use the DO-P4864 48x64 shape")

    def evaluate(
        self, *, session_id: str, frames: tuple[RawFrame, ...]
    ) -> HardwareQualityEvaluation:
        if not frames:
            return self._invalid("NO_CAPTURED_FRAMES")
        if (
            self._dynamic_defect_mask is not None
            and self._dynamic_defect_mask.health_status(self._dynamic_defect_policy)
            is DeviceHealthStatus.HEALTH_UNAVAILABLE
        ):
            return self._invalid("DEVICE_DYNAMIC_DEFECT_MASK_UNUSABLE")
        if any(frame.values.shape != (48, 64) or frame.values.dtype != np.uint8 for frame in frames):
            return self._invalid("UNSUPPORTED_RAW_FRAME_FORMAT")

        bad = set(self._policy.known_bad_source_indices)
        if self._dynamic_defect_mask is not None:
            bad.update(self._dynamic_defect_mask.repairable_source_indices)
        bad.update(
            index
            for index, mad in enumerate(self._baseline_reference.noise_mad_count)
            if mad > self._policy.maximum_baseline_mad_count
        )
        repair = repair_sensor_defects(
            tuple(frame.values for frame in frames),
            known_bad_cells=frozenset(self._row_column(source_index) for source_index in bad),
            policy=self._policy.sensor_defect_repair_policy(),
        )
        if not repair.valid:
            return self._invalid(*repair.reasons)
        processing = (
            tuple(frame.values for frame in repair.frames) if repair.any_repairs else None
        )
        outcome = self._adapter.standardize(
            session_id,
            frames,
            baseline_reference=self._baseline_reference,
            processing_matrices=processing,
        )
        if outcome.status is StandardizationStatus.INVALID or outcome.session is None:
            return self._invalid("STANDARDIZATION_FAILED")
        if any(
            frame.estimated_force_n is None
            or any(value is None for value in frame.estimated_force_n)
            or "ADC_OR_FORCE_MODEL_SATURATED" in frame.quality_flags
            for frame in outcome.session.frames
        ):
            return self._invalid("FORCE_CONVERSION_OR_SATURATION_FAILED")
        return HardwareQualityEvaluation(
            validity=HardwareDataValidity.VALID,
            reasons=(),
            repaired_source_indices=self._repaired_source_indices(repair),
            physical_session=outcome.session,
            processing_metadata={
                "baseline_window_id": self._baseline_reference.baseline_window_id,
                "baseline_rules_version": self._baseline_reference.rules_version,
                "baseline_threshold_version": self._baseline_reference.threshold_version,
                "bad_point_policy_version": self._policy.version,
                "sensor_defect_repair": {
                    "policy_version": self._policy.version,
                    "median_window": self._policy.median_window,
                    "line_support_relative_threshold": (
                        self._policy.line_support_relative_threshold
                    ),
                    "detected_missing_rows_per_frame": [
                        list(rows) for rows in repair.detected_missing_rows_per_frame
                    ],
                    "detected_missing_columns_per_frame": [
                        list(columns)
                        for columns in repair.detected_missing_columns_per_frame
                    ],
                    "persistent_missing_rows": list(repair.persistent_missing_rows),
                    "persistent_missing_columns": list(repair.persistent_missing_columns),
                    "method_counts": dict(repair.method_counts),
                    "repaired_cell_counts_per_frame": [
                        int(np.count_nonzero(frame.repair_mask)) for frame in repair.frames
                    ],
                },
                "repaired_source_indices": list(self._repaired_source_indices(repair)),
            },
        )

    def frozen_configuration_versions(self) -> dict[str, str]:
        """Expose the complete V1 quality/physical conversion selection for storage."""

        return {
            **self._adapter.frozen_configuration_versions,
            "bad_point_policy": self._policy.version,
            "baseline_window_id": self._baseline_reference.baseline_window_id,
            "baseline_rules": self._baseline_reference.rules_version,
            "baseline_threshold": self._baseline_reference.threshold_version,
        }

    @staticmethod
    def _row_column(source_index: int) -> tuple[int, int]:
        return source_index % 48, source_index // 48

    @staticmethod
    def _source_index(row: int, column: int) -> int:
        return row + 48 * column

    @classmethod
    def _repaired_source_indices(cls, repair) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    cls._source_index(row, column)
                    for frame in repair.frames
                    for row, column in zip(*np.nonzero(frame.repair_mask), strict=True)
                }
            )
        )

    @staticmethod
    def _invalid(*reasons: str) -> HardwareQualityEvaluation:
        return HardwareQualityEvaluation(HardwareDataValidity.INVALID, tuple(reasons))
