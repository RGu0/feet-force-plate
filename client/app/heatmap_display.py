"""Display-only refinement for the live 48×64 heatmap.

This module deliberately has no device, storage, workflow, analysis, or report
dependencies.  It turns an immutable display-frame copy into a calmer raster
for the Qt widget; it is never a measurement-processing path.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter, label


_SHAPE = (48, 64)
_CARDINAL_STRUCTURE = np.asarray(
    ((0, 1, 0), (1, 1, 1), (0, 1, 0)), dtype=np.uint8
)


@dataclass(frozen=True, slots=True)
class HeatmapDisplayConfig:
    """Safe, centralized visual-only controls for fixture and device tuning."""

    enabled: bool = True
    temporal_window: int = 3
    hampel_scale: float = 3.5
    mad_scale: float = 1.4826
    p99_relative_threshold: float = 0.08
    high_neighbor_ratio: float = 0.5
    island_max_pixels: int = 2
    gamma: float = 0.75
    gaussian_sigma: float = 0.9

    def __post_init__(self) -> None:
        if self.temporal_window < 1:
            raise ValueError("temporal_window must be positive")
        if self.hampel_scale <= 0 or self.mad_scale <= 0:
            raise ValueError("Hampel scales must be positive")
        if not 0 < self.p99_relative_threshold <= 1:
            raise ValueError("p99_relative_threshold must be within (0, 1]")
        if not 0 < self.high_neighbor_ratio <= 1:
            raise ValueError("high_neighbor_ratio must be within (0, 1]")
        if self.island_max_pixels < 0:
            raise ValueError("island_max_pixels must not be negative")
        if self.gamma <= 0 or self.gaussian_sigma < 0:
            raise ValueError("gamma must be positive and gaussian_sigma non-negative")


class HeatmapDisplayRefiner:
    """Own the latest three display copies and refine only their visual output."""

    def __init__(self, config: HeatmapDisplayConfig | None = None) -> None:
        self.config = config or HeatmapDisplayConfig()
        self._history: deque[NDArray[np.float64]] = deque(
            maxlen=self.config.temporal_window
        )

    def refine(
        self, values: tuple[tuple[float, ...], ...]
    ) -> tuple[tuple[float, ...], ...]:
        """Return a separate render matrix while leaving ``values`` untouched."""
        current = _copied_matrix(values)
        if not self.config.enabled:
            return _as_tuple(current)
        if not np.any(current > 0):
            # Never preserve a ghost footprint merely because the two preceding
            # display frames had contact.
            self._history.clear()
            return _as_tuple(np.zeros(_SHAPE, dtype=np.float64))

        self._history.append(current.copy())
        temporal = np.median(np.stack(tuple(self._history)), axis=0)
        cleaned = _conditional_hampel(temporal, self.config)
        contact, repaired = _clean_contact(cleaned, self.config)
        normalized = _robust_normalize(repaired, contact)
        gamma_corrected = np.power(normalized, self.config.gamma)
        blurred = gaussian_filter(
            gamma_corrected,
            sigma=self.config.gaussian_sigma,
            mode="nearest",
        )
        # Gaussian smoothing makes the raster continuous *inside* actual
        # contact only; it is never allowed to grow a new foot outline.
        return _as_tuple(np.where(contact, blurred, 0.0))


def _copied_matrix(values: tuple[tuple[float, ...], ...]) -> NDArray[np.float64]:
    matrix = np.array(values, dtype=np.float64, copy=True)
    if matrix.shape != _SHAPE:
        raise ValueError("display heatmap must be 48×64")
    if not np.all(np.isfinite(matrix)) or np.any(matrix < 0):
        raise ValueError("display heatmap values must be finite and non-negative")
    return matrix


def _conditional_hampel(
    values: NDArray[np.float64], config: HeatmapDisplayConfig
) -> NDArray[np.float64]:
    """Replace only isolated highs and enclosed single-cell lows."""
    source = values.copy()
    result = values.copy()
    p99 = _nonzero_p99(source)
    if p99 <= 0:
        return np.zeros_like(source)
    floor = config.p99_relative_threshold * p99
    height, width = source.shape
    for row in range(height):
        for column in range(width):
            neighbors = _neighbor_values(source, row, column)
            if not len(neighbors):
                continue
            median = float(np.median(neighbors))
            mad = float(np.median(np.abs(neighbors - median)))
            threshold = max(config.hampel_scale * config.mad_scale * mad, floor)
            value = float(source[row, column])
            if abs(value - median) <= threshold:
                continue
            if value > median:
                # A genuinely compact high-pressure region has immediate peers;
                # an isolated hot pixel does not.
                supported = np.count_nonzero(
                    neighbors >= value * config.high_neighbor_ratio
                )
                if supported == 0:
                    result[row, column] = median
            elif median > 0 and _is_enclosed_low(source, row, column, median, config):
                result[row, column] = median
    return result


def _neighbor_values(
    values: NDArray[np.float64], row: int, column: int
) -> NDArray[np.float64]:
    top, bottom = max(0, row - 1), min(values.shape[0], row + 2)
    left, right = max(0, column - 1), min(values.shape[1], column + 2)
    region = values[top:bottom, left:right].copy()
    region[row - top, column - left] = np.nan
    return region[np.isfinite(region)]


def _is_enclosed_low(
    values: NDArray[np.float64],
    row: int,
    column: int,
    median: float,
    config: HeatmapDisplayConfig,
) -> bool:
    if row == 0 or column == 0 or row == values.shape[0] - 1 or column == values.shape[1] - 1:
        return False
    cardinal = (
        values[row - 1, column],
        values[row + 1, column],
        values[row, column - 1],
        values[row, column + 1],
    )
    return all(value >= median * config.high_neighbor_ratio for value in cardinal)


def _clean_contact(
    values: NDArray[np.float64], config: HeatmapDisplayConfig
) -> tuple[NDArray[np.bool_], NDArray[np.float64]]:
    mask = values > 0
    labels, component_count = label(mask, structure=_CARDINAL_STRUCTURE)
    for component in range(1, component_count + 1):
        if np.count_nonzero(labels == component) <= config.island_max_pixels:
            mask[labels == component] = False

    repaired = np.where(mask, values, 0.0)
    for row in range(1, values.shape[0] - 1):
        for column in range(1, values.shape[1] - 1):
            if mask[row, column] or not _surrounded_by_contact(mask, row, column):
                continue
            neighbors = _neighbor_values(values, row, column)
            positive = neighbors[neighbors > 0]
            if len(positive):
                mask[row, column] = True
                repaired[row, column] = float(np.median(positive))
    return mask, repaired


def _surrounded_by_contact(mask: NDArray[np.bool_], row: int, column: int) -> bool:
    return bool(
        mask[row - 1, column]
        and mask[row + 1, column]
        and mask[row, column - 1]
        and mask[row, column + 1]
    )


def _robust_normalize(
    values: NDArray[np.float64], mask: NDArray[np.bool_]
) -> NDArray[np.float64]:
    p99 = _nonzero_p99(values[mask])
    if p99 <= 0:
        return np.zeros_like(values)
    return np.clip(values / p99, 0.0, 1.0)


def _nonzero_p99(values: NDArray[np.float64]) -> float:
    nonzero = values[values > 0]
    return 0.0 if not len(nonzero) else float(np.percentile(nonzero, 99))


def _as_tuple(values: NDArray[np.float64]) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in values)
