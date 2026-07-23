from __future__ import annotations

import pytest

from client.hardware_standardization.spatial_integration import integrate_regular_grid_force


def test_regular_grid_integrates_interpolated_pressure_over_sensor_gaps() -> None:
    result = integrate_regular_grid_force(
        force_n=(1.0, 1.0, 1.0, 1.0),
        active=(True, True, True, True),
        rows=2,
        columns=2,
        pitch_x_mm=2.0,
        pitch_y_mm=3.0,
        sensor_area_mm2=1.0,
    )

    assert result.integrated_force_n == pytest.approx(6.0)
    assert result.active_sensor_count == 4


def test_inactive_points_are_zero_pressure_boundaries_not_force_contributors() -> None:
    result = integrate_regular_grid_force(
        force_n=(1.0, 1.0, 1.0, 1.0),
        active=(True, False, False, False),
        rows=2,
        columns=2,
        pitch_x_mm=2.0,
        pitch_y_mm=3.0,
        sensor_area_mm2=1.0,
    )

    assert result.integrated_force_n == pytest.approx(1.5)
    assert result.active_sensor_count == 1
