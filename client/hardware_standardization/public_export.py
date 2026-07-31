"""Minimal hardware-to-algorithm screening estimated-force export.

This module is the only public boundary for a hardware-standardized session.
It deliberately accepts the whole-session decision produced by the hardware
quality gate, rather than a raw frame or the hardware-private observation
object.  The returned value therefore has no protocol, repair, quality or
device-specific fields for an algorithm consumer to depend on.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .models import CellStatus, PhysicalArrayFrame
from .quality import HardwareDataValidity, HardwareQualityEvaluation


class PublicPressureExportError(ValueError):
    """A hardware result cannot cross into the algorithm input boundary."""


@dataclass(frozen=True, slots=True)
class PhysicalPressurePoint:
    """One algorithm-facing, board-local physical point."""

    point_id: str
    board_x_mm: float
    board_y_mm: float

    def __post_init__(self) -> None:
        if not self.point_id:
            raise ValueError("point_id is required")
        if not isfinite(self.board_x_mm) or not isfinite(self.board_y_mm):
            raise ValueError("board coordinates must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "point_id": self.point_id,
            "board_x_mm": self.board_x_mm,
            "board_y_mm": self.board_y_mm,
        }


@dataclass(frozen=True, slots=True)
class PhysicalPressureFrame:
    """One algorithm-facing estimated-force vector at measured monotonic time."""

    timestamp_s: float
    estimated_force_n: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isfinite(self.timestamp_s) or self.timestamp_s < 0:
            raise ValueError("timestamp_s must be finite and non-negative")
        if not self.estimated_force_n or any(
            not isfinite(value) or value < 0 for value in self.estimated_force_n
        ):
            raise ValueError("estimated_force_n must contain finite non-negative values")

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp_s": self.timestamp_s,
            "estimated_force_n": list(self.estimated_force_n),
        }


@dataclass(frozen=True, slots=True)
class PhysicalPressureSession:
    """Hardware-independent `estimated-force-session/1.0` input object."""

    session_id: str
    points: tuple[PhysicalPressurePoint, ...]
    frames: tuple[PhysicalPressureFrame, ...]
    schema_version: str = "estimated-force-session/1.0"
    coordinate_frame: str = "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN"
    coordinate_unit: str = "mm"
    force_unit: str = "N"
    time_unit: str = "s"

    def __post_init__(self) -> None:
        if self.schema_version != "estimated-force-session/1.0":
            raise ValueError("unsupported estimated-force session schema")
        if not self.session_id:
            raise ValueError("session_id is required")
        if self.coordinate_frame != "BOARD_TOP_LEFT_X_RIGHT_Y_DOWN":
            raise ValueError("only the board-local coordinate frame is supported")
        if self.coordinate_unit != "mm" or self.force_unit != "N" or self.time_unit != "s":
            raise ValueError("public physical pressure units must be mm, N, and s")
        if not self.points:
            raise ValueError("at least one public point is required")
        if len({point.point_id for point in self.points}) != len(self.points):
            raise ValueError("public point IDs must be unique")
        if not self.frames:
            raise ValueError("at least one public frame is required")
        timestamps = tuple(frame.timestamp_s for frame in self.frames)
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("public frame timestamps must be strictly increasing")
        if any(len(frame.estimated_force_n) != len(self.points) for frame in self.frames):
            raise ValueError("public force vectors must match public point count")

    def to_dict(self) -> dict[str, object]:
        """Return the exact JSON object allowed by the public schema."""

        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "coordinate_frame": self.coordinate_frame,
            "coordinate_unit": self.coordinate_unit,
            "force_unit": self.force_unit,
            "time_unit": self.time_unit,
            "points": [point.to_dict() for point in self.points],
            "frames": [frame.to_dict() for frame in self.frames],
        }


def export_committed_valid_hardware_session(
    evaluation: HardwareQualityEvaluation,
    *,
    local_session_committed: bool,
) -> PhysicalPressureSession:
    """Export only an already-committed, hardware-accepted estimated-force session.

    The frozen MVP screening ``estimated_force_n`` is the public algorithm
    value.  No raw-count, voltage, repair, quality or protocol attribute is
    copied across the boundary.
    """

    if evaluation.validity is not HardwareDataValidity.VALID:
        raise PublicPressureExportError("invalid hardware sessions cannot be exported")
    if not local_session_committed:
        raise PublicPressureExportError(
            "a public pressure session requires a committed local hardware session"
        )
    if evaluation.physical_session is None:  # Defensive: the gate enforces this too.
        raise PublicPressureExportError("valid hardware result is missing physical observations")

    source = evaluation.physical_session
    active_indices = tuple(
        index for index, cell in enumerate(source.cells) if cell.status is CellStatus.ACTIVE
    )
    if not active_indices:
        raise PublicPressureExportError("hardware session has no usable physical points")
    points = tuple(
        PhysicalPressurePoint(
            point_id=f"point-{public_index:04d}",
            board_x_mm=source.cells[source_index].board_x_mm,
            board_y_mm=source.cells[source_index].board_y_mm,
        )
        for public_index, source_index in enumerate(active_indices, start=1)
    )
    frames = tuple(
        PhysicalPressureFrame(
            timestamp_s=frame.timestamp_s,
            estimated_force_n=_estimated_force(frame, active_indices),
        )
        for frame in source.frames
    )
    return PhysicalPressureSession(session_id=source.session_id, points=points, frames=frames)


def _estimated_force(
    frame: PhysicalArrayFrame, active_indices: tuple[int, ...]
) -> tuple[float, ...]:
    values: tuple[float | None, ...] | None = None
    if frame.estimated_force_n is not None and all(
        value is not None for value in frame.estimated_force_n
    ):
        values = frame.estimated_force_n
    if values is None:
        raise PublicPressureExportError(
            "hardware session is missing an estimated force value for at least one point"
        )
    force = tuple(float(values[index]) for index in active_indices)
    if any(not isfinite(value) or value < 0 for value in force):
        raise PublicPressureExportError(
            "public estimated-force values must be finite and non-negative"
        )
    return force
