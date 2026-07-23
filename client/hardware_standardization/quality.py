"""Hardware validity gate: baseline bad-point assessment, repair, and V1 force output."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from client.device.protocol import RawFrame

from .do_p4864 import DoP4864StandardizationAdapter
from .models import BaselineReference, PhysicalArraySession, StandardizationStatus


class HardwareDataValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class BadPointPolicy:
    """Conservative V1 repair policy for a 48x64 board-local matrix."""

    version: str = "quality-policy/do-p4864-mvp/1"
    maximum_bad_cells: int = 2
    maximum_baseline_mad_count: float = 1.0
    known_bad_source_indices: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.maximum_bad_cells < 0:
            raise ValueError("maximum_bad_cells must not be negative")
        if self.maximum_baseline_mad_count < 0:
            raise ValueError("maximum_baseline_mad_count must not be negative")
        if any(not 0 <= value < 48 * 64 for value in self.known_bad_source_indices):
            raise ValueError("known bad source indexes must fit the 48x64 matrix")


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

    The raw immutable frames remain untouched.  When a baseline identifies a small,
    isolated set of bad cells, only the separate processing matrix is repaired by the
    mean of four orthogonal neighbours before zero correction and V1 force conversion.
    """

    def __init__(
        self,
        *,
        baseline_reference: BaselineReference,
        policy: BadPointPolicy = BadPointPolicy(),
        adapter: DoP4864StandardizationAdapter | None = None,
    ) -> None:
        self._adapter = adapter or DoP4864StandardizationAdapter.observed_compact_8bit()
        if baseline_reference.layout_digest != self._adapter.layout.digest:
            raise ValueError("baseline reference does not match the DO-P4864 layout")
        if len(baseline_reference.zero_offset_count) != 48 * 64:
            raise ValueError("baseline reference must contain 48x64 values")
        self._baseline_reference = baseline_reference
        self._policy = policy

    def evaluate(
        self, *, session_id: str, frames: tuple[RawFrame, ...]
    ) -> HardwareQualityEvaluation:
        if not frames:
            return self._invalid("NO_CAPTURED_FRAMES")
        if any(frame.values.shape != (48, 64) or frame.values.dtype != np.uint8 for frame in frames):
            return self._invalid("UNSUPPORTED_RAW_FRAME_FORMAT")

        bad = set(self._policy.known_bad_source_indices)
        bad.update(
            index
            for index, mad in enumerate(self._baseline_reference.noise_mad_count)
            if mad > self._policy.maximum_baseline_mad_count
        )
        repairability_error = self._repairability_error(bad)
        if repairability_error is not None:
            return self._invalid(repairability_error)

        processing = self._repair_frames(frames, bad) if bad else None
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
            repaired_source_indices=tuple(sorted(bad)),
            physical_session=outcome.session,
            processing_metadata={
                "baseline_window_id": self._baseline_reference.baseline_window_id,
                "baseline_rules_version": self._baseline_reference.rules_version,
                "baseline_threshold_version": self._baseline_reference.threshold_version,
                "bad_point_policy_version": self._policy.version,
                "repaired_source_indices": sorted(bad),
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

    def _repairability_error(self, bad: set[int]) -> str | None:
        if len(bad) > self._policy.maximum_bad_cells:
            return "TOO_MANY_PERSISTENT_BAD_CELLS"
        for source_index in bad:
            row, column = self._row_column(source_index)
            if row in {0, 47} or column in {0, 63}:
                return "BAD_CELL_CANNOT_BE_REPAIRED_AT_BOARD_EDGE"
            for neighbour in self._eight_neighbours(row, column):
                if self._source_index(*neighbour) in bad:
                    return "ADJACENT_BAD_CELL_CLUSTER"
        return None

    @staticmethod
    def _row_column(source_index: int) -> tuple[int, int]:
        return source_index % 48, source_index // 48

    @staticmethod
    def _source_index(row: int, column: int) -> int:
        return row + 48 * column

    @staticmethod
    def _eight_neighbours(row: int, column: int) -> tuple[tuple[int, int], ...]:
        return tuple(
            (row_delta, column_delta)
            for row_delta in range(row - 1, row + 2)
            for column_delta in range(column - 1, column + 2)
            if (row_delta, column_delta) != (row, column)
            and 0 <= row_delta < 48
            and 0 <= column_delta < 64
        )

    def _repair_frames(
        self, frames: tuple[RawFrame, ...], bad: set[int]
    ) -> tuple[np.ndarray, ...]:
        repaired: list[np.ndarray] = []
        for frame in frames:
            matrix = frame.values.astype(np.float64, copy=True)
            for source_index in bad:
                row, column = self._row_column(source_index)
                neighbours = (
                    matrix[row - 1, column],
                    matrix[row + 1, column],
                    matrix[row, column - 1],
                    matrix[row, column + 1],
                )
                matrix[row, column] = float(sum(neighbours) / len(neighbours))
            matrix.setflags(write=False)
            repaired.append(matrix)
        return tuple(repaired)

    @staticmethod
    def _invalid(reason: str) -> HardwareQualityEvaluation:
        return HardwareQualityEvaluation(HardwareDataValidity.INVALID, (reason,))
