"""Security 3: an upstream route's error answer carries the message, never a traceback.

The traceback is logged on the server; a client sees `{"success": false, "error": "<message>"}`.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from app import create_app
from app.api import graph as graph_api
from app.models.task import TaskManager
from app.services.graph_builder import GraphBuilderService
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager

APP = Path(__file__).resolve().parents[1] / "app"
# Every upstream module that formats a traceback for a route or a task a route reads back.
MODULES = ["api/graph.py", "api/simulation.py", "api/report.py", "services/graph_builder.py"]
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def boom(*_args, **_kwargs):
    raise RuntimeError("boom")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    return create_app().test_client()


def assert_no_traceback(resp):
    body = resp.get_data(as_text=True)
    assert "Traceback" not in body
    assert "traceback" not in body
    assert 'File "' not in body


@pytest.mark.parametrize(
    "target, attr, method, path",
    [
        (SimulationManager, "get_simulation", "get", "/api/simulation/sim_1"),
        (SimulationManager, "list_simulations", "get", "/api/simulation/list"),
        (SimulationManager, "get_simulation_config", "get", "/api/simulation/sim_1/config"),
        (ReportManager, "get_report", "get", "/api/report/report_1"),
        (ReportManager, "list_reports", "get", "/api/report/list"),
        (ReportManager, "get_progress", "get", "/api/report/report_1/progress"),
    ],
)
def test_a_500_answer_carries_the_message_not_the_traceback(
    client, monkeypatch, caplog, target, attr, method, path
):
    monkeypatch.setattr(target, attr, boom)
    # the app's loggers do not propagate to the root logger: listen on each of them
    app_loggers = [
        logging.getLogger(name) for name in list(logging.root.manager.loggerDict)
        if name.startswith("mirofish")
    ]
    for app_logger in app_loggers:
        app_logger.addHandler(caplog.handler)
    try:
        resp = getattr(client, method)(path)
    finally:
        for app_logger in app_loggers:
            app_logger.removeHandler(caplog.handler)
    assert resp.status_code == 500
    assert resp.get_json() == {"success": False, "error": "boom"}
    assert_no_traceback(resp)
    assert any("Traceback" in r.getMessage() for r in caplog.records)  # logged server-side


def test_the_graph_data_500_carries_no_traceback(client, monkeypatch):
    monkeypatch.setattr(graph_api.Config, "ZEP_API_KEY", "test-key")
    monkeypatch.setattr(GraphBuilderService, "__init__", lambda self, api_key=None: None)
    monkeypatch.setattr(GraphBuilderService, "get_graph_data", boom)
    resp = client.get("/api/graph/data/g_1")
    assert resp.status_code == 500
    assert resp.get_json() == {"success": False, "error": "boom"}


def test_a_failed_graph_build_task_reads_back_without_a_traceback(client, monkeypatch):
    builder = GraphBuilderService.__new__(GraphBuilderService)
    builder.task_manager = TaskManager()
    task_id = builder.task_manager.create_task("graph_build")
    monkeypatch.setattr(builder, "validate_batch_chunks", lambda *a, **k: None)
    monkeypatch.setattr(builder, "create_graph", boom)
    builder._build_graph_worker(task_id, "text", {}, "g", 500, 50, 3)
    resp = client.get(f"/api/graph/task/{task_id}")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["error"] == "boom"
    assert_no_traceback(resp)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


@pytest.mark.parametrize("module", MODULES)
def test_a_formatted_traceback_only_ever_goes_to_a_logger(module):
    tree = ast.parse((APP / module).read_text(encoding="utf-8"))
    parents = _parents(tree)
    leaks = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "traceback":
                    leaks.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"format_exc", "format_exception"}
        ):
            parent = parents[node]
            to_logger = (
                isinstance(parent, ast.Call)
                and isinstance(parent.func, ast.Attribute)
                and parent.func.attr in LOG_METHODS
            )
            if not to_logger:
                leaks.append(node.lineno)
    assert leaks == [], f"{module}: a traceback can reach a response at lines {leaks}"
