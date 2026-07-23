from __future__ import annotations

import pytest

from client.hardware_standardization.geometry import BoardCoordinateLayout


def test_top_left_grid_uses_user_confirmed_pitch_and_column_major_source_order() -> None:
    layout = BoardCoordinateLayout.top_left_grid(
        rows=48,
        columns=64,
        pitch_x_mm=7.99,
        pitch_y_mm=7.99,
        geometry_version="do-p4864-board/1",
        nominal_active_area_mm2=36.0,
    )

    assert layout.coordinate_frame == "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"
    assert layout.cells[0].board_x_mm == 0.0
    assert layout.cells[0].board_y_mm == 0.0
    point_99 = layout.cell_by_source_index(99)
    assert point_99.board_x_mm == pytest.approx(15.98)
    assert point_99.board_y_mm == pytest.approx(23.97)
    assert layout.cells[-1].board_x_mm == pytest.approx(503.37)
    assert layout.cells[-1].board_y_mm == pytest.approx(375.53)


def test_irregular_layout_accepts_explicit_mirrored_coordinates_without_transforming_them() -> None:
    layout = BoardCoordinateLayout.from_cells(
        geometry_version="irregular-fixture/1",
        cells=(
            ("left", 7, 100.0, 0.0, 20.0),
            ("right", 3, 0.0, 0.0, 12.0),
        ),
    )

    assert tuple(cell.source_index for cell in layout.cells) == (3, 7)
    assert layout.cell_by_source_index(7).board_x_mm == 100.0
