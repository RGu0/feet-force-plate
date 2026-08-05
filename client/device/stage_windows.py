"""Validated real-world timing boundaries for independently captured stages."""

from __future__ import annotations

from dataclasses import dataclass
import threading

from .protocol import RawFrame


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


@dataclass(frozen=True, slots=True)
class StageGateDecision:
    """Per-frame routing decision at the display/durable-storage boundary."""

    record: bool
    stage_id: str | None
    stage_complete: bool
    session_complete: bool
    window: CapturedStageWindow | None = None


@dataclass(frozen=True, slots=True)
class StageGateSnapshot:
    """Thread-safe progress state consumed by the Qt thread."""

    stage_id: str | None
    elapsed_seconds: float
    completed_windows: tuple[CapturedStageWindow, ...]
    stage_complete: bool
    session_complete: bool
    cancelled: bool


class StageRecordingGate:
    """Route decoded frames into explicit, ordered operator-started windows."""

    def __init__(self, *, expected_stage_ids: tuple[str, ...]) -> None:
        if not expected_stage_ids or any(not stage_id for stage_id in expected_stage_ids):
            raise ValueError("expected stage ids are required")
        if len(set(expected_stage_ids)) != len(expected_stage_ids):
            raise ValueError("expected stage ids must be distinct")
        self._expected_stage_ids = expected_stage_ids
        self._lock = threading.Lock()
        self._session_id: str | None = None
        self._active_stage_id: str | None = None
        self._display_stage_id: str | None = None
        self._duration_seconds = 0.0
        self._first_frame_ns: int | None = None
        self._session_origin_ns: int | None = None
        self._frame_count = 0
        self._elapsed_seconds = 0.0
        self._completed_windows: list[CapturedStageWindow] = []
        self._stage_complete = False
        self._session_complete = False
        self._cancelled = False

    @property
    def expected_stage_ids(self) -> tuple[str, ...]:
        return self._expected_stage_ids

    def bind_session(self, session_id: str) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        with self._lock:
            if self._session_id is None:
                self._session_id = session_id
            elif self._session_id != session_id:
                raise RuntimeError("one recording gate cannot span sessions")

    def open_stage(self, stage_id: str, duration_seconds: float) -> None:
        if duration_seconds <= 0:
            raise ValueError("stage duration must be positive")
        with self._lock:
            if self._session_complete:
                raise RuntimeError("all expected stages are already complete")
            if self._active_stage_id is not None:
                raise RuntimeError("a recording stage is already active")
            expected = self._expected_stage_ids[len(self._completed_windows)]
            if stage_id != expected:
                raise ValueError("stage order does not match the configured protocol")
            self._active_stage_id = stage_id
            self._display_stage_id = stage_id
            self._duration_seconds = float(duration_seconds)
            self._first_frame_ns = None
            self._frame_count = 0
            self._elapsed_seconds = 0.0
            self._stage_complete = False
            self._cancelled = False

    def observe(self, frame: RawFrame) -> StageGateDecision:
        with self._lock:
            stage_id = self._active_stage_id
            if stage_id is None:
                return StageGateDecision(
                    False,
                    self._display_stage_id,
                    False,
                    self._session_complete,
                )
            if self._first_frame_ns is None:
                self._first_frame_ns = frame.host_monotonic_ns
                if self._session_origin_ns is None:
                    self._session_origin_ns = frame.host_monotonic_ns
            if frame.host_monotonic_ns < self._first_frame_ns:
                raise ValueError("recorded frame timestamps must not move backwards")
            self._frame_count += 1
            actual_elapsed = (
                frame.host_monotonic_ns - self._first_frame_ns
            ) / 1_000_000_000
            self._elapsed_seconds = min(self._duration_seconds, actual_elapsed)
            if actual_elapsed < self._duration_seconds:
                return StageGateDecision(True, stage_id, False, False)

            assert self._session_origin_ns is not None
            window = CapturedStageWindow(
                stage_id=stage_id,
                start_s=(self._first_frame_ns - self._session_origin_ns) / 1_000_000_000,
                end_s=(frame.host_monotonic_ns - self._session_origin_ns)
                / 1_000_000_000,
                frame_count=self._frame_count,
            )
            self._completed_windows.append(window)
            self._active_stage_id = None
            self._stage_complete = True
            self._session_complete = len(self._completed_windows) == len(
                self._expected_stage_ids
            )
            return StageGateDecision(
                True,
                stage_id,
                True,
                self._session_complete,
                window,
            )

    def cancel_current_stage(self) -> None:
        with self._lock:
            stage_id = self._active_stage_id
            if stage_id is None and self._stage_complete and self._completed_windows:
                stage_id = self._completed_windows.pop().stage_id
                self._session_complete = False
            if stage_id is None:
                return
            self._display_stage_id = stage_id
            self._active_stage_id = None
            self._first_frame_ns = None
            self._frame_count = 0
            self._elapsed_seconds = 0.0
            self._stage_complete = False
            self._cancelled = True
            if not self._completed_windows:
                self._session_origin_ns = None

    def snapshot(self) -> StageGateSnapshot:
        with self._lock:
            return StageGateSnapshot(
                stage_id=self._display_stage_id,
                elapsed_seconds=self._elapsed_seconds,
                completed_windows=tuple(self._completed_windows),
                stage_complete=self._stage_complete,
                session_complete=self._session_complete,
                cancelled=self._cancelled,
            )


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
