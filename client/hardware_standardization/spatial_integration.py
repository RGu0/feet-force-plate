"""Area integration of an interpolated pressure field for hardware calibration."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np


@dataclass(frozen=True, slots=True)
class SpatialForceIntegration:
    integrated_force_n: float
    active_sensor_count: int
    average_active_sensor_pressure_n_per_mm2: float | None


def integrate_regular_grid_force(
    *,
    force_n: tuple[float, ...],
    active: tuple[bool, ...],
    rows: int,
    columns: int,
    pitch_x_mm: float,
    pitch_y_mm: float,
    sensor_area_mm2: float,
) -> SpatialForceIntegration:
    """Integrate bilinearly interpolated pressure, with inactive nodes fixed at zero."""

    expected_count = rows * columns
    if rows < 2 or columns < 2:
        raise ValueError("regular pressure integration requires at least a 2x2 grid")
    if len(force_n) != expected_count or len(active) != expected_count:
        raise ValueError("force and active vectors must match regular-grid point count")
    if any(not isfinite(value) or value < 0 for value in force_n):
        raise ValueError("force values must be finite and non-negative")
    if min(pitch_x_mm, pitch_y_mm, sensor_area_mm2) <= 0:
        raise ValueError("grid pitches and sensor area must be positive")

    force = np.asarray(force_n, dtype=np.float64).reshape((rows, columns), order="F")
    active_mask = np.asarray(active, dtype=bool).reshape((rows, columns), order="F")
    pressure = np.where(active_mask, force / sensor_area_mm2, 0.0)
    integrated = float(
        np.trapezoid(
            np.trapezoid(pressure, dx=pitch_x_mm, axis=1),
            dx=pitch_y_mm,
            axis=0,
        )
    )
    active_count = int(active_mask.sum())
    return SpatialForceIntegration(
        integrated_force_n=integrated,
        active_sensor_count=active_count,
        average_active_sensor_pressure_n_per_mm2=(
            None if active_count == 0 else float(pressure[active_mask].mean())
        ),
    )
