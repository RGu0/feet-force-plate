"""Pure institution UI session-lock state machine."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
import time


class LockTimeout(StrEnum):
    NEVER = "NEVER"
    MINUTES_5 = "5"
    MINUTES_15 = "15"
    MINUTES_30 = "30"
    MINUTES_60 = "60"

    @property
    def seconds(self) -> float | None:
        if self is LockTimeout.NEVER:
            return None
        return int(self.value) * 60.0


class SessionActivity(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    ACQUIRING = "ACQUIRING"
    FINALIZING = "FINALIZING"

    @property
    def protected(self) -> bool:
        return self in {SessionActivity.ACQUIRING, SessionActivity.FINALIZING}


class LockState(StrEnum):
    UNLOCKED = "UNLOCKED"
    LOCK_PENDING = "LOCK_PENDING"
    LOCKED = "LOCKED"


class SessionLockController:
    _FAILED_LIMIT = 5
    _FAILED_WINDOW_SECONDS = 15 * 60.0
    _LOCKOUT_SECONDS = 15 * 60.0

    def __init__(
        self,
        verify_password: Callable[[str], bool],
        *,
        timeout: LockTimeout = LockTimeout.MINUTES_30,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._verify_password = verify_password
        self._timeout = timeout
        self._monotonic = monotonic
        self._last_activity = monotonic()
        self._failed_attempts: list[float] = []
        self._locked_until: float | None = None
        self.state = LockState.UNLOCKED

    @property
    def timeout(self) -> LockTimeout:
        return self._timeout

    def set_timeout(self, timeout: LockTimeout) -> None:
        self._timeout = timeout
        self.record_activity()
        if timeout is LockTimeout.NEVER:
            self.state = LockState.UNLOCKED

    def record_activity(self) -> None:
        if self.state is LockState.UNLOCKED:
            self._last_activity = self._monotonic()

    def tick(
        self,
        activity: SessionActivity = SessionActivity.INTERACTIVE,
    ) -> LockState:
        if self.state is LockState.LOCKED:
            return self.state
        timeout_seconds = self._timeout.seconds
        if timeout_seconds is None:
            self.state = LockState.UNLOCKED
            return self.state
        if self._monotonic() - self._last_activity < timeout_seconds:
            return self.state
        self.state = (
            LockState.LOCK_PENDING if activity.protected else LockState.LOCKED
        )
        return self.state

    def protected_operation_finished(self) -> LockState:
        if self.state is LockState.LOCK_PENDING:
            self.state = LockState.LOCKED
        return self.state

    def lock_now(self) -> None:
        self.state = LockState.LOCKED

    def unlock(self, password: str) -> bool:
        now = self._monotonic()
        if self._locked_until is not None and now < self._locked_until:
            return False
        self._failed_attempts = [
            attempt
            for attempt in self._failed_attempts
            if now - attempt <= self._FAILED_WINDOW_SECONDS
        ]
        if self._verify_password(password):
            self._failed_attempts.clear()
            self._locked_until = None
            self.state = LockState.UNLOCKED
            self._last_activity = now
            return True
        self._failed_attempts.append(now)
        if len(self._failed_attempts) >= self._FAILED_LIMIT:
            self._locked_until = now + self._LOCKOUT_SECONDS
        return False


__all__ = [
    "LockState",
    "LockTimeout",
    "SessionActivity",
    "SessionLockController",
]
