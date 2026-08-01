from __future__ import annotations

import threading
import unittest

from client.app.session_lock import SessionLockController
from client.sync.worker import BackgroundAccessWorker, BackgroundHeartbeat


class TokenProvider:
    def __init__(self) -> None:
        self.token = "access-token-secret-value-at-least-20"
        self.calls = 0
        self.fail = False
        self._lock = threading.Lock()

    def current_access_token(self) -> str:
        with self._lock:
            self.calls += 1
            if self.fail:
                raise RuntimeError("refresh unavailable")
            return self.token


class UploadQueue:
    def __init__(self) -> None:
        self.uploaded_with: list[str] = []
        self.retry_count = 0
        self.sealed_payload_present = True

    def upload_next(self, access_token: str) -> bool:
        self.uploaded_with.append(access_token)
        return True

    def schedule_retry(self) -> None:
        self.retry_count += 1


class Heartbeats:
    def __init__(self) -> None:
        self.sent = []

    def send(self, access_token: str, heartbeat: BackgroundHeartbeat) -> None:
        self.sent.append((access_token, heartbeat))


class BackgroundAccessContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tokens = TokenProvider()
        self.uploads = UploadQueue()
        self.heartbeats = Heartbeats()
        self.events: list[str] = []
        self.worker = BackgroundAccessWorker(
            self.tokens,
            self.uploads,
            self.heartbeats,
            event_sink=self.events.append,
        )
        self.status = BackgroundHeartbeat(
            app_version="0.1.0",
            license_active=True,
            hardware_present=True,
            installation_active=True,
            pending_sessions=1,
            pending_bytes=1024,
        )

    def test_upload_and_heartbeat_continue_while_ui_session_is_locked(self) -> None:
        lock = SessionLockController(lambda _password: True)
        lock.lock_now()

        result = self.worker.run_cycle(self.status)

        self.assertTrue(result.upload_completed)
        self.assertTrue(result.heartbeat_sent)
        self.assertTrue(lock.state.value == "LOCKED")
        self.assertEqual(len(self.uploads.uploaded_with), 1)
        self.assertEqual(len(self.heartbeats.sent), 1)

    def test_refresh_failure_schedules_retry_without_deleting_sealed_data(self) -> None:
        self.tokens.fail = True

        result = self.worker.run_cycle(self.status)

        self.assertTrue(result.retry_scheduled)
        self.assertEqual(self.uploads.retry_count, 1)
        self.assertTrue(self.uploads.sealed_payload_present)
        self.assertEqual(self.events, ["background_access.retry_scheduled"])
        combined = " ".join(self.events)
        self.assertNotIn(self.tokens.token, combined)

    def test_heartbeat_contains_status_not_raw_account_hardware_or_installation_ids(self) -> None:
        self.worker.run_cycle(self.status)
        _token, heartbeat = self.heartbeats.sent[0]

        self.assertEqual(heartbeat.pending_sessions, 1)
        self.assertFalse(hasattr(heartbeat, "account_id"))
        self.assertFalse(hasattr(heartbeat, "hardware_id"))
        self.assertFalse(hasattr(heartbeat, "client_installation_id"))


if __name__ == "__main__":
    unittest.main()
