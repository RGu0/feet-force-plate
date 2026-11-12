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
