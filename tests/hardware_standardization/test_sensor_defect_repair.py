from __future__ import annotations

from pathlib import Path

import numpy as np
from client.hardware_standardization.defect_repair import (
    SensorDefectRepairPolicy,
    SensorRepairMethod,
    repair_sensor_defects,
)


def _frames(values: np.ndarray, count: int = 3) -> tuple[np.ndarray, ...]:
    return tuple(values.copy() for _ in range(count))


def test_isolated_bad_cell_uses_spatial_median_without_mutating_input() -> None:
    values = np.full((9, 11), 10.0)
    values[4, 5] = 255.0
    before = values.copy()

    result = repair_sensor_defects(
        _frames(values), known_bad_cells=frozenset({(4, 5)})
    )

    assert result.valid
    assert result.frames[0].values[4, 5] == 10.0
    assert result.frames[0].repair_mask[4, 5]
    assert result.frames[0].methods[4, 5] is SensorRepairMethod.ISOLATED_SPATIAL_MEDIAN
    assert np.array_equal(values, before)


def test_single_horizontal_drop_line_uses_pre_interpolation_directional_interpolation() -> None:
    values = np.zeros((13, 17), dtype=np.float64)
    values[3:10, 2:15] = 100.0
    values[6, 2:15] = 0.0

    result = repair_sensor_defects(
        _frames(values, count=1),
        policy=SensorDefectRepairPolicy(maximum_repaired_fraction_per_frame=0.1),
    )

    assert result.valid
    assert result.detected_missing_rows_per_frame == ((6,),)
    assert result.detected_missing_columns_per_frame == ((),)
    assert result.persistent_missing_rows == ()
    assert np.all(result.frames[0].values[6, 2:15] == 100.0)
    assert np.all(result.frames[0].repair_mask[6, 2:15])
    assert {
        method
        for method in result.frames[0].methods[6, 2:15]
    } == {SensorRepairMethod.HORIZONTAL_LINE_DIRECTIONAL_INTERPOLATION}
    assert not np.any(result.frames[0].repair_mask[2])
    assert not np.any(result.frames[0].repair_mask[10])


def test_single_vertical_drop_line_uses_pre_interpolation_row_median_window_five() -> None:
    values = np.zeros((13, 17), dtype=np.float64)
    values[2:11, 4:13] = 100.0
    values[2:11, 8] = 0.0

    result = repair_sensor_defects(
        _frames(values, count=1),
        policy=SensorDefectRepairPolicy(
            median_window=5,
            maximum_repaired_fraction_per_frame=0.1,
        ),
    )

    assert result.valid
    assert result.detected_missing_columns_per_frame == ((8,),)
    assert result.persistent_missing_columns == ()
    assert np.all(result.frames[0].values[2:11, 8] == 100.0)
    assert np.all(result.frames[0].repair_mask[2:11, 8])


def test_directional_interpolation_preserves_a_cross_line_gradient() -> None:
    values = np.zeros((13, 17), dtype=np.float64)
    values[3, 2:15] = 10.0
    values[4, 2:15] = 30.0
    values[5, 2:15] = 50.0
    values[6, 2:15] = 0.0
    values[7, 2:15] = 90.0
    values[8, 2:15] = 110.0
    values[9, 2:15] = 130.0

    result = repair_sensor_defects(
        _frames(values, count=1),
        policy=SensorDefectRepairPolicy(maximum_repaired_fraction_per_frame=0.1),
    )

    assert result.valid
    assert np.all(result.frames[0].values[6, 2:15] == 70.0)


def test_sparse_gap_is_not_repaired_as_a_sensor_line() -> None:
    values = np.zeros((13, 17), dtype=np.float64)
    values[3:10, 2:15] = 100.0
    values[6, 2:7] = 0.0

    result = repair_sensor_defects(_frames(values, count=1))

    assert result.valid
    assert result.persistent_missing_rows == ()
    assert not np.any(result.frames[0].repair_mask)


def test_one_sided_contact_edge_is_not_repaired_as_a_sensor_line() -> None:
    values = np.zeros((13, 17), dtype=np.float64)
    values[3:6, 2:15] = 100.0

    result = repair_sensor_defects(_frames(values, count=1))

    assert result.valid
    assert result.detected_missing_rows_per_frame == ((),)
    assert not np.any(result.frames[0].repair_mask)


def test_edge_cluster_multi_line_and_excessive_coverage_are_rejected() -> None:
    values = np.full((13, 17), 100.0)
    edge = repair_sensor_defects(_frames(values), known_bad_cells=frozenset({(0, 4)}))
    cluster = repair_sensor_defects(
        _frames(values), known_bad_cells=frozenset({(4, 4), (4, 5)})
    )
    values[4, :] = 0.0
    values[8, :] = 0.0
    multi_line = repair_sensor_defects(_frames(values, count=1))

    assert edge.reasons == ("BAD_CELL_CANNOT_BE_REPAIRED_AT_BOARD_EDGE",)
    assert cluster.reasons == ("ADJACENT_BAD_CELL_CLUSTER",)
    assert multi_line.reasons == ("TOO_MANY_SENSOR_DEFECT_LINES_IN_FRAME",)


def test_single_line_over_the_declared_repair_coverage_limit_is_rejected() -> None:
    values = np.zeros((13, 17), dtype=np.float64)
    values[3:10, 2:15] = 100.0
    values[6, 2:15] = 0.0

    result = repair_sensor_defects(_frames(values, count=1))

    assert result.reasons == ("EXCESSIVE_SENSOR_REPAIR_COVERAGE",)


def test_saved_tandem_reference_replays_a_persistent_horizontal_line_before_display_scaling() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "tests/fixtures/device/dop4864_reference_protocol_v1/reference-poses.npz"
    )
    with np.load(fixture_path, allow_pickle=False) as fixture:
        source = fixture["tandem_left_front"]
        source_before = source.copy()
        result = repair_sensor_defects(tuple(frame for frame in source))

    assert result.valid
    assert result.persistent_missing_rows == (27,)
    assert not result.persistent_missing_columns
    assert result.any_repairs
    repaired = result.frames[0]
    repaired_columns = np.flatnonzero(repaired.repair_mask[27])
    assert len(repaired_columns) >= 8
    assert np.all(repaired.values[27, repaired_columns] > 0)
    assert np.array_equal(source, source_before)
