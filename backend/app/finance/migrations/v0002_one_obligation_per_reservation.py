"""One reservation backs at most one obligation: the unique index on obligations.reservation_id.

A fresh database gets it from v0001's `create_all`; this adds it to one created before it.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

from ..models import obligations


def upgrade(conn: Connection) -> None:
    index = next(i for i in obligations.indexes if i.name == "obligations_one_per_reservation")
    index.create(conn, checkfirst=True)
