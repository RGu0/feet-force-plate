"""Durable SQLite connections for the client's own stores (RAY-447 R8).

foundation's ``connect_durable`` applies the WAL/FULL/busy-timeout policy and
creates the file owner-only.  It also turns foreign-key enforcement on, installs
``sqlite3.Row`` and lifts the thread check; these stores relied on none of that,
so the connection is returned as the plain ``sqlite3`` one they always had,
with enforcement left as it was.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

from techflex_cloud_foundation import LocalSqlitePolicy, connect_durable

_POLICY = LocalSqlitePolicy(foreign_keys=False)


def open_durable(path: str | Path) -> sqlite3.Connection:
    connection = connect_durable(path, _POLICY).raw
    connection.row_factory = None
    return connection
