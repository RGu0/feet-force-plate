"""Explicit, single-session local cleanup for a deployment-owned support flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from client.spool.session_commit import delete_completed_valid_session
from client.spool.state_store import StateStore


class SessionDeletionConfirmationRequired(PermissionError):
    """The operator did not supply the exact per-session confirmation."""


@dataclass(frozen=True, slots=True)
class CompletedSessionDeletionService:
    """Expose no bulk or automatic cleanup operation to the application shell."""

    root: Path
    store: StateStore

    def candidates(self) -> tuple[str, ...]:
        return self.store.completed_valid_session_ids()

    def delete(self, *, session_id: str, confirmation: str) -> None:
        if confirmation != f"删除 {session_id}":
            raise SessionDeletionConfirmationRequired("exact session confirmation required")
        if session_id not in self.candidates():
            raise ValueError("selected session is unavailable for manual deletion")
        delete_completed_valid_session(self.root, session_id=session_id, store=self.store)
