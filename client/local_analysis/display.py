from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    sequence: int
    captured_monotonic_seconds: float
    relative_heatmap: tuple[tuple[float, ...], ...]
    cop_x: float | None
    cop_y: float | None
    cop_trail: tuple[tuple[float, float], ...]
    total_relative_load: float
    left_load_percent: float
    right_load_percent: float
    total_trend: tuple[float, ...]


def build_display_frame(
    counts: NDArray[np.number],
    *,
    sequence: int,
    captured_monotonic_seconds: float,
    cop_trail: tuple[tuple[float, float], ...],
    total_trend: tuple[float, ...],
) -> DisplayFrame:
    matrix = np.asarray(counts, dtype=np.float64)
    if matrix.shape != (48, 64):
        raise ValueError("display counts must have shape (48, 64)")
    if not np.all(np.isfinite(matrix)) or np.any(matrix < 0):
        raise ValueError("display counts must be finite and non-negative")
    total = float(np.sum(matrix))
    peak = float(np.max(matrix))
    normalized = np.zeros_like(matrix) if peak <= 0 else matrix / peak
    if total <= 0:
        cop_x = None
        cop_y = None
        left = 0.0
        right = 0.0
        next_trail = cop_trail[-24:]
    else:
        x = np.arange(64, dtype=np.float64)[None, :]
        y = np.arange(48, dtype=np.float64)[:, None]
        cop_x = float(np.sum(matrix * x) / total)
        cop_y = float(np.sum(matrix * y) / total)
        left = float(np.sum(matrix[:, :32]) / total * 100.0)
        right = float(np.sum(matrix[:, 32:]) / total * 100.0)
        next_trail = (*cop_trail, (cop_x, cop_y))[-24:]
    return DisplayFrame(
        sequence=sequence,
        captured_monotonic_seconds=captured_monotonic_seconds,
        relative_heatmap=tuple(
            tuple(float(value) for value in row) for row in normalized
        ),
        cop_x=cop_x,
        cop_y=cop_y,
        cop_trail=next_trail,
        total_relative_load=total,
        left_load_percent=left,
        right_load_percent=right,
        total_trend=(*total_trend, total)[-60:],
    )


class LatestDisplayFrameMailbox:
    """A latest-only UI mailbox; it never owns or writes reliable capture data."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: DisplayFrame | None = None

    def publish(self, frame: DisplayFrame) -> None:
        with self._lock:
            if self._latest is None or frame.sequence > self._latest.sequence:
                self._latest = frame

    def take_latest(self, *, after_sequence: int) -> DisplayFrame | None:
        with self._lock:
            if self._latest is None or self._latest.sequence <= after_sequence:
                return None
            return self._latest


class DisplayRefreshController:
    def __init__(
        self,
        mailbox: LatestDisplayFrameMailbox,
        *,
        maximum_refresh_hz: float,
    ) -> None:
        if maximum_refresh_hz <= 0:
            raise ValueError("maximum_refresh_hz must be positive")
        self._mailbox = mailbox
        self._minimum_interval = 1.0 / maximum_refresh_hz
        self._next_allowed = 0.0
        self.last_sequence = -1

    def poll(self, *, now_monotonic_seconds: float) -> DisplayFrame | None:
        if now_monotonic_seconds < self._next_allowed:
            return None
        self._next_allowed = now_monotonic_seconds + self._minimum_interval
        frame = self._mailbox.take_latest(after_sequence=self.last_sequence)
        if frame is not None:
            self.last_sequence = frame.sequence
        return frame
