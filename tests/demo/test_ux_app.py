"""The UX-check app's environment: fake provider, its own SQLite file, and nobody else's queue."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ux_app():
    spec = importlib.util.spec_from_file_location("ux_app", ROOT / "scripts" / "ux_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_env_drops_inherited_queue_and_credentials(tmp_path, monkeypatch):
    for name, value in {"REDIS_URL": "redis://shared.example:6379/0", "AIRWALLEX_API_KEY": "x",
                        "AIRWALLEX_MODE": "sandbox", "LLM_API_KEY": "x", "ZEP_API_KEY": "x",
                        "LEDGERWORLD_DEMO_TOKEN": "x"}.items():
        monkeypatch.setenv(name, value)
    # recorded, so the values offline_env writes are undone after this test
    for name in ("LEDGER_DATABASE_URL", "PYTHON_DOTENV_DISABLED"):
        monkeypatch.delenv(name, raising=False)
    url = _ux_app().offline_env(tmp_path)
    assert url == f"sqlite:///{tmp_path / 'app.sqlite'}"
    assert os.environ["LEDGER_DATABASE_URL"] == url
    assert os.environ["AIRWALLEX_MODE"] == "fake"
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    for name in ("REDIS_URL", "AIRWALLEX_API_KEY", "LLM_API_KEY", "ZEP_API_KEY", "LEDGERWORLD_DEMO_TOKEN"):
        assert name not in os.environ, name


def test_the_queue_is_always_in_process():
    source = (ROOT / "scripts" / "ux_app.py").read_text(encoding="utf-8")
    assert "fakeredis.FakeRedis()" in source
    assert "Redis.from_url" not in source
