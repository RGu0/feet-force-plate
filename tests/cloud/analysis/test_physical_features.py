from __future__ import annotations


import pytest

from cloud.analysis.feature_parameters import FeatureParameters
from cloud.analysis.coordinates import board_to_subject_coordinates
from cloud.analysis.features import extract_features
from cloud.analysis.physical_input import parse_physical_pressure_session
from cloud.analysis.protocol_context import StageId, SubjectOrientation

from test_physical_input import valid_payload, valid_protocol_context


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


def _session_payload(
    split_cells: bool = False,
    *,
    sample_rate_hz: float = 1.0,
) -> dict[str, object]:
    payload = valid_payload()
    if split_cells:
        payload["points"] = [
            {
                "point_id": "a1", "board_x_mm": -40.0, "board_y_mm": 40.0,
            },
            {
                "point_id": "a2", "board_x_mm": -40.0, "board_y_mm": 40.0,
            },
            {
                "point_id": "b1", "board_x_mm": 40.0, "board_y_mm": 40.0,
            },
            {
                "point_id": "b2", "board_x_mm": 40.0, "board_y_mm": 40.0,
            },
            {
                "point_id": "c1", "board_x_mm": -40.0, "board_y_mm": -40.0,
            },
            {
                "point_id": "c2", "board_x_mm": -40.0, "board_y_mm": -40.0,
            },
            {
                "point_id": "d1", "board_x_mm": 40.0, "board_y_mm": -40.0,
            },
            {
                "point_id": "d2", "board_x_mm": 40.0, "board_y_mm": -40.0,
            },
        ]
    else:
        payload["points"] = [
            {
                "point_id": "a", "board_x_mm": -40.0, "board_y_mm": 40.0,
            },
            {
                "point_id": "b", "board_x_mm": 40.0, "board_y_mm": 40.0,
            },
            {
                "point_id": "c", "board_x_mm": -40.0, "board_y_mm": -40.0,
            },
            {
                "point_id": "d", "board_x_mm": 40.0, "board_y_mm": -40.0,
            },
        ]

    frames: list[dict[str, object]] = []
    frame_count = int(80 * sample_rate_hz) + 1
    for frame_index in range(frame_count):
        timestamp = frame_index / sample_rate_hz
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
                "estimated_force_n": forces,
            }
        )
    payload["frames"] = frames
    return payload


def test_extracts_physical_cop_metrics_and_stage_ratios() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        valid_protocol_context(),
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
        valid_protocol_context(),
        FeatureParameters(
            version="physical-features/test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )
    second = extract_features(
        parse_physical_pressure_session(_session_payload(split_cells=True)),
        valid_protocol_context(),
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
        valid_protocol_context(),
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


def test_hardware_quality_metadata_is_rejected_before_physical_metrics() -> None:
    payload = _session_payload()
    payload["frames"][2]["quality"] = "INVALID"
    with pytest.raises(Exception):
        parse_physical_pressure_session(payload)


def test_algorithm_rotates_board_coordinates_for_fixed_left_turn() -> None:
    assert board_to_subject_coordinates(
        x_mm=10.0,
        y_mm=20.0,
        orientation=SubjectOrientation.FORWARD,
    ) == pytest.approx((10.0, -20.0))
    assert board_to_subject_coordinates(
        x_mm=10.0,
        y_mm=20.0,
        orientation=SubjectOrientation.LEFT_90,
    ) == pytest.approx((-20.0, -10.0))


def test_feature_extraction_applies_left_turn_to_board_cop() -> None:
    session = parse_physical_pressure_session(_session_payload())
    features = extract_features(
        session,
        valid_protocol_context(),
        FeatureParameters(
            version="physical-features/test",
            despike_window_samples=1,
            lowpass_cutoff_hz=0.0,
        ),
    )

    left_forward = features.stage(StageId.SEMI_TANDEM_LEFT_FORWARD)
    # At t=41 the fixture's board COP is (27/19, -2.0).  The V1 fixed left
    # turn maps it to subject ML/AP = (-y, -x) = (2.0, -27/19).
    assert left_forward.cop_ml_mm[1] == pytest.approx(2.0)
    assert left_forward.cop_ap_mm[1] == pytest.approx(-(27.0 / 19.0))
