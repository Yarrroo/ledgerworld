"""Security 2: the upstream routes accept only well-formed ids, and a read never creates a directory."""

from __future__ import annotations

import pytest
from app import create_app
from app.api.v1.legacy_ids import valid_id
from app.models.project import ProjectManager
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner


@pytest.fixture
def sims(tmp_path, monkeypatch):
    root = tmp_path / "simulations"
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(root))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    return root


@pytest.fixture
def client(sims, monkeypatch, offline_legacy_services):
    import uuid

    token = uuid.uuid4().hex
    monkeypatch.setenv("LEDGERWORLD_DEMO_TOKEN", token)
    client = create_app().test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer " + token
    return client


@pytest.mark.parametrize(
    "value", ["sim_0123abcd", "proj-1", "a", "A" * 64, "3f2b-11ee_X"]
)
def test_well_formed_ids_pass(value):
    assert valid_id(value)


def test_an_int_is_an_id_only_where_it_is_an_agent_index():
    assert valid_id(7, "agent_id")
    assert not valid_id(7, "simulation_id")
    assert not valid_id(True, "agent_id")


@pytest.mark.parametrize(
    "value", ["", "A" * 65, "../etc", "a/b", "a.b", "..", "a b", "x\n", None, True, ["a"]]
)
def test_malformed_ids_fail(value):
    assert not valid_id(value)


@pytest.mark.parametrize(
    "path",
    [
        "/api/simulation/" + "a" * 65,
        "/api/simulation/a.b/config",
        "/api/report/..",
        "/api/report/x%2e%2e/progress",
        "/api/graph/project/a%20b",
        "/api/graph/data/a.b",
    ],
)
def test_a_malformed_url_id_answers_404(client, path):
    resp = client.get(path)
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/simulation/prepare", {"simulation_id": "../../uploads/projects"}),
        ("/api/simulation/start", {"simulation_id": "../x", "platform": "parallel"}),
        ("/api/simulation/create", {"project_id": "a/b"}),
        ("/api/simulation/interview/history", {"simulation_id": "a.b"}),
        ("/api/report/generate", {"simulation_id": "../../etc"}),
        ("/api/report/chat", {"simulation_id": "..", "message": "hi"}),
        ("/api/graph/build", {"project_id": {"nested": 1}}),
        ("/api/simulation/start", {"simulation_id": 5}),
    ],
)
def test_a_malformed_body_id_answers_400(client, sims, path, body):
    resp = client.post(path, json=body)
    assert resp.status_code == 400
    assert resp.get_json() == {"success": False, "error": f"invalid {next(iter(body))}"}
    assert not sims.exists()


def test_a_malformed_query_or_form_id_answers_400(client):
    assert client.get("/api/simulation/list?project_id=../x").status_code == 400
    assert client.get("/api/report/list?simulation_id=a/b").status_code == 400
    resp = client.post("/api/graph/ontology/generate", data={"project_id": "../x"})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "suffix", ["", "/config", "/config/download", "/profiles", "/run-status"]
)
def test_a_read_of_an_unknown_simulation_answers_404_and_creates_nothing(client, sims, suffix):
    resp = client.get(f"/api/simulation/sim_doesnotexist{suffix}")
    assert resp.status_code in (200, 404)
    if suffix != "/run-status":  # run-status reports an idle run for an id it has never seen
        assert resp.status_code == 404
    assert not (sims / "sim_doesnotexist").exists()


def test_a_known_simulation_still_reads(client, sims):
    state = SimulationManager().create_simulation(project_id="proj_1", graph_id="g_1")
    resp = client.get(f"/api/simulation/{state.simulation_id}")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["simulation_id"] == state.simulation_id


def test_v1_routes_are_not_touched(client):
    assert client.get("/api/v1/health").status_code == 200
