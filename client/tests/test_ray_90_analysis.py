from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from client.local_analysis.analyzer import analyze_local
from client.local_analysis.models import (
    AnalysisContext,
    CalibrationState,
    LocalQualityStatus,
)


FIXTURE = Path(__file__).parent / "fixtures" / "ray_90_basic_golden.json"


def _fixture() -> tuple[np.ndarray, dict]:
    definition = json.loads(FIXTURE.read_text(encoding="utf-8"))
    frames = np.zeros(definition["shape"], dtype=np.float64)
    for point in definition["points"]:
        frames[:, point["row"], point["column"]] = point["count"]
    return frames, definition


def _context(definition: dict, **overrides) -> AnalysisContext:
    values = {
        "sample_rate_hz": definition["sample_rate_hz"],
        "duration_seconds": definition["shape"][0] / definition["sample_rate_hz"],
        "protocol_id": definition["protocol_id"],
        "protocol_version": "1.0.0-pilot",
        "calibration_state": CalibrationState.RELATIVE_ONLY,
        "quality_status": LocalQualityStatus.VALID,
    }
    values.update(overrides)
    return AnalysisContext(**values)


def test_fixed_fixture_produces_deterministic_relative_heatmap_and_basic_loads_without_mutation() -> None:
    frames, fixture = _fixture()
    before = frames.copy()

    result = analyze_local(frames, _context(fixture))

    assert np.array_equal(frames, before)
    assert result.result_version == 1
    assert result.algorithm_version == "local-basic/1.0.0"
    assert result.raw_count_heatmap[20][10] == 1000.0
    assert len(result.relative_heatmap) == 48
    assert len(result.relative_heatmap[0]) == 64
    assert max(max(row) for row in result.relative_heatmap) == 1.0
    expected = fixture["expected"]
    customer = result.customer_metric_map
    assert customer["total_relative_load"].value == pytest.approx(
        expected["total_relative_load"]
    )
    assert customer["left_load_percent"].value == pytest.approx(50.0)
    assert customer["right_load_percent"].value == pytest.approx(50.0)
    assert "stability_score" not in customer
    assert "population_reference_range" not in customer


def test_cop_metrics_are_computed_internally_but_withheld_from_customer_until_validated() -> None:
    frames, fixture = _fixture()

    result = analyze_local(
        frames,
        _context(fixture, duration_seconds=30.0),
    )

    internal = result.internal_metric_map
    expected = fixture["expected"]
    assert internal["cop_x_sensor_index"].value == pytest.approx(
        expected["cop_x_sensor_index"]
    )
    assert internal["cop_y_sensor_index"].value == pytest.approx(
        expected["cop_y_sensor_index"]
    )
    assert internal["cop_path_length"].value == pytest.approx(0.0)
    assert "cop_path_length" not in result.customer_metric_map
    assert result.withheld_reason_map["cop_path_length"] == "NOT_CUSTOMER_VALIDATED"


def test_invalid_quality_or_missing_prerequisite_emits_no_customer_number() -> None:
    frames, fixture = _fixture()

    invalid = analyze_local(
        frames,
        _context(fixture, quality_status=LocalQualityStatus.INVALID),
    )
    low_rate = analyze_local(
        frames[:80],
        _context(fixture, sample_rate_hz=8.0, duration_seconds=10.0),
    )

    assert invalid.customer_metrics == ()
    assert invalid.relative_heatmap is None
    assert set(invalid.withheld_reason_map.values()) == {"QUALITY_NOT_VALID"}
    assert low_rate.customer_metrics == ()
    assert "SAMPLE_RATE_TOO_LOW" in set(low_rate.withheld_reason_map.values())
    assert (
        low_rate.withheld_reason_map["total_force_newton"]
        == "SAMPLE_RATE_TOO_LOW"
    )


def test_local_basic_definitions_align_with_independent_cloud_reference_within_tolerance() -> None:
    frames, fixture = _fixture()
    result = analyze_local(frames, _context(fixture))

    mean_frame = np.mean(frames, axis=0)
    cloud_total = float(np.sum(mean_frame))
    cloud_left = float(np.sum(mean_frame[:, :32]) / cloud_total * 100.0)
    cloud_right = 100.0 - cloud_left

    assert result.customer_metric_map["total_relative_load"].value == pytest.approx(
        cloud_total,
        rel=1e-9,
    )
    assert result.customer_metric_map["left_load_percent"].value == pytest.approx(
        cloud_left,
        abs=1e-9,
    )
    assert result.customer_metric_map["right_load_percent"].value == pytest.approx(
        cloud_right,
        abs=1e-9,
    )
