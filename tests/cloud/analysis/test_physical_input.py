from __future__ import annotations

from copy import deepcopy

import pytest

from cloud.analysis.physical_input import (
    CoordinateFrame,
    InputValidationError,
    parse_physical_pressure_session,
)


STAGES = (
    {
        "stage_id": "BILATERAL_EYES_OPEN",
        "start_s": 0.0,
        "end_s": 20.0,
        "completion_status": "COMPLETED",
        "actual_completion_s": 20.0,
        "subject_orientation": "FORWARD",
        "forward_foot": "NONE",
        "step_count": 0,
        "moved_feet": False,
        "touched_rail": False,
        "staff_supported": False,
        "near_fall": False,
        "eyes_opened_early": False,
        "stop_reason": "NONE",
    },
    {
        "stage_id": "BILATERAL_EYES_CLOSED",
        "start_s": 20.0,
        "end_s": 40.0,
        "completion_status": "COMPLETED",
        "actual_completion_s": 20.0,
        "subject_orientation": "FORWARD",
        "forward_foot": "NONE",
        "step_count": 0,
        "moved_feet": False,
        "touched_rail": False,
        "staff_supported": False,
        "near_fall": False,
        "eyes_opened_early": False,
        "stop_reason": "NONE",
    },
    {
        "stage_id": "SEMI_TANDEM_LEFT_FORWARD",
        "start_s": 40.0,
        "end_s": 60.0,
        "completion_status": "COMPLETED",
        "actual_completion_s": 20.0,
        "subject_orientation": "LEFT_90",
        "forward_foot": "LEFT",
        "step_count": 0,
        "moved_feet": False,
        "touched_rail": False,
        "staff_supported": False,
        "near_fall": False,
        "eyes_opened_early": False,
        "stop_reason": "NONE",
    },
    {
        "stage_id": "SEMI_TANDEM_RIGHT_FORWARD",
        "start_s": 60.0,
        "end_s": 80.0,
        "completion_status": "COMPLETED",
        "actual_completion_s": 20.0,
        "subject_orientation": "LEFT_90",
        "forward_foot": "RIGHT",
        "step_count": 0,
        "moved_feet": False,
        "touched_rail": False,
        "staff_supported": False,
        "near_fall": False,
        "eyes_opened_early": False,
        "stop_reason": "NONE",
    },
)


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "physical-pressure-session/1.0",
        "session_id": "session-physical-1",
        "coordinate_frame": "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN",
        "coordinate_unit": "mm",
        "force_unit": "N",
        "area_unit": "mm2",
        "time_unit": "s",
        "measurement_profile": {
            "profile_version": "measurement-profile/1",
            "measurement_conformance_version": "measurement-conformance/1",
            "calibration_profile_version": "calibration/1",
            "uncertainty_profile_version": "uncertainty/1",
            "physical_validation": "VALIDATED",
            "timing_validation": "VALIDATED",
            "coordinate_validation": "VALIDATED",
            "force_validation": "VALIDATED",
            "geometry_validation": "VALIDATED",
        },
        "cells": [
            {
                "cell_id": "a",
                "x_mm": 0.0,
                "y_mm": 0.0,
                "active_area_mm2": 100.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "b",
                "x_mm": 20.0,
                "y_mm": 0.0,
                "active_area_mm2": 100.0,
                "status": "ACTIVE",
            },
            {
                "cell_id": "c",
                "x_mm": 10.0,
                "y_mm": 40.0,
                "active_area_mm2": 75.0,
                "status": "ACTIVE",
            },
        ],
        "stages": deepcopy(STAGES),
        "frames": [
            {"timestamp_s": 0.0, "normal_force_n": [10.0, 20.0, 30.0], "quality": "VALID"},
            {"timestamp_s": 1.0, "normal_force_n": [11.0, 21.0, 31.0], "quality": "VALID"},
            {"timestamp_s": 80.0, "normal_force_n": [12.0, 22.0, 32.0], "quality": "VALID"},
        ],
    }


def test_accepts_irregular_layout_and_preserves_physical_semantics() -> None:
    session = parse_physical_pressure_session(valid_payload())

    assert session.schema_version == "physical-pressure-session/1.0"
    assert session.coordinate_frame is CoordinateFrame.BOARD_TOP_LEFT_X_RIGHT_Y_DOWN
    assert len(session.cells) == 3
    assert session.cells[2].active_area_mm2 == 75.0
    assert [stage.stage_id.value for stage in session.stages] == [
        "BILATERAL_EYES_OPEN",
        "BILATERAL_EYES_CLOSED",
        "SEMI_TANDEM_LEFT_FORWARD",
        "SEMI_TANDEM_RIGHT_FORWARD",
    ]
    assert not hasattr(session, "device_model")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "physical-pressure-session/0.9"),
        ("coordinate_frame", "BOARD_XY"),
        ("coordinate_unit", "cm"),
        ("force_unit", "counts"),
        ("area_unit", "mm"),
        ("time_unit", "ms"),
    ],
)
def test_rejects_noncanonical_schema_or_units(field: str, value: str) -> None:
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(InputValidationError):
        parse_physical_pressure_session(payload)


def test_rejects_unknown_top_level_fields() -> None:
    payload = valid_payload()
    payload["device_model"] = "DO-P4864"

    with pytest.raises(InputValidationError, match="unknown field"):
        parse_physical_pressure_session(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["cells"].__setitem__(1, {**payload["cells"][0]}),
        lambda payload: payload["cells"][0].__setitem__("active_area_mm2", 0),
        lambda payload: payload["frames"][0].__setitem__("normal_force_n", [1.0]),
        lambda payload: payload["frames"][1].__setitem__("timestamp_s", 0.0),
        lambda payload: payload["frames"][1]["normal_force_n"].__setitem__(0, -1.0),
    ],
)
def test_rejects_invalid_geometry_force_length_or_time(mutate) -> None:
    payload = valid_payload()
    mutate(payload)

    with pytest.raises(InputValidationError):
        parse_physical_pressure_session(payload)


@pytest.mark.parametrize(
    ("stage_index", "field", "value"),
    [
        (0, "subject_orientation", "LEFT_90"),
        (2, "forward_foot", "NONE"),
        (3, "forward_foot", "LEFT"),
        (1, "stage_id", "UNKNOWN_STAGE"),
        (0, "end_s", 21.0),
    ],
)
def test_rejects_invalid_stage_protocol_metadata(
    stage_index: int, field: str, value: object
) -> None:
    payload = valid_payload()
    payload["stages"][stage_index][field] = value

    with pytest.raises(InputValidationError):
        parse_physical_pressure_session(payload)


def test_requires_all_four_canonical_stages() -> None:
    payload = valid_payload()
    payload["stages"] = payload["stages"][:3]

    with pytest.raises(InputValidationError, match="four stages"):
        parse_physical_pressure_session(payload)


def test_preserves_unknown_active_area_without_inventing_a_value() -> None:
    payload = valid_payload()
    payload["cells"][0]["active_area_mm2"] = None

    session = parse_physical_pressure_session(payload)

    assert session.cells[0].active_area_mm2 is None


def test_requires_force_and_geometry_validation_status() -> None:
    payload = valid_payload()
    del payload["measurement_profile"]["force_validation"]

    with pytest.raises(InputValidationError, match="force_validation"):
        parse_physical_pressure_session(payload)
