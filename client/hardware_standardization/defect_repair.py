"""Device-layout-neutral, pre-interpolation sensor-defect repair.

Raw hardware samples are never modified.  This module produces a separate
matrix and repair mask suitable for the standardized hardware-derived stream
consumed by both algorithms and display.  It intentionally does not know
about COP, reports, Qt, serial transport, or a particular sensor size.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray


class SensorRepairMethod(StrEnum):
    ISOLATED_SPATIAL_MEDIAN = "ISOLATED_SPATIAL_MEDIAN"
    HORIZONTAL_LINE_DIRECTIONAL_INTERPOLATION = (
        "HORIZONTAL_LINE_DIRECTIONAL_INTERPOLATION"
    )
    VERTICAL_LINE_DIRECTIONAL_INTERPOLATION = (
        "VERTICAL_LINE_DIRECTIONAL_INTERPOLATION"
    )


@dataclass(frozen=True, slots=True)
class SensorDefectRepairPolicy:
    """Versioned, conservative rules for repairable board-local defects."""

    version: str = "sensor-defect-repair/generic-grid/2"
    median_window: int = 3
    maximum_isolated_bad_cells: int = 2
    line_minimum_supported_cells: int = 8
    line_missing_ratio: float = 0.85
    line_support_relative_threshold: float = 0.08
    line_minimum_persistent_frames: int = 3
    maximum_persistent_lines: int = 1
    maximum_repaired_fraction_per_frame: float = 0.03

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("repair policy version is required")
        if self.median_window not in (3, 5):
            raise ValueError("median_window must be 3 or 5")
        if self.maximum_isolated_bad_cells < 0:
            raise ValueError("maximum_isolated_bad_cells must not be negative")
        if self.line_minimum_supported_cells < 1:
            raise ValueError("line_minimum_supported_cells must be positive")
        if not 0 < self.line_missing_ratio <= 1:
            raise ValueError("line_missing_ratio must be within (0, 1]")
        if not 0 < self.line_support_relative_threshold <= 1:
            raise ValueError("line_support_relative_threshold must be within (0, 1]")
        if self.line_minimum_persistent_frames < 1:
            raise ValueError("line_minimum_persistent_frames must be positive")
        if self.maximum_persistent_lines < 0:
            raise ValueError("maximum_persistent_lines must not be negative")
        if not 0 < self.maximum_repaired_fraction_per_frame <= 1:
            raise ValueError("maximum_repaired_fraction_per_frame must be within (0, 1]")


@dataclass(frozen=True, slots=True)
class RepairedSensorFrame:
    """Derived one-frame data; all arrays are immutable display/algorithm input."""

    values: NDArray[np.float64]
    repair_mask: NDArray[np.bool_]
    methods: NDArray[np.object_]


@dataclass(frozen=True, slots=True)
class SensorDefectRepairResult:
    """A complete session-level repair decision with audit-friendly summaries."""

    frames: tuple[RepairedSensorFrame, ...]
    persistent_missing_rows: tuple[int, ...]
    persistent_missing_columns: tuple[int, ...]
    method_counts: tuple[tuple[str, int], ...]
    reasons: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.reasons

    @property
    def any_repairs(self) -> bool:
        return any(np.any(frame.repair_mask) for frame in self.frames)


def repair_sensor_defects(
    matrices: tuple[NDArray[np.number], ...],
    *,
    known_bad_cells: frozenset[tuple[int, int]] = frozenset(),
    policy: SensorDefectRepairPolicy = SensorDefectRepairPolicy(),
) -> SensorDefectRepairResult:
    """Repair only high-confidence defects before baseline/analysis/display.

    ``known_bad_cells`` is supplied by baseline/diagnostic evidence.  Dynamic
    single-line repairs require the same defect signature in several frames:
    a large fraction of a row (or column) is low while immediate opposite-side
    neighbours are supported.  A line cell is restored by pairwise directional
    interpolation across the defect, with a median across the available pairs.
    Natural contours, sparse gaps, boundaries and multi-line defects therefore
    remain unmodified or invalidate the session.
    """
    source = _validate_matrices(matrices)
    shape = source[0].shape
    isolated_error = _isolated_repairability_error(known_bad_cells, shape, policy)
    if isolated_error is not None:
        return _invalid(source, isolated_error)

    static_frames = tuple(
        _repair_known_isolated_cells(matrix, known_bad_cells, policy)
        for matrix in source
    )
    row_candidates = _persistent_line_indices(
        static_frames, axis=0, policy=policy
    )
    column_candidates = _persistent_line_indices(
        static_frames, axis=1, policy=policy
    )
    if len(row_candidates) + len(column_candidates) > policy.maximum_persistent_lines:
        return _invalid(source, "TOO_MANY_PERSISTENT_DEFECT_LINES")

    repaired_frames = tuple(
        _repair_detected_lines(
            frame,
            rows=row_candidates,
            columns=column_candidates,
            policy=policy,
        )
        for frame in static_frames
    )
    if any(
        np.count_nonzero(frame.repair_mask) / frame.repair_mask.size
        > policy.maximum_repaired_fraction_per_frame
        for frame in repaired_frames
    ):
        return _invalid(source, "EXCESSIVE_SENSOR_REPAIR_COVERAGE")
    counts = Counter(
        str(method)
        for frame in repaired_frames
        for method in frame.methods[frame.repair_mask]
    )
    return SensorDefectRepairResult(
        frames=repaired_frames,
        persistent_missing_rows=row_candidates,
        persistent_missing_columns=column_candidates,
        method_counts=tuple(sorted(counts.items())),
    )


def _validate_matrices(
    matrices: tuple[NDArray[np.number], ...]
) -> tuple[NDArray[np.float64], ...]:
    if not matrices:
        raise ValueError("at least one matrix is required")
    copied = tuple(np.array(matrix, dtype=np.float64, copy=True) for matrix in matrices)
    shape = copied[0].shape
    if len(shape) != 2 or min(shape) < 3:
        raise ValueError("sensor matrices must be two-dimensional and at least 3x3")
    if any(matrix.shape != shape for matrix in copied):
        raise ValueError("sensor matrices must share a shape")
    if any(not np.all(np.isfinite(matrix)) or np.any(matrix < 0) for matrix in copied):
        raise ValueError("sensor matrices must be finite and non-negative")
    return copied


def _isolated_repairability_error(
    bad: frozenset[tuple[int, int]],
    shape: tuple[int, int],
    policy: SensorDefectRepairPolicy,
) -> str | None:
    if len(bad) > policy.maximum_isolated_bad_cells:
        return "TOO_MANY_PERSISTENT_BAD_CELLS"
    radius = policy.median_window // 2
    for row, column in bad:
        if not 0 <= row < shape[0] or not 0 <= column < shape[1]:
            return "BAD_CELL_OUTSIDE_DECLARED_LAYOUT"
        if (
            row < radius
            or row >= shape[0] - radius
            or column < radius
            or column >= shape[1] - radius
        ):
            return "BAD_CELL_CANNOT_BE_REPAIRED_AT_BOARD_EDGE"
    for row, column in bad:
        if any(
            (neighbour_row, neighbour_column) in bad
            for neighbour_row in range(row - 1, row + 2)
            for neighbour_column in range(column - 1, column + 2)
            if (neighbour_row, neighbour_column) != (row, column)
        ):
            return "ADJACENT_BAD_CELL_CLUSTER"
    return None


def _empty_frame(values: NDArray[np.float64]) -> RepairedSensorFrame:
    methods = np.full(values.shape, None, dtype=object)
    copied_values = values.copy()
    mask = np.zeros(values.shape, dtype=bool)
    copied_values.setflags(write=False)
    mask.setflags(write=False)
    methods.setflags(write=False)
    return RepairedSensorFrame(
        values=copied_values,
        repair_mask=mask,
        methods=methods,
    )


def _repair_known_isolated_cells(
    values: NDArray[np.float64],
    bad: frozenset[tuple[int, int]],
    policy: SensorDefectRepairPolicy,
) -> RepairedSensorFrame:
    result = _empty_frame(values)
    repaired_values = result.values.copy()
    repair_mask = result.repair_mask.copy()
    methods = result.methods.copy()
    radius = policy.median_window // 2
    for row, column in bad:
        window = values[row - radius : row + radius + 1, column - radius : column + radius + 1]
        neighbours = np.delete(window.reshape(-1), radius * policy.median_window + radius)
        repaired_values[row, column] = float(np.median(neighbours))
        repair_mask[row, column] = True
        methods[row, column] = SensorRepairMethod.ISOLATED_SPATIAL_MEDIAN
    repaired_values.setflags(write=False)
    repair_mask.setflags(write=False)
    methods.setflags(write=False)
    return RepairedSensorFrame(repaired_values, repair_mask, methods)


def _persistent_line_indices(
    frames: tuple[RepairedSensorFrame, ...],
    *,
    axis: int,
    policy: SensorDefectRepairPolicy,
) -> tuple[int, ...]:
    candidates = Counter()
    for frame in frames:
        for index in _line_candidates(frame.values, axis=axis, policy=policy):
            candidates[index] += 1
    return tuple(
        sorted(
            index
            for index, count in candidates.items()
            if count >= policy.line_minimum_persistent_frames
        )
    )


def _line_candidates(
    values: NDArray[np.float64], *, axis: int, policy: SensorDefectRepairPolicy
) -> tuple[int, ...]:
    threshold = _nonzero_p99(values) * policy.line_support_relative_threshold
    if threshold <= 0:
        return ()
    limit = values.shape[axis]
    candidates: list[int] = []
    for index in range(1, limit - 1):
        if axis == 0:
            supported = (values[index - 1] >= threshold) & (values[index + 1] >= threshold)
            missing = supported & (values[index] < threshold)
        else:
            supported = (
                (values[:, index - 1] >= threshold)
                & (values[:, index + 1] >= threshold)
            )
            missing = supported & (values[:, index] < threshold)
        supported_count = int(np.count_nonzero(supported))
        if (
            supported_count >= policy.line_minimum_supported_cells
            and np.count_nonzero(missing) / supported_count >= policy.line_missing_ratio
        ):
            candidates.append(index)
    return tuple(candidates)


def _repair_detected_lines(
    frame: RepairedSensorFrame,
    *,
    rows: tuple[int, ...],
    columns: tuple[int, ...],
    policy: SensorDefectRepairPolicy,
) -> RepairedSensorFrame:
    values = frame.values.copy()
    mask = frame.repair_mask.copy()
    methods = frame.methods.copy()
    threshold = _nonzero_p99(values) * policy.line_support_relative_threshold
    if threshold <= 0:
        return RepairedSensorFrame(values, mask, methods)
    radius = policy.median_window // 2
    for row in rows:
        if row < radius or row >= values.shape[0] - radius:
            continue
        supported = (values[row - 1] >= threshold) & (values[row + 1] >= threshold)
        missing = supported & (values[row] < threshold)
        if not _is_current_line_defect(supported, missing, policy):
            continue
        for column in np.flatnonzero(missing):
            interpolated = _robust_directional_interpolation(
                values[row - radius : row + radius + 1, column],
                centre=radius,
                threshold=threshold,
            )
            if interpolated is None:
                continue
            values[row, column] = interpolated
            mask[row, column] = True
            methods[row, column] = (
                SensorRepairMethod.HORIZONTAL_LINE_DIRECTIONAL_INTERPOLATION
            )
    for column in columns:
        if column < radius or column >= values.shape[1] - radius:
            continue
        supported = (values[:, column - 1] >= threshold) & (values[:, column + 1] >= threshold)
        missing = supported & (values[:, column] < threshold)
        if not _is_current_line_defect(supported, missing, policy):
            continue
        for row in np.flatnonzero(missing):
            interpolated = _robust_directional_interpolation(
                values[row, column - radius : column + radius + 1],
                centre=radius,
                threshold=threshold,
            )
            if interpolated is None:
                continue
            values[row, column] = interpolated
            mask[row, column] = True
            methods[row, column] = (
                SensorRepairMethod.VERTICAL_LINE_DIRECTIONAL_INTERPOLATION
            )
    values.setflags(write=False)
    mask.setflags(write=False)
    methods.setflags(write=False)
    return RepairedSensorFrame(values, mask, methods)


def _is_current_line_defect(
    supported: NDArray[np.bool_], missing: NDArray[np.bool_], policy: SensorDefectRepairPolicy
) -> bool:
    supported_count = int(np.count_nonzero(supported))
    return (
        supported_count >= policy.line_minimum_supported_cells
        and np.count_nonzero(missing) / supported_count >= policy.line_missing_ratio
    )


def _robust_directional_interpolation(
    window: NDArray[np.float64], *, centre: int, threshold: float
) -> float | None:
    """Interpolate across a one-cell defect, robustly when a 5-wide window is used.

    Each opposite-side pair provides a linear estimate at the missing cell.
    The median of these estimates keeps a single noisy neighbour from skewing
    the result.  We deliberately never interpolate from a one-sided window:
    that would extend a true contact edge into an unmeasured area.
    """
    estimates = [
        (float(window[centre - distance]) + float(window[centre + distance])) / 2.0
        for distance in range(1, min(centre, len(window) - centre - 1) + 1)
        if window[centre - distance] >= threshold
        and window[centre + distance] >= threshold
    ]
    return None if not estimates else float(np.median(estimates))


def _nonzero_p99(values: NDArray[np.float64]) -> float:
    nonzero = values[values > 0]
    return 0.0 if not len(nonzero) else float(np.percentile(nonzero, 99))


def _invalid(
    source: tuple[NDArray[np.float64], ...], reason: str
) -> SensorDefectRepairResult:
    frames = tuple(_empty_frame(matrix) for matrix in source)
    return SensorDefectRepairResult(
        frames=frames,
        persistent_missing_rows=(),
        persistent_missing_columns=(),
        method_counts=(),
        reasons=(reason,),
    )
