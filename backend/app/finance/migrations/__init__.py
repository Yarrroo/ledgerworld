"""Schema migrations of the ledger store, applied in order and idempotent.

One branch is one database (SQLite file) or one schema (PostgreSQL); `upgrade` brings it to the
current tables. Each step is a module with `upgrade(connection)`; steps only ever add.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection, Engine

from . import v0001_initial

STEPS = (v0001_initial,)


def upgrade(bind: Engine | Connection) -> None:
    """Apply every step; a step that already ran is a no-op."""
    if isinstance(bind, Engine):
        with bind.begin() as conn:
            upgrade(conn)
        return
    for step in STEPS:
        step.upgrade(bind)
