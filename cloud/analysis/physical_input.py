from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class InputValidationError(ValueError):
    """The payload cannot be used as a standard physical pressure session."""


class CoordinateFrame(StrEnum):
    BOARD_TOP_LEFT_X_RIGHT_Y_DOWN = "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"


class ValidationState(StrEnum):
    VALIDATED = "VALIDATED"
    UNVALIDATED = "UNVALIDATED"
    UNKNOWN = "UNKNOWN"


class CellStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXCLUDED = "EXCLUDED"


class FrameQuality(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class StageId(StrEnum):
    BILATERAL_EYES_OPEN = "BILATERAL_EYES_OPEN"
    BILATERAL_EYES_CLOSED = "BILATERAL_EYES_CLOSED"
    SEMI_TANDEM_LEFT_FORWARD = "SEMI_TANDEM_LEFT_FORWARD"
    SEMI_TANDEM_RIGHT_FORWARD = "SEMI_TANDEM_RIGHT_FORWARD"


class CompletionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    BALANCE_FAILURE = "BALANCE_FAILURE"
    SAFETY_ABORT = "SAFETY_ABORT"
    NON_BALANCE_STOP = "NON_BALANCE_STOP"
    PROTOCOL_INVALID = "PROTOCOL_INVALID"
    TECHNICAL_INVALID = "TECHNICAL_INVALID"


class SubjectOrientation(StrEnum):
    FORWARD = "FORWARD"
    LEFT_90 = "LEFT_90"


class ForwardFoot(StrEnum):
    NONE = "NONE"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class StopReason(StrEnum):
    NONE = "NONE"
    LOSS_OF_BALANCE = "LOSS_OF_BALANCE"
    SAFETY_SYMPTOM = "SAFETY_SYMPTOM"
    PAIN = "PAIN"
    INSTRUCTION = "INSTRUCTION"
    REFUSED = "REFUSED"
    TECHNICAL = "TECHNICAL"
    PROTOCOL = "PROTOCOL"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class MeasurementProfile:
    profile_version: str
    measurement_conformance_version: str
    calibration_profile_version: str
    uncertainty_profile_version: str
    physical_validation: ValidationState
    timing_validation: ValidationState
    coordinate_validation: ValidationState
    force_validation: ValidationState
    geometry_validation: ValidationState


@dataclass(frozen=True, slots=True)
class SensorCell:
    cell_id: str
    x_mm: float
    y_mm: float
    active_area_mm2: float | None
    status: CellStatus


@dataclass(frozen=True, slots=True)
class PhysicalFrame:
    timestamp_s: float
    normal_force_n: tuple[float, ...]
    quality: FrameQuality


@dataclass(frozen=True, slots=True)
class StageWindow:
    stage_id: StageId
    start_s: float
    end_s: float
    completion_status: CompletionStatus
    actual_completion_s: float
    subject_orientation: SubjectOrientation
    forward_foot: ForwardFoot
    step_count: int
    moved_feet: bool
    touched_rail: bool
    staff_supported: bool
    near_fall: bool
    eyes_opened_early: bool
    stop_reason: StopReason


@dataclass(frozen=True, slots=True)
class PhysicalPressureSession:
    schema_version: str
    session_id: str
    coordinate_frame: CoordinateFrame
    coordinate_unit: str
    force_unit: str
    area_unit: str
    time_unit: str
    measurement_profile: MeasurementProfile
    cells: tuple[SensorCell, ...]
    stages: tuple[StageWindow, ...]
    frames: tuple[PhysicalFrame, ...]


_TOP_LEVEL_FIELDS = {
    "schema_version",
    "session_id",
    "coordinate_frame",
    "coordinate_unit",
    "force_unit",
    "area_unit",
    "time_unit",
    "measurement_profile",
    "cells",
    "stages",
    "frames",
}
_PROFILE_FIELDS = {
    "profile_version",
    "measurement_conformance_version",
    "calibration_profile_version",
    "uncertainty_profile_version",
    "physical_validation",
    "timing_validation",
    "coordinate_validation",
    "force_validation",
    "geometry_validation",
}
_CELL_FIELDS = {"cell_id", "x_mm", "y_mm", "active_area_mm2", "status"}
_FRAME_FIELDS = {"timestamp_s", "normal_force_n", "quality"}
_STAGE_FIELDS = {
    "stage_id",
    "start_s",
    "end_s",
    "completion_status",
    "actual_completion_s",
    "subject_orientation",
    "forward_foot",
    "step_count",
    "moved_feet",
    "touched_rail",
    "staff_supported",
    "near_fall",
    "eyes_opened_early",
    "stop_reason",
}
_EXPECTED_STAGES = (
    StageId.BILATERAL_EYES_OPEN,
    StageId.BILATERAL_EYES_CLOSED,
    StageId.SEMI_TANDEM_LEFT_FORWARD,
    StageId.SEMI_TANDEM_RIGHT_FORWARD,
)


def _ensure_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InputValidationError(f"{name} must be an object")
    return value


def _ensure_fields(value: Mapping[str, object], expected: set[str], name: str) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise InputValidationError(f"{name} has unknown field(s): {', '.join(sorted(unknown))}")
    if missing:
        raise InputValidationError(f"{name} is missing field(s): {', '.join(sorted(missing))}")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError(f"{name} must be a non-empty string")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputValidationError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise InputValidationError(f"{name} must be a finite number")
    return number


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise InputValidationError(f"{name} must be boolean")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputValidationError(f"{name} must be a non-negative integer")
    return value


def _enum(enum_type: type[StrEnum], value: object, name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{name} has unsupported value: {value!r}") from exc


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError(f"{name} must be an array")
    return value


def _parse_profile(value: object) -> MeasurementProfile:
    raw = _ensure_mapping(value, "measurement_profile")
    _ensure_fields(raw, _PROFILE_FIELDS, "measurement_profile")
    return MeasurementProfile(
        profile_version=_text(raw["profile_version"], "profile_version"),
        measurement_conformance_version=_text(
            raw["measurement_conformance_version"],
            "measurement_conformance_version",
        ),
        calibration_profile_version=_text(
            raw["calibration_profile_version"],
            "calibration_profile_version",
        ),
        uncertainty_profile_version=_text(
            raw["uncertainty_profile_version"],
            "uncertainty_profile_version",
        ),
        physical_validation=_enum(
            ValidationState,
            raw["physical_validation"],
            "physical_validation",
        ),
        timing_validation=_enum(ValidationState, raw["timing_validation"], "timing_validation"),
        coordinate_validation=_enum(
            ValidationState,
            raw["coordinate_validation"],
            "coordinate_validation",
        ),
        force_validation=_enum(ValidationState, raw["force_validation"], "force_validation"),
        geometry_validation=_enum(
            ValidationState,
            raw["geometry_validation"],
            "geometry_validation",
        ),
    )


def _parse_cells(value: object) -> tuple[SensorCell, ...]:
    raw_cells = _sequence(value, "cells")
    if not raw_cells:
        raise InputValidationError("cells must not be empty")
    cells: list[SensorCell] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_cells):
        raw = _ensure_mapping(value, f"cells[{index}]")
        _ensure_fields(raw, _CELL_FIELDS, f"cells[{index}]")
        cell_id = _text(raw["cell_id"], f"cells[{index}].cell_id")
        if cell_id in seen:
            raise InputValidationError(f"duplicate cell_id: {cell_id}")
        seen.add(cell_id)
        raw_area = raw["active_area_mm2"]
        active_area = (
            None
            if raw_area is None
            else _number(raw_area, f"cells[{index}].active_area_mm2")
        )
        if active_area is not None and active_area <= 0:
            raise InputValidationError(f"cells[{index}].active_area_mm2 must be positive")
        cells.append(
            SensorCell(
                cell_id=cell_id,
                x_mm=_number(raw["x_mm"], f"cells[{index}].x_mm"),
                y_mm=_number(raw["y_mm"], f"cells[{index}].y_mm"),
                active_area_mm2=active_area,
                status=_enum(CellStatus, raw["status"], f"cells[{index}].status"),
            )
        )
    return tuple(cells)


def _parse_frames(value: object, cell_count: int) -> tuple[PhysicalFrame, ...]:
    raw_frames = _sequence(value, "frames")
    if not raw_frames:
        raise InputValidationError("frames must not be empty")
    frames: list[PhysicalFrame] = []
    previous_timestamp: float | None = None
    for index, value in enumerate(raw_frames):
        raw = _ensure_mapping(value, f"frames[{index}]")
        _ensure_fields(raw, _FRAME_FIELDS, f"frames[{index}]")
        timestamp = _number(raw["timestamp_s"], f"frames[{index}].timestamp_s")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise InputValidationError("frame timestamps must be strictly increasing")
        previous_timestamp = timestamp
        raw_forces = _sequence(raw["normal_force_n"], f"frames[{index}].normal_force_n")
        if len(raw_forces) != cell_count:
            raise InputValidationError("normal_force_n length must match cells")
        forces: list[float] = []
        for force_index, force in enumerate(raw_forces):
            number = _number(force, f"frames[{index}].normal_force_n[{force_index}]")
            if number < 0:
                raise InputValidationError("normal_force_n cannot be negative")
            forces.append(number)
        frames.append(
            PhysicalFrame(
                timestamp_s=timestamp,
                normal_force_n=tuple(forces),
                quality=_enum(FrameQuality, raw["quality"], f"frames[{index}].quality"),
            )
        )
    return tuple(frames)


def _parse_stages(value: object, first_time: float, last_time: float) -> tuple[StageWindow, ...]:
    raw_stages = _sequence(value, "stages")
    if len(raw_stages) != len(_EXPECTED_STAGES):
        raise InputValidationError("session must contain all four stages")
    stages: list[StageWindow] = []
    previous_end: float | None = None
    for index, value in enumerate(raw_stages):
        raw = _ensure_mapping(value, f"stages[{index}]")
        _ensure_fields(raw, _STAGE_FIELDS, f"stages[{index}]")
        stage_id = _enum(StageId, raw["stage_id"], f"stages[{index}].stage_id")
        if stage_id is not _EXPECTED_STAGES[index]:
            raise InputValidationError("stages must use the canonical four-stage order")
        start = _number(raw["start_s"], f"stages[{index}].start_s")
        end = _number(raw["end_s"], f"stages[{index}].end_s")
        if end <= start or start < first_time or end > last_time:
            raise InputValidationError("stage bounds must be ordered and within frame time")
        if previous_end is not None and start != previous_end:
            raise InputValidationError("stage windows must be contiguous")
        previous_end = end
        completion = _enum(
            CompletionStatus,
            raw["completion_status"],
            f"stages[{index}].completion_status",
        )
        actual_completion = _number(
            raw["actual_completion_s"],
            f"stages[{index}].actual_completion_s",
        )
        if actual_completion < 0 or actual_completion > end - start:
            raise InputValidationError("actual_completion_s must fit inside the stage window")
        orientation = _enum(
            SubjectOrientation,
            raw["subject_orientation"],
            f"stages[{index}].subject_orientation",
        )
        forward_foot = _enum(ForwardFoot, raw["forward_foot"], f"stages[{index}].forward_foot")
        expected_orientation = (
            SubjectOrientation.FORWARD if index < 2 else SubjectOrientation.LEFT_90
        )
        expected_foot = ForwardFoot.NONE if index < 2 else (
            ForwardFoot.LEFT if index == 2 else ForwardFoot.RIGHT
        )
        if orientation is not expected_orientation or forward_foot is not expected_foot:
            raise InputValidationError("stage orientation or forward foot is invalid")
        stages.append(
            StageWindow(
                stage_id=stage_id,
                start_s=start,
                end_s=end,
                completion_status=completion,
                actual_completion_s=actual_completion,
                subject_orientation=orientation,
                forward_foot=forward_foot,
                step_count=_integer(raw["step_count"], f"stages[{index}].step_count"),
                moved_feet=_boolean(raw["moved_feet"], f"stages[{index}].moved_feet"),
                touched_rail=_boolean(raw["touched_rail"], f"stages[{index}].touched_rail"),
                staff_supported=_boolean(
                    raw["staff_supported"],
                    f"stages[{index}].staff_supported",
                ),
                near_fall=_boolean(raw["near_fall"], f"stages[{index}].near_fall"),
                eyes_opened_early=_boolean(
                    raw["eyes_opened_early"],
                    f"stages[{index}].eyes_opened_early",
                ),
                stop_reason=_enum(StopReason, raw["stop_reason"], f"stages[{index}].stop_reason"),
            )
        )
    return tuple(stages)


def parse_physical_pressure_session(payload: Mapping[str, object]) -> PhysicalPressureSession:
    """Parse and validate a canonical physical-pressure-session/1.0 payload."""

    raw = _ensure_mapping(payload, "session")
    _ensure_fields(raw, _TOP_LEVEL_FIELDS, "session")
    if raw["schema_version"] != "physical-pressure-session/1.0":
        raise InputValidationError("unsupported schema_version")
    coordinate_frame = _enum(CoordinateFrame, raw["coordinate_frame"], "coordinate_frame")
    if raw["coordinate_unit"] != "mm":
        raise InputValidationError("coordinate_unit must be mm")
    if raw["force_unit"] != "N":
        raise InputValidationError("force_unit must be N")
    if raw["area_unit"] != "mm2":
        raise InputValidationError("area_unit must be mm2")
    if raw["time_unit"] != "s":
        raise InputValidationError("time_unit must be s")
    profile = _parse_profile(raw["measurement_profile"])
    cells = _parse_cells(raw["cells"])
    frames = _parse_frames(raw["frames"], len(cells))
    stages = _parse_stages(raw["stages"], frames[0].timestamp_s, frames[-1].timestamp_s)
    return PhysicalPressureSession(
        schema_version="physical-pressure-session/1.0",
        session_id=_text(raw["session_id"], "session_id"),
        coordinate_frame=coordinate_frame,
        coordinate_unit="mm",
        force_unit="N",
        area_unit="mm2",
        time_unit="s",
        measurement_profile=profile,
        cells=cells,
        stages=stages,
        frames=frames,
    )


def validate_physical_pressure_session(session: PhysicalPressureSession) -> None:
    """Validate an already constructed session at the public algorithm boundary."""

    if not isinstance(session, PhysicalPressureSession):
        raise InputValidationError("session must be PhysicalPressureSession")
    parse_physical_pressure_session(_session_to_payload(session))


def _session_to_payload(session: PhysicalPressureSession) -> dict[str, object]:
    """Create a validation payload without exposing device-specific metadata."""

    profile = session.measurement_profile
    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "coordinate_frame": session.coordinate_frame.value,
        "coordinate_unit": session.coordinate_unit,
        "force_unit": session.force_unit,
        "area_unit": session.area_unit,
        "time_unit": session.time_unit,
        "measurement_profile": {
            "profile_version": profile.profile_version,
            "measurement_conformance_version": profile.measurement_conformance_version,
            "calibration_profile_version": profile.calibration_profile_version,
            "uncertainty_profile_version": profile.uncertainty_profile_version,
            "physical_validation": profile.physical_validation.value,
            "timing_validation": profile.timing_validation.value,
            "coordinate_validation": profile.coordinate_validation.value,
            "force_validation": profile.force_validation.value,
            "geometry_validation": profile.geometry_validation.value,
        },
        "cells": [
            {
                "cell_id": cell.cell_id,
                "x_mm": cell.x_mm,
                "y_mm": cell.y_mm,
                "active_area_mm2": cell.active_area_mm2,
                "status": cell.status.value,
            }
            for cell in session.cells
        ],
        "stages": [
            {
                "stage_id": stage.stage_id.value,
                "start_s": stage.start_s,
                "end_s": stage.end_s,
                "completion_status": stage.completion_status.value,
                "actual_completion_s": stage.actual_completion_s,
                "subject_orientation": stage.subject_orientation.value,
                "forward_foot": stage.forward_foot.value,
                "step_count": stage.step_count,
                "moved_feet": stage.moved_feet,
                "touched_rail": stage.touched_rail,
                "staff_supported": stage.staff_supported,
                "near_fall": stage.near_fall,
                "eyes_opened_early": stage.eyes_opened_early,
                "stop_reason": stage.stop_reason.value,
            }
            for stage in session.stages
        ],
        "frames": [
            {
                "timestamp_s": frame.timestamp_s,
                "normal_force_n": list(frame.normal_force_n),
                "quality": frame.quality.value,
            }
            for frame in session.frames
        ],
    }
