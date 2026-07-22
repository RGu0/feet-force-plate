from __future__ import annotations

from copy import deepcopy

import pytest

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.features import extract_features
from cloud.analysis.physical_input import StageId, parse_physical_pressure_session

from test_physical_input import valid_payload


def _weights(ml_mm: float, ap_mm: float) -> tuple[float, float, float, float]:
    # Four corners at (-40,-40), (40,-40), (-40,40), (40,40).
    ml = ml_mm / 40.0
    ap = ap_mm / 40.0
    return (
        (1 - ml) * (1 - ap) / 4,
        (1 + ml) * (1 - ap) / 4,
        (1 - ml) * (1 + ap) / 4,
        (1 + ml) * (1 + ap) / 4,
    )


def _session_payload(split_cells: bool = False) -> dict[str, object]:
    payload = valid_payload()
    if split_cells:
        payload["cells"] = [
            {
                "cell_id": "a1",
                "ml_mm": -40.0,
                "ap_mm": -40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "a2",
                "ml_mm": -40.0,
                "ap_mm": -40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "b1",
                "ml_mm": 40.0,
                "ap_mm": -40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "b2",
                "ml_mm": 40.0,
                "ap_mm": -40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "c1",
                "ml_mm": -40.0,
                "ap_mm": 40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "c2",
                "ml_mm": -40.0,
                "ap_mm": 40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "d1",
                "ml_mm": 40.0,
                "ap_mm": 40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "d2",
                "ml_mm": 40.0,
                "ap_mm": 40.0,
                "active_area_mm2": 50.0,
                "status": "ACTIVE",
            },
        ]
    else:
        payload["cells"] = [
            {
                "cell_id": "a",
                "ml_mm": -40.0,
                "ap_mm": -40.0,
                "active_area_mm2": 100.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "b",
                "ml_mm": 40.0,
                "ap_mm": -40.0,
                "active_area_mm2": 100.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "c",
                "ml_mm": -40.0,
                "ap_mm": 40.0,
                "active_area_mm2": 100.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "d",
                "ml_mm": 40.0,
                "ap_mm": 40.0,
                "active_area_mm2": 100.0,
                "status": "ACTIVE",
            },
        ]

    frames: list[dict[str, object]] = []
    for timestamp in range(81):
        stage_index = min(timestamp // 20, 3)
        local = timestamp % 20
        extent = (stage_index + 1) * 9.0
        ml_mm = extent * local / 19.0
        ap_mm = (local % 2) * 2.0
        weights = _weights(ml_mm, ap_mm)
        forces = [weight * 100.0 for weight in weights]
        if split_cells:
            forces = [force / 2 for force in forces for _ in (0, 1)]
        frames.append(
            {
                "timestamp_s": float(timestamp),
                "normal_force_n": forces,
                "quality": "VALID",
            }
        )
    payload["frames"] = frames
    return payload


def test_extracts_physical_cop_metrics_and_stage_ratios() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        FeatureParameters(
            version="physical-features/test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )

    eyes_open = features.stage(StageId.BILATERAL_EYES_OPEN)
    eyes_closed = features.stage(StageId.BILATERAL_EYES_CLOSED)

    assert eyes_open.completion_time_s == 20.0
    expected_path = 19.0 * ((9.0 / 19.0) ** 2 + 2.0**2) ** 0.5
    assert eyes_open.cop_path_mm == pytest.approx(expected_path, rel=1e-6)
    assert eyes_open.mean_velocity_mm_s == pytest.approx(
        eyes_open.cop_path_mm / 19.0,
        rel=1e-6,
    )
    assert eyes_open.ml_mean_velocity_mm_s == pytest.approx(9.0 / 19.0, rel=1e-6)
    assert eyes_open.ap_range_90_mm == pytest.approx(2.0, rel=1e-6)
    assert eyes_open.total_force_cv == pytest.approx(0.0, abs=1e-9)
    assert features.eyes_closed_ratio("ml_mean_velocity_mm_s") == pytest.approx(2.0, rel=1e-6)
    assert eyes_closed.mean_velocity_mm_s > eyes_open.mean_velocity_mm_s


def test_same_physical_field_has_same_features_with_split_array_layout() -> None:
    first = extract_features(
        parse_physical_pressure_session(_session_payload()),
        FeatureParameters(
            version="physical-features/test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )
    second = extract_features(
        parse_physical_pressure_session(_session_payload(split_cells=True)),
        FeatureParameters(
            version="physical-features/test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )

    for stage_id in StageId:
        left = first.stage(stage_id)
        right = second.stage(stage_id)
        assert right.cop_path_mm == pytest.approx(left.cop_path_mm, abs=1e-9)
        assert right.mean_velocity_mm_s == pytest.approx(left.mean_velocity_mm_s, abs=1e-9)
        assert right.ellipse_area_95_mm2 == pytest.approx(left.ellipse_area_95_mm2, abs=1e-9)


def test_does_not_bridge_a_gap_larger_than_two_nominal_intervals() -> None:
    payload = _session_payload()
    payload["frames"] = [
        frame
        for frame in payload["frames"]
        if frame["timestamp_s"] not in {10.0, 11.0, 12.0, 13.0}
    ]
    session = parse_physical_pressure_session(payload)
    features = extract_features(
        session,
        FeatureParameters(
            version="physical-features/test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )

    eyes_open = features.stage(StageId.BILATERAL_EYES_OPEN)
    full_path = 19.0 * ((9.0 / 19.0) ** 2 + 2.0**2) ** 0.5
    assert eyes_open.cop_path_mm < full_path
    assert eyes_open.gap_count == 1


def test_invalid_frames_are_excluded_from_physical_metrics() -> None:
    payload = _session_payload()
    payload["frames"][2]["quality"] = "INVALID"
    session = parse_physical_pressure_session(payload)
    features = extract_features(
        session,
        FeatureParameters(version="physical-features/test", lowpass_cutoff_hz=0.0),
    )

    assert features.stage(StageId.BILATERAL_EYES_OPEN).valid_frame_count == 19
