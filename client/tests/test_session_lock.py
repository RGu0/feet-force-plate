from __future__ import annotations

import unittest

from client.app.session_lock import (
    LockState,
    LockTimeout,
    SessionActivity,
    SessionLockController,
)


class SessionLockControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_000.0
        self.password_calls: list[str] = []
        self.controller = SessionLockController(
            lambda password: self.password_calls.append(password) or password == "correct",
            monotonic=lambda: self.now,
        )

    def test_default_and_supported_timeout_options(self) -> None:
        self.assertEqual(self.controller.timeout, LockTimeout.MINUTES_30)
        self.assertEqual(
            {item.seconds for item in LockTimeout},
            {None, 300.0, 900.0, 1800.0, 3600.0},
        )

    def test_user_activity_resets_timeout_and_never_disables_locking(self) -> None:
        self.now += 29 * 60
        self.controller.record_activity()
        self.now += 29 * 60
        self.assertEqual(self.controller.tick(), LockState.UNLOCKED)
        self.controller.set_timeout(LockTimeout.NEVER)
        self.now += 24 * 60 * 60
        self.assertEqual(self.controller.tick(), LockState.UNLOCKED)

    def test_timeout_during_acquisition_defers_visual_lock_until_finish(self) -> None:
        self.now += 30 * 60
        self.assertEqual(
            self.controller.tick(SessionActivity.ACQUIRING),
            LockState.LOCK_PENDING,
        )
        self.assertEqual(
            self.controller.protected_operation_finished(),
            LockState.LOCKED,
        )

    def test_timeout_during_finalization_also_defers_then_locks(self) -> None:
        self.now += 30 * 60
        self.assertEqual(
            self.controller.tick(SessionActivity.FINALIZING),
            LockState.LOCK_PENDING,
        )
        self.controller.protected_operation_finished()
        self.assertEqual(self.controller.state, LockState.LOCKED)

    def test_unlock_requires_password_and_rate_limits_failures(self) -> None:
        self.controller.lock_now()
        for _ in range(5):
            self.assertFalse(self.controller.unlock("wrong"))
        self.assertFalse(self.controller.unlock("correct"))
        self.assertEqual(len(self.password_calls), 5)
        self.now += 15 * 60 + 1
        self.assertTrue(self.controller.unlock("correct"))
        self.assertEqual(self.controller.state, LockState.UNLOCKED)


if __name__ == "__main__":
    unittest.main()
