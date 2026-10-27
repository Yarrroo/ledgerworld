"""One reservation backs at most one obligation: the unique index on obligations.reservation_id.

A fresh database gets it from v0001's `create_all`; this adds it to one created before it. A
database that already pays two obligations from one reservation is refused by name, not mended:
which of them the payment met is not this step's to decide.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

INDEX = "obligations_one_per_reservation"
SHARED = text("SELECT reservation_id, obligation_id FROM obligations WHERE reservation_id IN ("
              "SELECT reservation_id FROM obligations WHERE reservation_id IS NOT NULL "
              "GROUP BY reservation_id HAVING count(*) > 1) ORDER BY reservation_id, obligation_id")


def upgrade(conn: Connection) -> None:
    if INDEX in {i["name"] for i in inspect(conn).get_indexes("obligations")}:
        return
    shared = conn.execute(SHARED).all()
    if shared:
        raise ValueError(f"obligations share a reservation: {[tuple(r) for r in shared]}")
    conn.exec_driver_sql(f"CREATE UNIQUE INDEX {INDEX} ON obligations (reservation_id)")
