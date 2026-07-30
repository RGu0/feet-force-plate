from __future__ import annotations

import pytest

from cloud.analysis.physical_input import (
    CoordinateFrame,
    InputValidationError,
    parse_physical_pressure_session,
)
from cloud.analysis.protocol_context import (
    CompletionStatus,
    ForwardFoot,
    StageId,
    StageWindow,
    StaticBalanceProtocolContext,
    StopReason,
    SubjectOrientation,
    validate_static_balance_protocol_context,
)


def _stage(stage_id: StageId, start_s: float, *, orientation: SubjectOrientation, foot: ForwardFoot) -> StageWindow:
    return StageWindow(
        stage_id=stage_id, start_s=start_s, end_s=start_s + 20.0,
        completion_status=CompletionStatus.COMPLETED, actual_completion_s=20.0,
        subject_orientation=orientation, forward_foot=foot, step_count=0,
        moved_feet=False, touched_rail=False, staff_supported=False, near_fall=False,
        eyes_opened_early=False, stop_reason=StopReason.NONE,
    )


def valid_protocol_context(session_id: str = "session-physical-1") -> StaticBalanceProtocolContext:
    return StaticBalanceProtocolContext(
        session_id=session_id, protocol_version="static-balance/1",
        stages=(
            _stage(StageId.BILATERAL_EYES_OPEN, 0.0, orientation=SubjectOrientation.FORWARD, foot=ForwardFoot.NONE),
            _stage(StageId.BILATERAL_EYES_CLOSED, 20.0, orientation=SubjectOrientation.FORWARD, foot=ForwardFoot.NONE),
            _stage(StageId.SEMI_TANDEM_LEFT_FORWARD, 40.0, orientation=SubjectOrientation.LEFT_90, foot=ForwardFoot.LEFT),
            _stage(StageId.SEMI_TANDEM_RIGHT_FORWARD, 60.0, orientation=SubjectOrientation.LEFT_90, foot=ForwardFoot.RIGHT),
        ),
    )


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "estimated-force-session/1.0",
        "session_id": "session-physical-1",
        "coordinate_frame": "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN",
        "coordinate_unit": "mm",
        "force_unit": "N",
        "time_unit": "s",
        "points": [
            {"point_id": "a", "board_x_mm": 0.0, "board_y_mm": 0.0},
            {"point_id": "b", "board_x_mm": 20.0, "board_y_mm": 0.0},
            {"point_id": "c", "board_x_mm": 10.0, "board_y_mm": 40.0},
        ],
        "frames": [
            {"timestamp_s": 0.0, "estimated_force_n": [10.0, 20.0, 30.0]},
            {"timestamp_s": 1.0, "estimated_force_n": [11.0, 21.0, 31.0]},
            {"timestamp_s": 80.0, "estimated_force_n": [12.0, 22.0, 32.0]},
        ],
    }


def test_accepts_irregular_layout_and_preserves_physical_semantics() -> None:
    session = parse_physical_pressure_session(valid_payload())
    assert session.coordinate_frame is CoordinateFrame.BOARD_TOP_LEFT_X_RIGHT_Y_DOWN
    assert session.points[2].board_y_mm == 40.0
    assert not hasattr(session, "device_model")
    assert not hasattr(session, "stages")
    assert not hasattr(session, "measurement_profile")


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "estimated-force-session/0.9"), ("coordinate_frame", "BOARD_XY"),
     ("coordinate_unit", "cm"), ("force_unit", "counts"), ("time_unit", "ms")],
)
def test_rejects_noncanonical_schema_or_units(field: str, value: str) -> None:
    payload = valid_payload(); payload[field] = value
    with pytest.raises(InputValidationError):
        parse_physical_pressure_session(payload)


@pytest.mark.parametrize("field", ["device_model", "measurement_profile", "stages", "area_unit"])
def test_rejects_hardware_or_workflow_metadata_in_public_force_payload(field: str) -> None:
    payload = valid_payload(); payload[field] = "not-public"
    with pytest.raises(InputValidationError, match="unknown field"):
        parse_physical_pressure_session(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["points"].__setitem__(1, {**payload["points"][0]}),
        lambda payload: payload["frames"][0].__setitem__("estimated_force_n", [1.0]),
        lambda payload: payload["frames"][1].__setitem__("timestamp_s", 0.0),
        lambda payload: payload["frames"][1]["estimated_force_n"].__setitem__(0, -1.0),
        lambda payload: payload["frames"][0].__setitem__("quality", "VALID"),
    ],
)
def test_rejects_invalid_geometry_force_length_time_or_quality_metadata(mutate) -> None:
    payload = valid_payload(); mutate(payload)
    with pytest.raises(InputValidationError):
        parse_physical_pressure_session(payload)


def test_protocol_context_is_separate_and_has_canonical_stages() -> None:
    context = valid_protocol_context()
    validate_static_balance_protocol_context(context)
    assert [stage.stage_id for stage in context.stages] == list(StageId)


def test_protocol_context_rejects_invalid_left_turn_or_forward_foot() -> None:
    context = valid_protocol_context()
    invalid = StaticBalanceProtocolContext(
        session_id=context.session_id, protocol_version=context.protocol_version,
        stages=(
            *context.stages[:2],
            _stage(StageId.SEMI_TANDEM_LEFT_FORWARD, 40.0, orientation=SubjectOrientation.LEFT_90, foot=ForwardFoot.RIGHT),
            context.stages[3],
        ),
    )
    with pytest.raises(Exception):
        validate_static_balance_protocol_context(invalid)
