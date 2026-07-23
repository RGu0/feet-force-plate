from __future__ import annotations

import pytest

from client.hardware_standardization.calibrated_array import (
    CalibratedArrayAdapter,
    RawArrayFrame,
)
from client.hardware_standardization.geometry import BoardCoordinateLayout
from client.hardware_standardization.models import BaselineReference, StandardizationStatus


def _layout() -> BoardCoordinateLayout:
    return BoardCoordinateLayout.from_cells(
        geometry_version="fixture-layout/1",
        cells=(
            ("a", 10, 3.0, 1.0, 10.0),
            ("b", 2, 9.0, 5.0, 20.0),
            ("missing", 7, 14.0, 8.0, 12.0),
        ),
    )


def test_adapter_uses_actual_host_time_and_degrades_without_baseline_or_force_calibration() -> None:
    adapter = CalibratedArrayAdapter(_layout())

    outcome = adapter.standardize(
        session_id="session-1",
        frames=(
            RawArrayFrame(100_000_000, (10, 20, 30), frozenset()),
            RawArrayFrame(148_380_000, (11, 21, 31), frozenset({"LONG_FRAME_INTERVAL"})),
        ),
    )

    assert outcome.status is StandardizationStatus.DEGRADED
    assert outcome.session is not None
    assert tuple(cell.source_index for cell in outcome.session.cells) == (2, 7, 10)
    assert outcome.session.frames[1].timestamp_s == pytest.approx(0.04838)
    assert outcome.session.frames[0].zero_corrected_count is None
    assert outcome.session.frames[0].normal_force_n == (None, None, None)
    assert {"BASELINE_MISSING", "FORCE_UNCALIBRATED", "ACTIVE_AREA_UNVALIDATED"} <= outcome.session.frames[0].quality_flags


def test_adapter_applies_only_layout_matched_baseline_reference() -> None:
    layout = _layout()
    adapter = CalibratedArrayAdapter(layout)
    reference = BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="base-1",
        layout_digest=layout.digest,
        zero_offset_count=(1.0, 2.0, 3.0),
        noise_mad_count=(0.0, 0.0, 0.0),
        rules_version="startup-baseline/1",
        threshold_version="threshold/1",
        source_digest="a" * 64,
    )

    outcome = adapter.standardize(
        session_id="session-2",
        frames=(RawArrayFrame(0, (5, 1, 8), frozenset()),),
        baseline_reference=reference,
    )

    assert outcome.session is not None
    assert outcome.session.frames[0].zero_corrected_count == (4.0, -1.0, 5.0)
    assert outcome.session.frames[0].relative_load_count == (4.0, 0.0, 5.0)


def test_adapter_rejects_descending_host_time_and_layout_mismatch() -> None:
    adapter = CalibratedArrayAdapter(_layout())
    mismatched = BaselineReference(
        schema_version="baseline-reference/1",
        baseline_window_id="base-1",
        layout_digest="wrong-layout",
        zero_offset_count=(1.0, 2.0, 3.0),
        noise_mad_count=(0.0, 0.0, 0.0),
        rules_version="startup-baseline/1",
        threshold_version="threshold/1",
        source_digest="a" * 64,
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        adapter.standardize(
            session_id="session-3",
            frames=(RawArrayFrame(5, (1, 2, 3), frozenset()), RawArrayFrame(4, (1, 2, 3), frozenset())),
        )
    with pytest.raises(ValueError, match="layout"):
        adapter.standardize(
            session_id="session-4",
            frames=(RawArrayFrame(5, (1, 2, 3), frozenset()),),
            baseline_reference=mismatched,
        )
