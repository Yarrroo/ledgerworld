"""Keep legacy API tests independent of deployed provider and datastore settings."""

import os

import pytest
from app.api.v1.services import Services
from app.simulation.scenarios import load_world


@pytest.fixture
def offline_legacy_services(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    def from_env(cls):
        world = load_world()
        return cls.build(world.snapshot, epoch=world.epoch, mode="fake",
                         token=os.environ.get("LEDGERWORLD_DEMO_TOKEN") or None)

    monkeypatch.setattr(Services, "from_env", classmethod(from_env))
