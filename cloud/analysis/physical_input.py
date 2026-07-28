"""Strict public hardware-to-algorithm physical-force input boundary.

This module deliberately contains no calibration details, device topology,
quality flags, stage actions, or operator/safety metadata.  Hardware emits only
validated physical positions, normal forces, and timestamps.  The workflow
service supplies test protocol context separately by ``session_id``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class InputValidationError(ValueError):
    """The payload cannot be used as a standard physical pressure session."""


class CoordinateFrame(StrEnum):
    BOARD_TOP_LEFT_X_RIGHT_Y_DOWN = "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"


class PhysicalInputValidationStatus(StrEnum):
    """Cloud completion status; deliberately not a hardware payload field."""

    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class PhysicalPoint:
    point_id: str
    board_x_mm: float
    board_y_mm: float


@dataclass(frozen=True, slots=True)
class PhysicalFrame:
    timestamp_s: float
    normal_force_n: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class PhysicalPressureSession:
    schema_version: str
    session_id: str
    coordinate_frame: CoordinateFrame
    coordinate_unit: str
    force_unit: str
    time_unit: str
    points: tuple[PhysicalPoint, ...]
    frames: tuple[PhysicalFrame, ...]


_TOP_LEVEL_FIELDS = {
    "schema_version",
    "session_id",
    "coordinate_frame",
    "coordinate_unit",
    "force_unit",
    "time_unit",
    "points",
    "frames",
}
_POINT_FIELDS = {"point_id", "board_x_mm", "board_y_mm"}
_FRAME_FIELDS = {"timestamp_s", "normal_force_n"}


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


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError(f"{name} must be an array")
    return value


def _parse_points(value: object) -> tuple[PhysicalPoint, ...]:
    raw_points = _sequence(value, "points")
    if not raw_points:
        raise InputValidationError("points must not be empty")
    points: list[PhysicalPoint] = []
    identifiers: set[str] = set()
    for index, raw_value in enumerate(raw_points):
        raw = _ensure_mapping(raw_value, f"points[{index}]")
        _ensure_fields(raw, _POINT_FIELDS, f"points[{index}]")
        point_id = _text(raw["point_id"], f"points[{index}].point_id")
        if point_id in identifiers:
            raise InputValidationError(f"duplicate point_id: {point_id}")
        identifiers.add(point_id)
        points.append(
            PhysicalPoint(
                point_id=point_id,
                board_x_mm=_number(raw["board_x_mm"], f"points[{index}].board_x_mm"),
                board_y_mm=_number(raw["board_y_mm"], f"points[{index}].board_y_mm"),
            )
        )
    return tuple(points)


def _parse_frames(value: object, point_count: int) -> tuple[PhysicalFrame, ...]:
    raw_frames = _sequence(value, "frames")
    if not raw_frames:
        raise InputValidationError("frames must not be empty")
    frames: list[PhysicalFrame] = []
    previous_timestamp: float | None = None
    for index, raw_value in enumerate(raw_frames):
        raw = _ensure_mapping(raw_value, f"frames[{index}]")
        _ensure_fields(raw, _FRAME_FIELDS, f"frames[{index}]")
        timestamp = _number(raw["timestamp_s"], f"frames[{index}].timestamp_s")
        if timestamp < 0:
            raise InputValidationError("frame timestamps cannot be negative")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise InputValidationError("frame timestamps must be strictly increasing")
        previous_timestamp = timestamp
        raw_forces = _sequence(raw["normal_force_n"], f"frames[{index}].normal_force_n")
        if len(raw_forces) != point_count:
            raise InputValidationError("normal_force_n length must match points")
        forces = tuple(
            _number(force, f"frames[{index}].normal_force_n[{force_index}]")
            for force_index, force in enumerate(raw_forces)
        )
        if any(force < 0 for force in forces):
            raise InputValidationError("normal_force_n cannot be negative")
        frames.append(PhysicalFrame(timestamp_s=timestamp, normal_force_n=forces))
    return tuple(frames)


def parse_physical_pressure_session(payload: Mapping[str, object]) -> PhysicalPressureSession:
    """Parse the public ``physical-pressure-session/1.0`` force-field contract."""

    raw = _ensure_mapping(payload, "session")
    _ensure_fields(raw, _TOP_LEVEL_FIELDS, "session")
    if raw["schema_version"] != "physical-pressure-session/1.0":
        raise InputValidationError("unsupported schema_version")
    try:
        coordinate_frame = CoordinateFrame(raw["coordinate_frame"])
    except (TypeError, ValueError) as exc:
        raise InputValidationError("coordinate_frame has unsupported value") from exc
    if raw["coordinate_unit"] != "mm":
        raise InputValidationError("coordinate_unit must be mm")
    if raw["force_unit"] != "N":
        raise InputValidationError("force_unit must be N")
    if raw["time_unit"] != "s":
        raise InputValidationError("time_unit must be s")
    points = _parse_points(raw["points"])
    return PhysicalPressureSession(
        schema_version="physical-pressure-session/1.0",
        session_id=_text(raw["session_id"], "session_id"),
        coordinate_frame=coordinate_frame,
        coordinate_unit="mm",
        force_unit="N",
        time_unit="s",
        points=points,
        frames=_parse_frames(raw["frames"], len(points)),
    )


def validate_physical_pressure_session(session: PhysicalPressureSession) -> None:
    """Validate an already constructed session at the public algorithm boundary."""

    if not isinstance(session, PhysicalPressureSession):
        raise InputValidationError("session must be PhysicalPressureSession")
    parse_physical_pressure_session(_session_to_payload(session))


def _session_to_payload(session: PhysicalPressureSession) -> dict[str, object]:
    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "coordinate_frame": session.coordinate_frame.value,
        "coordinate_unit": session.coordinate_unit,
        "force_unit": session.force_unit,
        "time_unit": session.time_unit,
        "points": [
            {
                "point_id": point.point_id,
                "board_x_mm": point.board_x_mm,
                "board_y_mm": point.board_y_mm,
            }
            for point in session.points
        ],
        "frames": [
            {
                "timestamp_s": frame.timestamp_s,
                "normal_force_n": list(frame.normal_force_n),
            }
            for frame in session.frames
        ],
    }
