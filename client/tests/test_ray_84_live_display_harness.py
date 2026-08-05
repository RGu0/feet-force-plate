from scripts import run_dop4864_live_display_validation


def test_live_display_harness_uses_active_hardware_geometry() -> None:
    """Catch stale script calls to the removed device-specification overlay API."""

    grid = run_dop4864_live_display_validation.live_physical_grid()

    assert (grid.rows, grid.columns) == (48, 64)
    assert grid.specification_id == "do-p4864/1.0"
