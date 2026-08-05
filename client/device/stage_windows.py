"""Validated real-world timing boundaries for independently captured stages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapturedStageWindow:
    stage_id: str
    start_s: float
    end_s: float
    frame_count: int

    def __post_init__(self) -> None:
        if not self.stage_id or self.start_s < 0 or self.end_s <= self.start_s:
            raise ValueError("captured stage timing is invalid")
        if self.frame_count <= 0:
            raise ValueError("captured stage must contain frames")


def validate_captured_stage_windows(
    windows: tuple[CapturedStageWindow, ...],
    *,
    expected_stage_ids: tuple[str, ...],
    minimum_duration_s: float,
) -> tuple[CapturedStageWindow, ...]:
    """Return only the ordered, distinct, non-overlapping captured stages."""

    if minimum_duration_s <= 0:
        raise ValueError("minimum captured stage duration must be positive")
    if len(windows) != len(expected_stage_ids) or tuple(
        window.stage_id for window in windows
    ) != expected_stage_ids:
        raise ValueError("captured stage windows must match the protocol order")
    if any(
        window.end_s - window.start_s < minimum_duration_s for window in windows
    ):
        raise ValueError("captured stage windows must meet the minimum duration")
    if any(
        current.start_s < previous.end_s
        for previous, current in zip(windows, windows[1:])
    ):
        raise ValueError("captured stage windows must not overlap")
    return windows
