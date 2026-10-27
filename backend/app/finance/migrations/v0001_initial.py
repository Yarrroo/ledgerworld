"""The initial ledger tables (design/modules/ledger/schema.sql)."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from ..models import metadata


def upgrade(conn: Connection) -> None:
    metadata.create_all(conn, checkfirst=True)
