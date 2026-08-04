"""Lock-independent upload/heartbeat cycle with retry-only failure semantics."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Protocol


class AccessTokenProvider(Protocol):
    def current_access_token(self) -> str: ...


class UploadQueuePort(Protocol):
    def upload_next(self, access_token: str) -> bool: ...

    def schedule_retry(self) -> None: ...


class HeartbeatPort(Protocol):
    def send(self, access_token: str, heartbeat: BackgroundHeartbeat) -> None: ...


@dataclass(frozen=True, slots=True)
class BackgroundHeartbeat:
    app_version: str
    license_active: bool
    hardware_present: bool
    installation_active: bool
    pending_sessions: int
    pending_bytes: int


@dataclass(frozen=True, slots=True)
class WorkerCycleResult:
    upload_completed: bool
    heartbeat_sent: bool
    retry_scheduled: bool


class BackgroundAccessWorker:
    """One background cycle; it has no dependency on UI visibility or lock state."""

    def __init__(
        self,
        token_provider: AccessTokenProvider,
        uploads: UploadQueuePort,
        heartbeat: HeartbeatPort,
        *,
        event_sink=None,
    ) -> None:
        self._tokens = token_provider
        self._uploads = uploads
        self._heartbeat = heartbeat
        self._event_sink = event_sink or (lambda _event: None)

    def run_cycle(self, status: BackgroundHeartbeat) -> WorkerCycleResult:
        try:
            access_token = self._tokens.current_access_token()
            uploaded = self._uploads.upload_next(access_token)
            self._heartbeat.send(access_token, status)
        except Exception:
            self._uploads.schedule_retry()
            self._event_sink("background_access.retry_scheduled")
            return WorkerCycleResult(False, False, True)
        self._event_sink("background_access.cycle_completed")
        return WorkerCycleResult(uploaded, True, False)


class BackgroundAccessScheduler:
    """Continuously retries lock-independent background access work."""

    def __init__(
        self,
        worker: BackgroundAccessWorker,
        status_provider,
        *,
        retry_interval_seconds: float = 30.0,
    ) -> None:
        if retry_interval_seconds <= 0:
            raise ValueError("retry_interval_seconds must be positive")
        self._worker = worker
        self._status_provider = status_provider
        self._retry_interval_seconds = retry_interval_seconds
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_requested.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="feetforceplate-background-access",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            try:
                self._worker.run_cycle(self._status_provider())
            except Exception:
                pass
            self._stop_requested.wait(self._retry_interval_seconds)


__all__ = [
    "AccessTokenProvider",
    "BackgroundAccessScheduler",
    "BackgroundAccessWorker",
    "BackgroundHeartbeat",
    "HeartbeatPort",
    "UploadQueuePort",
    "WorkerCycleResult",
]
