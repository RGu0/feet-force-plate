"""RAY-447 R8: the client's own SQLite stores run under foundation's durability policy."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from techflex_cloud_foundation import inspect_durability

from client.support.durable_sqlite import open_durable


def test_a_store_connection_gets_the_durability_pragmas_and_stays_a_plain_connection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "store.sqlite3"

    connection = open_durable(path)

    status = inspect_durability(connection)
    assert (status.journal_mode, status.synchronous, status.busy_timeout_ms) == ("WAL", "FULL", 5000)
    assert not status.foreign_keys  # enforcement stays as these stores always had it
    assert isinstance(connection, sqlite3.Connection) and connection.row_factory is None
    connection.execute("CREATE TABLE t (a INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    assert connection.execute("SELECT a FROM t").fetchall() == [(1,)]  # tuples, not sqlite3.Row
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    connection.close()


class _MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_the_institution_and_local_replay_stores_open_in_wal_with_full_sync(tmp_path: Path) -> None:
    from client.app.institution_store import InstitutionLocalStore
    from client.app.local_store import LocalReplayStore

    institution = InstitutionLocalStore.open(tmp_path / "institution", credential_vault=_MemoryVault())
    replay = LocalReplayStore(tmp_path / "replay", credential_vault=_MemoryVault())
    try:
        for store in (institution, replay):
            status = inspect_durability(store.db)
            assert (status.journal_mode, status.synchronous) == ("WAL", "FULL")
            assert not status.foreign_keys
    finally:
        institution.db.close()
        replay.db.close()
