"""Keep legacy API tests independent of deployed provider and datastore settings."""

import os

import pytest
from app.api.v1.services import Services
from app.simulation.scenarios import load_world


@pytest.fixture(autouse=True)
def offline_legacy_services(monkeypatch):
    def from_env(cls):
        world = load_world()
        return cls.build(world.snapshot, epoch=world.epoch, mode="fake",
                         token=os.environ.get("LEDGERWORLD_DEMO_TOKEN") or None)

    monkeypatch.setattr(Services, "from_env", classmethod(from_env))


@pytest.fixture
def legacy_storage(tmp_path, monkeypatch):
    from app.config import Config
    from app.models.project import ProjectManager
    from app.services.report_agent import ReportManager
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner

    roots = {"project_id": tmp_path / "projects",
             "simulation_id": tmp_path / "simulations",
             "report_id": tmp_path / "reports"}
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(roots["project_id"]))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(roots["simulation_id"]))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(roots["simulation_id"]))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(roots["simulation_id"]))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(roots["report_id"]))
    return roots
