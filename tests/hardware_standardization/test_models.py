from __future__ import annotations

import pytest

from client.hardware_standardization.models import (
    CellStatus,
    FrameQuality,
    MeasurementProfile,
    MeasurementUncertainty,
    PhysicalArrayCell,
    PhysicalArrayFrame,
    PhysicalArraySession,
)


def _cell(cell_id: str, source_index: int, x_mm: float, y_mm: float) -> PhysicalArrayCell:
    return PhysicalArrayCell(
        cell_id=cell_id,
        source_index=source_index,
        board_x_mm=x_mm,
        board_y_mm=y_mm,
        nominal_active_area_mm2=36.0,
        status=CellStatus.ACTIVE,
    )


def _profile() -> MeasurementProfile:
    return MeasurementProfile(
        profile_version="physical-array-profile/1",
        geometry_validation="USER_CONFIRMED",
        baseline_validation="VALIDATED",
        force_validation="UNVALIDATED",
        timing_validation="HOST_MONOTONIC",
        active_area_validation="UNVALIDATED",
        uncertainty_profile_version="uncertainty/1",
    )


def _uncertainty() -> MeasurementUncertainty:
    return MeasurementUncertainty(
        profile_version="uncertainty/unknown/1",
        coordinate_mm=None,
        relative_count=None,
        force_n=None,
        timing_s=None,
        validation="UNVALIDATED",
    )


def test_session_preserves_raw_and_relative_values_without_claiming_force() -> None:
    session = PhysicalArraySession(
        schema_version="physical-sensor-observation/1.0",
        session_id="session-1",
        coordinate_frame="BOARD_TOP_LEFT_X_RIGHT_Y_DOWN",
        coordinate_unit="mm",
        raw_value_unit="uint8_count",
        relative_value_unit="relative_count",
        force_unit="N",
        measurement_profile=_profile(),
        uncertainty=_uncertainty(),
        cells=(_cell("cell-0", 0, 0.0, 0.0), _cell("cell-1", 1, 7.99, 0.0)),
        frames=(
            PhysicalArrayFrame(
                timestamp_s=0.0,
                raw_count=(4, 8),
                zero_corrected_count=(1.0, -1.0),
                relative_load_count=(1.0, 0.0),
                quality=FrameQuality.DEGRADED,
                quality_flags=frozenset({"ZERO_OFFSET_APPLIED", "FORCE_UNCALIBRATED"}),
            ),
        ),
        adapter_version="test-adapter/1",
        geometry_version="test-geometry/1",
        source_schema_version="raw-array/1",
    )

    assert session.frames[0].raw_count == (4, 8)
    assert session.frames[0].relative_load_count == (1.0, 0.0)
    assert session.frames[0].estimated_force_n is None
    assert session.uncertainty.validation == "UNVALIDATED"


def test_algorithm_estimated_force_session_rejects_missing_screening_estimate() -> None:
    frame = PhysicalArrayFrame(
        timestamp_s=0.0,
        raw_count=(1,),
        zero_corrected_count=(0.0,),
        relative_load_count=(0.0,),
        quality=FrameQuality.DEGRADED,
        quality_flags=frozenset({"FORCE_UNCALIBRATED"}),
    )

    with pytest.raises(ValueError, match="MVP screening estimated force"):
        PhysicalArraySession(
            schema_version="estimated-force-session/1.0",
            session_id="not-ready-for-algorithm",
            coordinate_frame="BOARD_TOP_LEFT_X_RIGHT_Y_DOWN",
            coordinate_unit="mm",
            raw_value_unit="uint8_count",
            relative_value_unit="relative_count",
            force_unit="N",
            measurement_profile=_profile(),
            uncertainty=_uncertainty(),
            cells=(_cell("cell-0", 0, 0.0, 0.0),),
            frames=(frame,),
            adapter_version="test-adapter/1",
            geometry_version="test-geometry/1",
            source_schema_version="raw-array/1",
        )


def test_session_rejects_duplicate_source_indices_and_non_increasing_time() -> None:
    frame = PhysicalArrayFrame(
        timestamp_s=0.0,
        raw_count=(1, 2),
        zero_corrected_count=None,
        relative_load_count=None,
        quality=FrameQuality.DEGRADED,
        quality_flags=frozenset({"BASELINE_MISSING", "FORCE_UNCALIBRATED"}),
    )
    duplicate_source = (_cell("cell-0", 0, 0.0, 0.0), _cell("cell-1", 0, 7.99, 0.0))

    with pytest.raises(ValueError, match="source_index"):
        PhysicalArraySession(
            schema_version="physical-sensor-observation/1.0",
            session_id="session-1",
            coordinate_frame="BOARD_TOP_LEFT_X_RIGHT_Y_DOWN",
            coordinate_unit="mm",
            raw_value_unit="uint8_count",
            relative_value_unit="relative_count",
            force_unit="N",
            measurement_profile=_profile(),
            uncertainty=_uncertainty(),
            cells=duplicate_source,
            frames=(frame,),
            adapter_version="test-adapter/1",
            geometry_version="test-geometry/1",
            source_schema_version="raw-array/1",
        )
