"""Formal-session upload queue state on the foundation operation store (RAY-447).

The queue state of a formal-session upload (ready, leased, retry wait, blocked,
conflict, confirmed) lives in foundation's ``SqliteOperationStore``, attached to
the state store's own SQLite connection so a queue change and an application
change commit or roll back together.  ``sync_handoffs`` keeps only what is
specific to this application (manifest, encrypted envelope and credential,
local analysis, cloud receipt time) plus the ``operation_id`` that links a
handoff to its operation.

foundation 0.9.2 has no public call to import an operation in a given state or
to purge one, so exactly two statements here touch ``foundation_operations``
directly: :func:`import_legacy_operation` (the one-time v12 to v13 migration,
which must keep each queue entry's state, attempt count, retry time and error
code) and :func:`purge_operation` (deleting a completed session must not leave
its identifiers behind).  ``tests/spool/test_operation_queue.py`` fails if the
foundation table stops having the columns used below.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3
from uuid import UUID, uuid4

from techflex_cloud_foundation import OperationState, ReliableOperation

QUEUE_KIND = "ffp.formal-session-upload"

#: Names the rest of the client (and its tests) have always used for these states.
LEGACY_STATE_NAMES: dict[OperationState, str] = {
    OperationState.READY: "READY_FOR_NETWORK",
    OperationState.LEASED: "UPLOADING",
    OperationState.RETRY_WAIT: "RETRY_WAIT",
    OperationState.CONFIRMED: "CLOUD_CONFIRMED",
    OperationState.BLOCKED: "BLOCKED",
    OperationState.CONFLICT: "CONFLICT",
}
_FROM_LEGACY_STATE = {name: state for state, name in LEGACY_STATE_NAMES.items()}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def idempotency_key(session_id: str) -> str:
    return f"upload:{session_id}"


def datetime_from_ns(value_ns: int) -> datetime:
    """Exact UTC datetime for a nanosecond epoch (sub-microsecond part is dropped)."""

    return _EPOCH + timedelta(microseconds=value_ns // 1000)


def ns_from_datetime(value: datetime) -> int:
    return (value.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1) * 1000


def new_operation(
    session_id: str,
    manifest_sha256: str,
    created_at_ns: int,
    *,
    operation_id: UUID | None = None,
) -> ReliableOperation:
    """The queue entry for one formal session; ordering follows the session end time."""

    return ReliableOperation(
        operation_id or uuid4(),
        QUEUE_KIND,
        session_id,
        manifest_sha256,
        idempotency_key(session_id),
        datetime_from_ns(created_at_ns),
    )


def import_legacy_operation(
    connection: sqlite3.Connection,
    operation: ReliableOperation,
    *,
    legacy_state: str,
    attempt_count: int,
    next_attempt_at_ns: int | None,
    error_code: str | None,
) -> None:
    """One-time migration: store an existing queue entry in its current state.

    Fails closed on a state this client never wrote.  Runs inside the caller's
    transaction.
    """

    try:
        state = _FROM_LEGACY_STATE[legacy_state]
    except KeyError:
        raise ValueError(f"unknown upload queue state {legacy_state!r}") from None
    connection.execute(
        """INSERT INTO foundation_operations
        (operation_id, kind, payload_ref, payload_digest, idempotency_key, created_at,
         state, attempt_count, next_attempt_at, error_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(operation.operation_id), operation.kind, operation.payload_ref,
            operation.payload_digest, operation.idempotency_key,
            _encode(operation.created_at), str(state), attempt_count,
            None if next_attempt_at_ns is None else _encode(datetime_from_ns(next_attempt_at_ns)),
            error_code,
        ),
    )


def purge_operation(connection: sqlite3.Connection, operation_id: str) -> None:
    """Remove the operation of a deleted session; runs inside the caller's transaction."""

    connection.execute(
        "DELETE FROM foundation_operations WHERE operation_id=?", (operation_id,)
    )


def _encode(value: datetime) -> str:
    # Same text form foundation writes, so its due-time comparisons stay valid.
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
