from __future__ import annotations

from client.app.session_lock import SessionLockController
from client.sync.runtime import PackagedUploadRuntime


def test_upload_runtime_recovers_before_one_daemon_scheduler_and_closes_only_owned_network_resources() -> None:
    """Catch a restart that races upload recovery, duplicates workers, or closes shared SQLite."""

    order: list[str] = []

    class _PhysicalStore:
        def recover_interrupted_state(self, *, recovered_at_ns: int) -> None:
            assert recovered_at_ns > 0
            order.append("recover_interrupted_state")

        def close(self) -> None:
            order.append("physical_store.close")

    class _UploadScheduler:
        def start(self) -> None:
            order.append("upload_scheduler.start")

        def stop(self) -> None:
            order.append("upload_scheduler.stop")

    class _HttpClient:
        def close(self) -> None:
            order.append("http.close")

    runtime = PackagedUploadRuntime(
        physical_store=_PhysicalStore(),
        upload_scheduler=_UploadScheduler(),
        http_client=_HttpClient(),
    )

    runtime.start()
    runtime.start()
    lock = SessionLockController(lambda _password: True)
    lock.lock_now()

    assert lock.state.value == "LOCKED"
    assert "upload_scheduler.stop" not in order

    runtime.close()
    runtime.close()

    assert order[:2] == ["recover_interrupted_state", "upload_scheduler.start"]
    assert order.count("upload_scheduler.start") == 1
    assert order.count("upload_scheduler.stop") == 1
    assert order.count("http.close") == 1
    assert "physical_store.close" not in order
