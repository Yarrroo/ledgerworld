"""The same ledger cases on PostgreSQL (`LEDGER_DATABASE_URL`); marked `pg`, run in CI only.

The merge gate deselects `pg`; CI's postgres job runs `pytest -m pg` against a fresh database.
"""

from __future__ import annotations

import os

import pytest
from app.finance.models import metadata
from sqlalchemy import create_engine
from test_fixtures import assert_paths, lf1
from test_fixtures import world as lf1_world
from test_ledger import design, run_case, run_path

pytestmark = pytest.mark.pg


@pytest.fixture
def url():
    url = os.environ.get("LEDGER_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("LEDGER_DATABASE_URL names no PostgreSQL database")
    engine = create_engine(url)
    metadata.drop_all(engine)
    engine.dispose()
    return url


@pytest.mark.parametrize("case", design("invariants")["cases"], ids=lambda c: c["id"])
def test_invariant_on_postgres(url, case):
    run_case(case, url)


@pytest.mark.parametrize("path", design("reservation-lifecycle")["paths"], ids=lambda p: p["id"])
def test_reservation_lifecycle_on_postgres(url, path):
    run_path(path, url)


def test_lf1_on_postgres(url):
    assert_paths(lf1_world(url), lf1()["expected"]["no_shock"])
