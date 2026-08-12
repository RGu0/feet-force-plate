"""Packaged ownership boundary for durable, lock-independent uploads."""

from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import Any, Protocol
from uuid import UUID

from client.spool.state_store import KeyProvider, StateStore

from .persistent_upload import HttpIngestionClient, PersistentUploadQueue


_LOGGER = logging.getLogger(__name__)
_UNEXPECTED_UPLOAD_ERROR_CODE = "E-SYN-500"


class _AccessTokenRuntime(Protocol):
    def current_access_token(self) -> str: ...

    def refresh(self) -> object: ...


class _LeaseTrackingStore:
    """Track only the lease owned by one scheduler cycle around a shared store."""

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._leased_session_id: str | None = None
        self._lock = threading.Lock()

    def begin_cycle(self) -> None:
        with self._lock:
            self._leased_session_id = None

    def lease_sync_handoff(self, *, now_ns: int):
        handoff = self._store.lease_sync_handoff(now_ns=now_ns)
        with self._lock:
            self._leased_session_id = (
                None if handoff is None else str(handoff.session_id)
            )
        return handoff

    def finish_cycle(self) -> None:
        with self._lock:
            self._leased_session_id = None

    def block_escaped_lease(self) -> None:
        with self._lock:
            session_id = self._leased_session_id
            self._leased_session_id = None
        if session_id is None:
            return
        self._store.mark_sync_handoff_blocked(
            session_id,
            error_code=_UNEXPECTED_UPLOAD_ERROR_CODE,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


class _RecoverableUploadQueue:
    """Expose escaped-lease recovery without changing the durable queue contract."""

    def __init__(self, queue: PersistentUploadQueue, store: _LeaseTrackingStore) -> None:
        self._queue = queue
        self._store = store

    def upload_next(self, access_runtime: _AccessTokenRuntime):
        self._store.begin_cycle()
        try:
            outcome = self._queue.upload_next(access_runtime)
        except Exception:
            raise
        else:
            self._store.finish_cycle()
            return outcome

    def recover_escaped_lease(self) -> None:
        self._store.block_escaped_lease()


class _UploadScheduler:
    """One daemon worker; durable queue due times choose when actual retries occur."""

    def __init__(
        self,
        queue: PersistentUploadQueue,
        access_runtime: _AccessTokenRuntime,
        *,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._queue = queue
        self._access_runtime = access_runtime
        self._poll_interval_seconds = poll_interval_seconds
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
                name="feetforceplate-persistent-upload",
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
                self._queue.upload_next(self._access_runtime)
            except Exception:
                try:
                    recover = getattr(self._queue, "recover_escaped_lease", None)
                    if recover is not None:
                        recover()
                except Exception:
                    _LOGGER.error(
                        "packaged upload lease recovery failed: %s",
                        _UNEXPECTED_UPLOAD_ERROR_CODE,
                    )
                _LOGGER.error(
                    "packaged upload cycle failed: %s",
                    _UNEXPECTED_UPLOAD_ERROR_CODE,
                )
            self._stop_requested.wait(self._poll_interval_seconds)


class PackagedUploadRuntime:
    """Own HTTP and its single upload worker, never the shared local stores."""

    def __init__(self, *, physical_store, upload_scheduler, http_client) -> None:
        self._physical_store = physical_store
        self._upload_scheduler = upload_scheduler
        self._http_client = http_client
        self._lock = threading.RLock()
        self._started = False
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("packaged upload runtime is already closed")
            if self._started:
                return
            self._physical_store.recover_interrupted_state(recovered_at_ns=time.time_ns())
            try:
                self._upload_scheduler.start()
            except Exception:
                self._upload_scheduler.stop()
                raise
            self._started = True

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._upload_scheduler.stop()
            self._started = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.stop()
            close = getattr(self._http_client, "close", None)
            if close is not None:
                close()


def build_packaged_upload_runtime(
    data_root: Path,
    settings,
    session,
    access_runtime: _AccessTokenRuntime,
    key_provider: KeyProvider,
    institution_store,
    physical_store: StateStore,
) -> PackagedUploadRuntime:
    """Compose upload dependencies from the authenticated shared local resources."""

    del institution_store
    http_client = HttpIngestionClient(
        settings.base_url,
        terminal_id=UUID(str(session.client_installation_id)),
        verify=settings.verify,
    )
    tracking_store = _LeaseTrackingStore(physical_store)
    try:
        queue = PersistentUploadQueue(
            tracking_store,
            data_root,
            key_provider,
            http_client,
        )
        scheduler = _UploadScheduler(
            _RecoverableUploadQueue(queue, tracking_store), access_runtime
        )
    except Exception:
        http_client.close()
        raise
    return PackagedUploadRuntime(
        physical_store=physical_store,
        upload_scheduler=scheduler,
        http_client=http_client,
    )


__all__ = ["PackagedUploadRuntime", "build_packaged_upload_runtime"]
