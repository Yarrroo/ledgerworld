"""Legacy resource IDs cannot escape storage or allocate files during reads."""

import json
import uuid

import pytest
from app import create_app
from app.models.project import ProjectManager
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager


@pytest.fixture
def client(legacy_storage, monkeypatch, offline_legacy_services):
    token = uuid.uuid4().hex
    monkeypatch.setenv("LEDGERWORLD_DEMO_TOKEN", token)
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = "Bearer " + token
    return client


@pytest.mark.parametrize("value", ["..", "../outside", "/tmp/outside", "a/b", "a\\b",
                                    "", "a.b", "a" * 65, "é", "id\n", None, 12, [], {}])
@pytest.mark.parametrize(("path", "field"), [
    ("/api/graph/build", "project_id"),
    ("/api/simulation/create", "project_id"),
    ("/api/simulation/prepare", "simulation_id"),
    ("/api/report/generate", "simulation_id"),
])
def test_invalid_body_ids_are_rejected_before_dispatch(client, path, field, value):
    rule = next(rule for rule in client.application.url_map.iter_rules() if rule.rule == path)
    client.application.view_functions[rule.endpoint] = lambda: {"reached": True}
    response = client.post(path, json={field: value})
    assert response.status_code == 400
    assert "traceback" not in response.json


@pytest.mark.parametrize("path", [
    "/api/graph/project/..", "/api/simulation/../config", "/api/report/../progress",
    "/api/simulation/a%5Cb", "/api/report/" + "a" * 65,
])
def test_invalid_url_ids_are_rejected(client, path):
    assert client.get(path).status_code == 400


def test_invalid_query_and_duplicate_ids_are_rejected(client):
    assert client.get("/api/simulation/list", query_string={"project_id": "../x"}).status_code == 400
    assert client.get("/api/report/list", query_string=[
        ("simulation_id", "valid"), ("simulation_id", "../x")]).status_code == 400


def test_unknown_simulation_never_creates_its_directory(client, legacy_storage):
    root = legacy_storage["simulation_id"]
    assert client.get("/api/simulation/missing").status_code == 404
    assert not root.exists()


def test_all_resource_routes_return_404_for_unknown_ids(client):
    count = 0
    for rule in client.application.url_map.iter_rules():
        if not rule.arguments.intersection({"project_id", "simulation_id", "report_id"}):
            continue
        if not rule.rule.startswith(("/api/graph/", "/api/simulation/", "/api/report/")):
            continue
        path = rule.build({key: 1 if key == "section_index" else "missing"
                           for key in rule.arguments})[1]
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert client.open(path, method=method).status_code == 404, (path, method)
            count += 1
    assert count > 20


@pytest.mark.parametrize(("path", "field"), [
    ("/api/graph/build", "project_id"),
    ("/api/simulation/start", "simulation_id"),
    ("/api/report/generate", "simulation_id"),
])
def test_unknown_body_ids_return_404(client, path, field):
    assert client.post(path, json={field: "missing"}).status_code == 404


def test_empty_storage_reads_do_not_mkdir(client, legacy_storage):
    assert ProjectManager.list_projects() == []
    manager = SimulationManager()
    assert manager.get_simulation("missing") is None
    assert manager.get_simulation_config("missing") is None
    assert ReportManager.list_reports() == []
    assert ReportManager.get_report_by_simulation("missing") is None
    for path in ("/api/graph/project/list", "/api/simulation/list", "/api/simulation/history",
                 "/api/report/list"):
        assert client.get(path).status_code == 200
    assert not any(root.exists() for root in legacy_storage.values())


def test_manager_paths_reject_traversal(legacy_storage):
    with pytest.raises(ValueError):
        ProjectManager._get_project_dir("../outside")
    with pytest.raises(ValueError):
        SimulationManager()._get_simulation_dir("../outside")
    with pytest.raises(ValueError):
        ReportManager._get_report_folder("../outside")


def test_valid_creation_still_persists_and_can_be_read(client, legacy_storage):
    project = ProjectManager.create_project()
    assert ProjectManager.get_project(project.project_id) == project
    manager = SimulationManager()
    state = manager.create_simulation(project.project_id, "graph_existing")
    assert SimulationManager().get_simulation(state.simulation_id).project_id == project.project_id
    assert client.get("/api/graph/project/" + project.project_id).status_code == 200
    assert client.get("/api/simulation/" + state.simulation_id).status_code == 200


def test_platform_cannot_escape_database_directory(client, legacy_storage):
    project = ProjectManager.create_project()
    state = SimulationManager().create_simulation(project.project_id, "graph_existing")
    for suffix in ("posts", "comments"):
        response = client.get(f"/api/simulation/{state.simulation_id}/{suffix}",
                              query_string={"platform": "../../outside"})
        assert response.status_code == 400


def test_symlink_resource_cannot_escape_root(client, legacy_storage, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "state.json").write_text(json.dumps({"simulation_id": "linked"}))
    root = legacy_storage["simulation_id"]
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    assert client.get("/api/simulation/linked").status_code == 400
    assert (outside / "state.json").exists()


@pytest.mark.parametrize("resource_id", ["a", "A_9-z", "x" * 64])
def test_allowed_id_boundaries_reach_existing_resources(client, legacy_storage, resource_id):
    folder = legacy_storage["report_id"] / resource_id
    folder.mkdir(parents=True)
    (folder / "progress.json").write_text('{"status":"generating"}')
    assert client.get(f"/api/report/{resource_id}/progress").status_code == 200


@pytest.mark.parametrize(("field", "path"), [
    ("project_id", "/api/graph/project/list"),
    ("simulation_id", "/api/simulation/list"),
    ("report_id", "/api/report/list"),
])
def test_lists_skip_non_resource_entries(client, legacy_storage, field, path):
    root = legacy_storage[field]
    root.mkdir()
    (root / ".DS_Store").write_text("metadata")
    (root / "bad.name").mkdir()
    assert client.get(path).status_code == 200


def test_cyclic_symlink_is_a_controlled_refusal(client, legacy_storage):
    root = legacy_storage["simulation_id"]
    root.mkdir()
    (root / "loop").symlink_to("loop")
    assert client.get("/api/simulation/loop").status_code == 400


@pytest.mark.parametrize("field", ["project_id", "simulation_id", "report_id"])
def test_nested_resource_file_cannot_escape_root(client, legacy_storage, tmp_path, field):
    project = ProjectManager.create_project()
    if field == "project_id":
        resource_id, filename = project.project_id, "project.json"
        path = f"/api/graph/project/{resource_id}"
    elif field == "simulation_id":
        state = SimulationManager().create_simulation(project.project_id, "graph_existing")
        resource_id, filename = state.simulation_id, "state.json"
        path = f"/api/simulation/{resource_id}"
    else:
        resource_id, filename = "report_existing", "progress.json"
        path = f"/api/report/{resource_id}/progress"
    folder = legacy_storage[field] / resource_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    outside = tmp_path / "outside.json"
    outside.write_text(target.read_text() if target.exists() else '{"status":"outside"}')
    if target.exists():
        target.unlink()
    target.symlink_to(outside)
    assert client.get(path).status_code == 400

