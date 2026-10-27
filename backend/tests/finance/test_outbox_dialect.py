"""The outbox installs its tables on any store, not only SQLite.

`install` used to probe for `execution_legs` in `sqlite_master`. PostgreSQL has no such table:
the probe raised, the connection's transaction was left aborted, and the next query on it failed,
so the first request after the gateway started answered 500. The check is now dialect-neutral:
`sqlite_master` only on a SQLite connection, `information_schema` everywhere else, and a
non-SQLite install leaves no transaction open behind it. The `pg` test runs it on PostgreSQL.
"""

from __future__ import annotations

import os
import sqlite3

import pytest
from app.execution import outbox as ob

SQLITE_ONLY = ("sqlite_master", "sqlite_schema", "pragma", "executescript")


class RecordingConnection:
    """A DB-API connection that is not SQLite: it records each statement, and refuses the
    SQLite catalogue the way PostgreSQL does."""

    def __init__(self, tables: set[str]) -> None:
        self.tables = tables
        self.statements: list[str] = []
        self.commits = 0
        self.rolled_back = 0

    def execute(self, sql: str, params: tuple = ()) -> RecordingConnection:
        self.statements.append(sql)
        if any(word in sql.lower() for word in SQLITE_ONLY):
            raise RuntimeError(f'relation "{sql}" does not exist')
        self._row = None
        if "information_schema.tables" in sql:
            self._row = (1,) if any(f"'{t}'" in sql for t in self.tables) else None
        return self

    def fetchone(self) -> tuple | None:
        return self._row

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rolled_back += 1


def test_install_never_issues_a_sqlite_only_statement_on_another_connection():
    conn = RecordingConnection(tables=set())
    ob.install(conn)
    assert not [s for s in conn.statements if any(w in s.lower() for w in SQLITE_ONLY)]
    assert any("information_schema.tables" in s for s in conn.statements)
    created = [s for s in conn.statements if s.lstrip().upper().startswith("CREATE")]
    assert any("CREATE TABLE execution_legs" in s for s in created)
    assert all(";" not in s for s in created)  # one statement per call, as a server driver takes
    assert conn.commits == 1  # the install's transaction is closed, never left to the next query


def test_install_on_another_connection_creates_nothing_when_the_tables_exist():
    conn = RecordingConnection(tables={"execution_legs"})
    ob.install(conn)
    assert not [s for s in conn.statements if s.lstrip().upper().startswith("CREATE")]
    assert conn.commits == 1


def test_install_on_sqlite_creates_the_tables_once():
    conn = sqlite3.connect(":memory:")
    ob.install(conn)
    ob.install(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"approvals", "execution_legs", "leg_events", "incidents"} <= names


@pytest.mark.pg
def test_install_leaves_a_postgres_connection_usable():
    url = os.environ.get("LEDGER_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("LEDGER_DATABASE_URL names no PostgreSQL database")
    import psycopg

    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        ob.install(conn)
        ob.install(conn)
        assert conn.execute("SELECT count(*) FROM execution_legs").fetchone() is not None
