from __future__ import annotations

import numpy as np
import pytest

from client.app.heatmap_display import HeatmapDisplayConfig, HeatmapDisplayRefiner


def _as_tuple(values: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in values)


def _contact_cluster() -> np.ndarray:
    values = np.zeros((48, 64), dtype=np.float64)
    values[20:25, 26:31] = 0.7
    return values


def test_refiner_removes_a_single_high_outlier_without_spreading_it() -> None:
    values = _contact_cluster()
    values[5, 5] = 1.0

    refined = np.asarray(HeatmapDisplayRefiner().refine(_as_tuple(values)))

    assert refined.shape == (48, 64)
    assert refined[5, 5] == pytest.approx(0.0)
    assert np.max(refined[4:7, 4:7]) == pytest.approx(0.0)
    assert np.max(refined[20:25, 26:31]) > 0.0


def test_refiner_fills_a_single_low_hole_inside_contact() -> None:
    values = _contact_cluster()
    values[22, 28] = 0.0

    refined = np.asarray(HeatmapDisplayRefiner().refine(_as_tuple(values)))

    assert refined[22, 28] > 0.0


def test_refiner_preserves_a_two_by_two_high_pressure_cluster() -> None:
    values = np.zeros((48, 64), dtype=np.float64)
    values[15:17, 24:26] = 1.0

    refined = np.asarray(HeatmapDisplayRefiner().refine(_as_tuple(values)))

    assert np.count_nonzero(refined[15:17, 24:26]) == 4
    assert np.max(refined) > 0.0


def test_refiner_keeps_an_empty_current_frame_empty_after_contact_history() -> None:
    refiner = HeatmapDisplayRefiner()
    refiner.refine(_as_tuple(_contact_cluster()))

    refined = np.asarray(refiner.refine(_as_tuple(np.zeros((48, 64)))))

    assert not np.any(refined)


def test_refiner_uses_the_recent_three_frame_median_for_transient_large_noise() -> None:
    refiner = HeatmapDisplayRefiner()
    baseline = _contact_cluster()
    refiner.refine(_as_tuple(baseline))
    refiner.refine(_as_tuple(baseline))
    transient = baseline.copy()
    transient[5:8, 5:8] = 1.0

    refined = np.asarray(refiner.refine(_as_tuple(transient)))

    assert not np.any(refined[5:8, 5:8])


def test_refiner_copies_source_matrix_and_never_mutates_it() -> None:
    values = _contact_cluster()
    values[5, 5] = 1.0
    before = values.copy()

    HeatmapDisplayRefiner().refine(_as_tuple(values))

    assert np.array_equal(values, before)


def test_disabled_refiner_returns_a_separate_unmodified_display_copy() -> None:
    values = _contact_cluster()
    values[5, 5] = 1.0

    refined = HeatmapDisplayRefiner(
        HeatmapDisplayConfig(enabled=False)
    ).refine(_as_tuple(values))

    assert refined == _as_tuple(values)
