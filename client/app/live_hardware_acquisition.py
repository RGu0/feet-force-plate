"""Qt bridge for operator-started stages on one persistent device loop."""

from __future__ import annotations

from collections.abc import Callable
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from client.device.stage_windows import StageRecordingGate
from client.workflow.protocol import default_standard_protocol


class QtLiveHardwareAcquisition(QObject):
    """Open manual recording windows and marshal worker events to the Qt thread."""

    capture_finished = Signal(object)
    capture_failed = Signal(str)

    def __init__(
        self,
        capture_session: Callable[[str, StageRecordingGate], object],
        *,
        expected_stage_ids: tuple[str, ...] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._capture_session = capture_session
        self._expected_stage_ids = (
            tuple(stage.stage_id for stage in default_standard_protocol().stages)
            if expected_stage_ids is None
            else expected_stage_ids
        )
        self._gate = StageRecordingGate(
            expected_stage_ids=self._expected_stage_ids
        )
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._session_id: str | None = None
        self._stage_id: str | None = None
        self._stage_duration_seconds = 0
        self._completed_stages = 0
        self._stage_completion_delivered = False
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
            self._gate.bind_session(session_id)
        elif self._session_id != session_id:
            raise RuntimeError("one live acquisition bridge cannot span sessions")

        stage_id_value = getattr(stage.stage_id, "value", stage.stage_id)
        stage_id = str(stage_id_value)
        duration_seconds = int(stage.duration_seconds)
        if duration_seconds <= 0:
            raise ValueError("stage duration must be positive")
        self._gate.open_stage(stage_id, duration_seconds)
        self._stage_id = stage_id
        self._stage_duration_seconds = duration_seconds
        self._stage_completion_delivered = False
        self._last_elapsed = -1

        with self._thread_lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._capture,
                    args=(session_id,),
                    name=f"live-hardware-capture-{session_id}",
                    daemon=True,
                )
                self._thread.start()
        self._timer.start()

    def start(self, _session_id: str) -> None:
        raise RuntimeError("live hardware acquisition requires a staged protocol")

    def finish(self, session_id: str) -> None:
        if session_id == self._session_id:
            self._maybe_deliver_complete()

    def stop(self, session_id: str) -> None:
        """Cancel only the active attempt; the worker closes its owned transport."""

        if session_id == self._session_id:
            self._gate.cancel_current_stage()
            self._timer.stop()

    def _capture(self, session_id: str) -> None:
        try:
            result = self._capture_session(session_id, self._gate)
        except Exception as exc:
            with self._thread_lock:
                self._thread = None
            self.capture_failed.emit(f"{type(exc).__name__}: {exc}")
            return
        with self._thread_lock:
            self._thread = None
        self.capture_finished.emit(result)

    def _tick(self) -> None:
        snapshot = self._gate.snapshot()
        if snapshot.stage_id != self._stage_id:
            return
        if snapshot.cancelled:
            self._timer.stop()
            return
        elapsed = min(
            self._stage_duration_seconds, int(snapshot.elapsed_seconds)
        )
        if not snapshot.stage_complete:
            if elapsed != self._last_elapsed:
                self._last_elapsed = elapsed
                self._on_progress(elapsed)
            return
        if self._stage_completion_delivered:
            return

        self._stage_completion_delivered = True
        self._completed_stages += 1
        self._ui_stages_completed = self._completed_stages == len(
            self._expected_stage_ids
        )
        self._last_elapsed = self._stage_duration_seconds
        self._timer.stop()
        self._on_progress(self._stage_duration_seconds)
        self._maybe_deliver_complete()

    def _deliver_complete(self, result: object) -> None:
        self._capture_result = result
        self._maybe_deliver_complete()

    def _deliver_failure(self, message: str) -> None:
        self._timer.stop()
        self._capture_result = None
        self._on_failure(message)

    def _maybe_deliver_complete(self) -> None:
        result = self._capture_result
        if result is None or not self._ui_stages_completed:
            return
        self._capture_result = None
        self._timer.stop()
        self._on_complete(result)
