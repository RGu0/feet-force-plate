"""Qt bridge for a single real-hardware capture across the four UI stages."""

from __future__ import annotations

from collections.abc import Callable
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal


class QtLiveHardwareAcquisition(QObject):
    """Keep serial capture off the Qt thread while the operator sees live stages.

    ``capture_session`` owns the actual byte transport, storage, quality gate,
    and encrypted commit.  This bridge owns only the GUI clock and dispatches
    the resulting completion back to the Qt thread.
    """

    capture_finished = Signal(object)
    capture_failed = Signal(str)
    continuous_stage_capture = True

    def __init__(
        self,
        capture_session: Callable[[str], object],
        *,
        stage_count: int = 4,
        require_stage_completion: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if stage_count <= 0:
            raise ValueError("stage_count must be positive")
        self._capture_session = capture_session
        self._stage_count = stage_count
        self._require_stage_completion = require_stage_completion
        self._thread: threading.Thread | None = None
        self._session_id: str | None = None
        self._stage_duration_seconds = 0
        self._completed_stages = 0
        self._stage_started_at: float | None = None
        self._last_elapsed = -1
        self._ui_stages_completed = False
        self._capture_result: object | None = None
        self._on_progress: Callable[[int], None] = lambda _elapsed: None
        self._on_complete: Callable[[object], None] = lambda _result: None
        self._on_failure: Callable[[str], None] = lambda _message: None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self.capture_finished.connect(self._deliver_complete)
        self.capture_failed.connect(self._deliver_failure)

    def set_callbacks(
        self,
        *,
        on_progress: Callable[[int], None],
        on_complete: Callable[[object], None],
        on_failure: Callable[[str], None],
    ) -> None:
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_failure = on_failure

    def start_stage(self, session_id: str, stage) -> None:
        if self._session_id is None:
            self._session_id = session_id
            self._stage_duration_seconds = int(stage.duration_seconds)
            if self._stage_duration_seconds <= 0:
                raise ValueError("stage duration must be positive")
            self._stage_started_at = time.monotonic()
            self._thread = threading.Thread(
                target=self._capture,
                args=(session_id,),
                name=f"live-hardware-capture-{session_id}",
                daemon=True,
            )
            self._thread.start()
            self._timer.start()
            return
        if self._session_id != session_id:
            raise RuntimeError("one live acquisition bridge cannot span sessions")

    def start(self, _session_id: str) -> None:
        raise RuntimeError("live hardware acquisition requires a staged protocol")

    def finish(self, session_id: str) -> None:
        if session_id != self._session_id:
            return
        self._timer.stop()

    def stop(self, session_id: str) -> None:
        """Stop the UI timer; transport cancellation remains owned by its adapter."""

        if session_id == self._session_id:
            self._timer.stop()

    def _capture(self, session_id: str) -> None:
        try:
            self.capture_finished.emit(self._capture_session(session_id))
        except Exception as exc:
            self.capture_failed.emit(f"{type(exc).__name__}: {exc}")

    def _tick(self) -> None:
        started = self._stage_started_at
        if started is None:
            return
        elapsed = min(
            self._stage_duration_seconds,
            int(time.monotonic() - started),
        )
        if elapsed != self._last_elapsed:
            self._last_elapsed = elapsed
            self._on_progress(elapsed)
        if elapsed < self._stage_duration_seconds:
            return
        self._completed_stages += 1
        if self._completed_stages >= self._stage_count:
            self._timer.stop()
            self._ui_stages_completed = True
            self._maybe_deliver_complete()
            return
        self._stage_started_at = time.monotonic()
        self._last_elapsed = -1

    def _deliver_complete(self, result: object) -> None:
        self._capture_result = result
        self._maybe_deliver_complete()

    def _deliver_failure(self, message: str) -> None:
        self._timer.stop()
        self._on_failure(message)

    def _maybe_deliver_complete(self) -> None:
        result = self._capture_result
        if result is None:
            return
        if self._require_stage_completion and not self._ui_stages_completed:
            return
        self._capture_result = None
        self._timer.stop()
        self._on_complete(result)
