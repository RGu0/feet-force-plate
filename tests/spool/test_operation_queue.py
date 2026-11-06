"""RAY-447: the formal-session upload queue lives in foundation's operation store."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from client.spool.operation_queue import (
    datetime_from_ns,
    idempotency_key,
    ns_from_datetime,
)
from client.spool.state_store import (
    SCHEMA_VERSION,
    SensitiveBlobCodec,
    StateStore,
    ValidSegmentRecord,
)


class _Keys:
    def get_key(self) -> bytes:
        return b"k" * 32


def _open(path: Path) -> StateStore:
    return StateStore(path, SensitiveBlobCodec(_Keys()))


def _commit(store: StateStore, index: int, *, byte_count: int = 8) -> str:
    session_id = f"session-{index}"
    store.commit_valid_session(
        session_id,
        subject_uuid="subject-uuid",
        consent_id=None,
        versions_json=b'{"protocol":"static-balance/1"}',
        started_at_ns=(10 + index) * 1_000_000,
        ended_at_ns=(20 + index) * 1_000_000,
        manifest_sha256=f"{index:064x}",
        segments=(
            ValidSegmentRecord(
                segment_id=f"segment-{index}",
                relative_path=f"sessions/{session_id}/segment-{index}.ffps",
                byte_count=byte_count,
                sealed_at_ns=(20 + index) * 1_000_000,
            ),
        ),
    )
    return session_id


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.sqlite3"


@pytest.fixture
def store(db_path: Path):
    opened = _open(db_path)
    opened.put_subject_ref("subject-uuid", b"opaque")
    yield opened
    opened.close()


def _operation_rows(path: Path) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM foundation_operations ORDER BY idempotency_key"
        ).fetchall()


def _make_v12(path: Path, states: dict[str, dict[str, object]]) -> None:
    """Rewrite a current database into the v12 shape: queue state inside sync_handoffs."""

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP TABLE foundation_operations")
        connection.execute("DROP INDEX idx_sync_handoffs_operation")
        connection.execute("ALTER TABLE sync_handoffs DROP COLUMN operation_id")
        connection.execute(
            "ALTER TABLE sync_handoffs ADD COLUMN state TEXT NOT NULL DEFAULT 'READY_FOR_NETWORK'"
        )
        connection.execute(
            "ALTER TABLE sync_handoffs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
        )
        connection.execute("ALTER TABLE sync_handoffs ADD COLUMN next_attempt_at_ns INTEGER")
        connection.execute("ALTER TABLE sync_handoffs ADD COLUMN last_error_code TEXT")
        connection.execute(
            "CREATE INDEX idx_sync_handoffs_state "
            "ON sync_handoffs(state, created_at_ns, session_id)"
        )
        for session_id, values in states.items():
            connection.execute(
                """UPDATE sync_handoffs SET state=?, attempt_count=?, next_attempt_at_ns=?,
                last_error_code=?, cloud_confirmed_at_ns=? WHERE session_id=?""",
                (
                    values["state"], values.get("attempts", 0), values.get("next"),
                    values.get("error"), values.get("confirmed"), session_id,
                ),
            )
        connection.execute("PRAGMA user_version=12")
        connection.commit()


def test_v12_queue_state_moves_into_the_operation_store_without_loss(
    db_path: Path, store: StateStore
) -> None:
    sessions = [_commit(store, index) for index in range(6)]
    store.close()
    due_ns = 1_700_000_000_123_456_000
    _make_v12(db_path, {
        "session-0": {"state": "READY_FOR_NETWORK"},
        "session-1": {"state": "RETRY_WAIT", "attempts": 3, "next": due_ns, "error": "E-NET-503"},
        "session-2": {"state": "BLOCKED", "attempts": 1, "error": "E-AUT-403"},
        "session-3": {"state": "CONFLICT", "attempts": 2, "error": "E-SUB-409"},
        "session-4": {"state": "CLOUD_CONFIRMED", "attempts": 1, "confirmed": 99},
        "session-5": {"state": "UPLOADING", "attempts": 4},
    })

    migrated = _open(db_path)
    try:
        assert migrated.schema_version == SCHEMA_VERSION == 13
        assert [migrated.sync_handoff_state(session_id) for session_id in sessions] == [
            "READY_FOR_NETWORK", "RETRY_WAIT", "BLOCKED", "CONFLICT",
            "CLOUD_CONFIRMED", "UPLOADING",
        ]
        assert migrated.sync_handoff_retry_state("session-1") == (3, due_ns, "E-NET-503")
        assert migrated.sync_handoff_retry_state("session-2") == (1, None, "E-AUT-403")
        assert migrated.sync_handoff_retry_state("session-3") == (2, None, "E-SUB-409")
        # The queue was not cleared: five of six sessions are still pending.
        assert migrated.offline_snapshot().pending_session_count == 5
        assert migrated.valid_local_storage_snapshot().last_cloud_confirmed_at_ns == 99
        # The interrupted lease is released by the normal crash recovery.
        assert migrated.recover_interrupted_state(recovered_at_ns=1).sync_handoffs_requeued == 1
        assert migrated.sync_handoff_state("session-5") == "READY_FOR_NETWORK"
    finally:
        migrated.close()

    rows = _operation_rows(db_path)
    assert [row["idempotency_key"] for row in rows] == [idempotency_key(s) for s in sessions]
    assert {row["kind"] for row in rows} == {"ffp.formal-session-upload"}
    with closing(sqlite3.connect(db_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(sync_handoffs)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(sync_handoffs)")}
    assert not columns & {"state", "attempt_count", "next_attempt_at_ns", "last_error_code"}
    assert "operation_id" in columns and "cloud_confirmed_at_ns" in columns
    assert "idx_sync_handoffs_state" not in indexes


def test_an_unknown_legacy_state_fails_closed_and_leaves_the_database_at_v12(
    db_path: Path, store: StateStore
) -> None:
    _commit(store, 0)
    store.close()
    _make_v12(db_path, {"session-0": {"state": "SOMETHING_ELSE"}})

    with pytest.raises(ValueError, match="unknown upload queue state"):
        _open(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 12
        columns = {row[1] for row in connection.execute("PRAGMA table_info(sync_handoffs)")}
    assert "state" in columns  # the failed migration rolled back completely


def test_queue_changes_roll_back_with_the_surrounding_transaction(store: StateStore) -> None:
    session_id = _commit(store, 0)
    assert store.lease_sync_handoff(now_ns=1) is not None

    with pytest.raises(RuntimeError, match="boom"):
        with store._lock, store._connection:
            # The store's own methods commit; the attached queue itself must not.
            store._queue.block(store._operation_id(session_id), error_code="E-SYN-400")
            raise RuntimeError("boom")

    assert store.sync_handoff_state(session_id) == "UPLOADING"


def test_deleting_a_completed_session_leaves_no_queue_entry_behind(
    db_path: Path, store: StateStore
) -> None:
    session_id = _commit(store, 0)
    assert store.lease_sync_handoff(now_ns=1) is not None
    store.mark_cloud_confirmed(session_id, confirmed_at_ns=5)
    assert len(_operation_rows(db_path)) == 1

    store.delete_completed_valid_session(session_id)

    assert _operation_rows(db_path) == []


def test_a_handoff_whose_queue_entry_is_missing_is_queued_again_on_open(
    db_path: Path, store: StateStore
) -> None:
    session_id = _commit(store, 0)
    with closing(sqlite3.connect(db_path)) as connection:
        operation_id = connection.execute(
            "SELECT operation_id FROM sync_handoffs WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        connection.execute("DELETE FROM foundation_operations")
        connection.commit()
    store.close()

    healed = _open(db_path)
    try:
        assert healed.sync_handoff_state(session_id) == "READY_FOR_NETWORK"
    finally:
        healed.close()
    assert [row["operation_id"] for row in _operation_rows(db_path)] == [operation_id]


def test_a_handoff_without_an_operation_id_gets_one_on_open(
    db_path: Path, store: StateStore
) -> None:
    session_id = _commit(store, 0)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DROP INDEX idx_sync_handoffs_operation")
        connection.execute("UPDATE sync_handoffs SET operation_id=NULL")
        connection.execute("DELETE FROM foundation_operations")
        connection.commit()
    store.close()

    healed = _open(db_path)
    try:
        assert healed.sync_handoff_state(session_id) == "READY_FOR_NETWORK"
        handoff = healed.lease_sync_handoff(now_ns=1)
        assert handoff is not None and handoff.session_id == session_id
    finally:
        healed.close()


def test_the_lease_order_follows_the_session_end_time(store: StateStore) -> None:
    for index in (2, 0, 1):
        _commit(store, index)

    leased = [store.lease_sync_handoff(now_ns=1) for _ in range(3)]

    assert [handoff.session_id for handoff in leased if handoff] == [
        "session-0", "session-1", "session-2",
    ]
    assert store.lease_sync_handoff(now_ns=1) is None


def test_only_a_leased_upload_can_be_confirmed(store: StateStore) -> None:
    session_id = _commit(store, 0)

    with pytest.raises(KeyError):
        store.mark_cloud_confirmed(session_id, confirmed_at_ns=5)

    assert store.lease_sync_handoff(now_ns=1) is not None
    store.mark_cloud_confirmed(session_id, confirmed_at_ns=5)
    assert store.sync_handoff_state(session_id) == "CLOUD_CONFIRMED"


def test_the_foundation_table_still_has_the_columns_this_client_writes(
    db_path: Path, store: StateStore
) -> None:
    """`operation_queue` imports and purges rows directly: fail if foundation moves them."""

    with closing(sqlite3.connect(db_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(foundation_operations)")}
    assert columns == {
        "operation_id", "kind", "payload_ref", "payload_digest", "idempotency_key",
        "created_at", "state", "attempt_count", "next_attempt_at", "error_code",
    }


def test_nanosecond_times_round_trip_at_microsecond_resolution() -> None:
    value_ns = 1_700_000_000_123_456_789
    assert ns_from_datetime(datetime_from_ns(value_ns)) == 1_700_000_000_123_456_000
    assert datetime_from_ns(0).isoformat() == "1970-01-01T00:00:00+00:00"


def test_a_legacy_retry_wait_without_a_deadline_is_leased_after_migration(
    db_path: Path, store: StateStore
) -> None:
    # Rows written before schema v7 have no deadline; v12 leased them at once.
    _commit(store, 0)
    store.close()
    _make_v12(db_path, {"session-0": {"state": "RETRY_WAIT", "attempts": 3, "error": "E-NET-503"}})

    migrated = _open(db_path)
    try:
        assert migrated.sync_handoff_state("session-0") == "RETRY_WAIT"
        handoff = migrated.lease_sync_handoff(now_ns=1_000_000_000)
        assert handoff is not None and handoff.session_id == "session-0"
        assert handoff.attempt_count == 4
    finally:
        migrated.close()


def test_a_handoff_with_a_cloud_receipt_stays_confirmed_when_its_entry_is_rebuilt(
    db_path: Path, store: StateStore
) -> None:
    session_id = _commit(store, 0)
    assert store.lease_sync_handoff(now_ns=1) is not None
    store.mark_cloud_confirmed(session_id, confirmed_at_ns=5)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("DELETE FROM foundation_operations")
        connection.commit()
    store.close()

    healed = _open(db_path)
    try:
        assert healed.sync_handoff_state(session_id) == "CLOUD_CONFIRMED"
        assert healed.offline_snapshot().pending_session_count == 0
        assert healed.lease_sync_handoff(now_ns=1) is None
    finally:
        healed.close()


def test_a_confirmation_is_durable_across_a_reopen(db_path: Path, store: StateStore) -> None:
    session_id = _commit(store, 0)
    assert store.lease_sync_handoff(now_ns=1) is not None
    store.mark_cloud_confirmed(session_id, confirmed_at_ns=5)
    store.close()

    reopened = _open(db_path)
    try:
        assert reopened.sync_handoff_state(session_id) == "CLOUD_CONFIRMED"
        assert reopened.valid_local_storage_snapshot().last_cloud_confirmed_at_ns == 5
    finally:
        reopened.close()


def test_only_a_leased_upload_can_be_blocked_or_conflicted(store: StateStore) -> None:
    session_id = _commit(store, 0)

    with pytest.raises(KeyError):
        store.mark_sync_handoff_blocked(session_id, error_code="E-SYN-400")
    with pytest.raises(KeyError):
        store.mark_sync_handoff_conflict(session_id)

    assert store.sync_handoff_state(session_id) == "READY_FOR_NETWORK"


def test_the_retry_deadline_is_reported_only_while_waiting_to_retry(store: StateStore) -> None:
    session_id = _commit(store, 0)
    assert store.lease_sync_handoff(now_ns=1_000_000) is not None
    store.defer_sync_handoff(session_id, error_code="E-NET-503", next_attempt_at_ns=2_000_000)
    assert store.sync_handoff_retry_state(session_id) == (1, 2_000_000, "E-NET-503")

    assert store.lease_sync_handoff(now_ns=3_000_000) is not None
    assert store.sync_handoff_state(session_id) == "UPLOADING"
    attempts, due_ns, _ = store.sync_handoff_retry_state(session_id)
    assert (attempts, due_ns) == (2, None)  # no stale deadline once it is leased again

    store.mark_sync_handoff_blocked(session_id, error_code="E-SYN-400")
    assert store.sync_handoff_retry_state(session_id) == (2, None, "E-SYN-400")


def test_committing_a_session_over_a_stale_queue_entry_fails_and_commits_nothing(
    db_path: Path, store: StateStore
) -> None:
    session_id = _commit(store, 0)
    store.close()
    with closing(sqlite3.connect(db_path)) as connection:
        # Delete the session without the purge, as a bug or manual repair might.
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("DELETE FROM segments WHERE session_id=?", (session_id,))
        connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        connection.commit()
        assert connection.execute("SELECT COUNT(*) FROM foundation_operations").fetchone()[0] == 1

    reopened = _open(db_path)
    try:
        with pytest.raises(RuntimeError, match="already exists"):
            _commit(reopened, 0)
    finally:
        reopened.close()

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM sync_handoffs").fetchone()[0] == 0
