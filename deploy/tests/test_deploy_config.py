"""The container, compose and host config, read without Docker (the build box has none).

The Dockerfile and compose parse and point at files that exist; every variable they, the
entrypoint and the host config name is in `.env.example`; the simulation role's environment holds
no `AIRWALLEX_*` name, both as compose writes it and as the entrypoint hands it to the process.
"""

from __future__ import annotations

import json
import re
import runpy
import shlex
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
ENTRYPOINT = DEPLOY / "entrypoint.sh"
INSTRUCTIONS = {
    "FROM", "RUN", "CMD", "LABEL", "EXPOSE", "ENV", "ADD", "COPY", "ENTRYPOINT", "VOLUME",
    "USER", "WORKDIR", "ARG", "ONBUILD", "STOPSIGNAL", "HEALTHCHECK", "SHELL",
}
# Names the image sets for its own toolchain; none is application configuration.
TOOLCHAIN_ENV = {
    "PATH", "PYTHONUNBUFFERED", "UV_COMPILE_BYTECODE", "UV_LINK_MODE", "UV_PYTHON_DOWNLOADS",
    "VITE_API_BASE_URL",
}
SERVICE_IMAGES = {"postgres": "postgres:16", "redis": "redis:7"}
INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")
SHELL_NAME = re.compile(r"\$\{?([A-Z][A-Z0-9_]*)")


def env_example() -> set[str]:
    names = set()
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, sep, value = line.partition("=")
            assert sep and not value, f".env.example carries a value for {name}"
            names.add(name)
    return names


def dockerfile() -> list[tuple[str, str]]:
    """(instruction, arguments) per instruction, continuation lines joined."""
    joined, pending = [], ""
    for line in (DEPLOY / "Dockerfile").read_text().splitlines():
        if not pending and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        joined.append(pending + line)
        pending = ""
    assert not pending, "the Dockerfile ends inside a continuation"
    out = []
    for line in joined:
        word, _, rest = line.strip().partition(" ")
        out.append((word.upper(), rest.strip()))
    return out


def stages() -> dict[str, list[tuple[str, str]]]:
    """Each build stage's instructions by its name; every stage is named."""
    named: dict[str, list[tuple[str, str]]] = {}
    current = None
    for word, rest in dockerfile():
        if word == "FROM":
            parts = rest.split()
            assert len(parts) >= 3 and parts[-2].upper() == "AS", f"FROM {rest} names no stage"
            current = parts[-1]
            named[current] = []
        assert current is not None, "the Dockerfile has an instruction before its first FROM"
        named[current].append((word, rest))
    return named


def copies() -> list[tuple[set[str], list[str]]]:
    """(flags, sources) of every COPY from the build context."""
    out = []
    for word, rest in dockerfile():
        if word == "COPY" and not rest.startswith("--from"):
            words = shlex.split(rest)[:-1]
            out.append(({w for w in words if w.startswith("--")},
                        [w.rstrip("/") for w in words if not w.startswith("--")]))
    return out


def copy_sources() -> set[str]:
    """Every path the Dockerfile copies from the build context."""
    return {source for _, sources in copies() for source in sources}


def compose() -> dict:
    return yaml.safe_load((DEPLOY / "compose.yml").read_text())


def environment(service: dict) -> dict[str, str | None]:
    """A service's environment as name → value (None: passed through from the host)."""
    env = service.get("environment") or {}
    assert isinstance(env, dict), "compose writes each environment as a map"
    return {k: (None if v is None else str(v)) for k, v in env.items()}


def secret_names() -> set[str]:
    """The .env.example names whose value is a credential."""
    names = {n for n in env_example() if n.endswith(("_KEY", "_SECRET", "_TOKEN"))}
    return names | {"AIRWALLEX_CLIENT_ID"}


def our_services() -> dict[str, dict]:
    return {name: s for name, s in compose()["services"].items()
            if (s.get("build") or {}).get("dockerfile") == "deploy/Dockerfile"}


def host() -> dict:
    return tomllib.loads((DEPLOY / "host.toml").read_text())


def run_entrypoint(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(ENTRYPOINT), *args], env={"PATH": "/usr/bin:/bin", **env},
                          capture_output=True, text=True, timeout=30, check=False)


def entrypoint_env(env: dict[str, str]) -> dict[str, str]:
    """The environment the entrypoint hands its process, given ``env``."""
    result = run_entrypoint(env, "env")
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


# ---------------------------------------------------------------------------------- Dockerfile

def test_the_dockerfile_parses_into_known_instructions():
    instructions = dockerfile()
    assert instructions and instructions[0][0] == "FROM"
    unknown = [word for word, _ in instructions if word not in INSTRUCTIONS]
    assert not unknown


def test_the_image_is_python_312_slim_with_the_built_frontend():
    named = stages()
    final = named["app"]
    assert list(named)[-1] == "app"
    assert final[0] == ("FROM", "python:3.12-slim AS app")
    assert "frontend" in named
    assert any(w == "RUN" and "run build" in r for w, r in named["frontend"])
    assert ("COPY", "--from=frontend /src/frontend/dist ./frontend/dist") in final
    assert any(w == "RUN" and "uv sync --frozen --no-dev" in r for w, r in final)


def test_every_copied_path_exists_in_the_repo():
    assert not [s for s in copy_sources() if not (ROOT / s).exists()]


def test_the_image_copies_sources_not_a_checkout_s_run_time_output():
    """backend/ also holds a checkout's logs, uploads and job dirs; only its code is copied."""
    copied = copy_sources()
    assert "backend" not in copied
    assert {"backend/app", "backend/scripts"} <= copied


DOTENV = "." + "env"
CODE_COPY_EXCLUDES = {f"--exclude=**/{DOTENV}", "--exclude=**/__pycache__"}


def test_no_code_copy_brings_a_nested_dotenv_file_or_host_bytecode():
    """The root .dockerignore matches its dotenv and __pycache__ entries at the context root
    only, so every copy of a code tree excludes them itself."""
    for flags, sources in copies():
        if any((ROOT / s).is_dir() and any((ROOT / s).rglob("*.py")) for s in sources):
            assert CODE_COPY_EXCLUDES <= flags, sources


def test_the_image_prepares_every_directory_the_process_writes_for_its_user():
    """The process runs as a non-root user from backend/, which root owns. The upstream social
    platform makes ./log in the working directory at import time, so backend/log is created and
    handed to that user beside the app's own logs, uploads and var, or the app crash-loops."""
    final = stages()["app"]
    user = next(r for w, r in final if w == "USER")
    workdir = [r for w, r in final if w == "WORKDIR"][-1]
    assert workdir == "/app/backend"
    runs = [r for w, r in final if w == "RUN" and "useradd" in r]
    assert len(runs) == 1
    steps = [shlex.split(step) for step in runs[0].split("&&")]
    made = {d for s in steps if s[:2] == ["mkdir", "-p"] for d in s[2:]}
    owned = {d for s in steps if s[:1] == ["chown"] and user in s for d in s
             if d.startswith("backend/")}
    for directory in ("backend/log", "backend/logs", "backend/uploads", "backend/var"):
        assert directory in made and directory in owned, directory


def test_the_entrypoint_is_the_role_switch():
    final = stages()["app"]
    entry = [json.loads(r) for w, r in final if w == "ENTRYPOINT"]
    assert entry == [["bash", "/app/deploy/entrypoint.sh"]]
    assert ("EXPOSE", str(host()["host"]["internal_port"])) in final
    assert ("ENV", "LEDGERWORLD_ROLE=api") in final


def test_the_dockerfile_sets_no_application_value_beyond_the_role():
    """A build argument is a name the build is given, never a value it carries itself."""
    names, args = set(), set()
    for word, rest in dockerfile():
        if word == "ENV":
            names |= {pair.split("=", 1)[0] for pair in shlex.split(rest)}
        if word == "ARG":
            assert "=" not in rest, f"ARG {rest} carries a default value"
            args |= set(rest.split())
    assert names - TOOLCHAIN_ENV == {"LEDGERWORLD_ROLE"}
    assert (names - TOOLCHAIN_ENV) | args <= env_example()


# --------------------------------------------------------------------------- AGPL source link

SOURCE_ARG = "VITE_SOURCE_URL"


def run_source_guard(value: str | None) -> subprocess.CompletedProcess:
    """The frontend stage's check on the source link, run as the build's /bin/sh runs it."""
    runs = [r for w, r in stages()["frontend"] if w == "RUN" and SOURCE_ARG in r]
    assert len(runs) == 1, "the frontend stage checks the source link in exactly one RUN"
    env = {"PATH": "/usr/bin:/bin"} | ({} if value is None else {SOURCE_ARG: value})
    return subprocess.run(["sh", "-c", runs[0]], env=env, capture_output=True, text=True,
                          timeout=30, check=False)


def test_the_frontend_build_takes_the_source_link_as_a_build_argument():
    """Every page footer links the source (AGPL-3.0 §13, system brief §3); the shell renders that
    link only when the bundle was built with VITE_SOURCE_URL, so the image declares it, checks it
    and builds after the check."""
    frontend = stages()["frontend"]
    assert ("ARG", SOURCE_ARG) in frontend
    order = [r for w, r in frontend if w in ("ARG", "RUN")]
    arg = order.index(SOURCE_ARG)
    guard = next(i for i, r in enumerate(order) if SOURCE_ARG in r and i != arg)
    build = next(i for i, r in enumerate(order) if "run build" in r)
    assert arg < guard < build


@pytest.mark.parametrize("value", [None, "", " ", "github.com/x/y", "javascript:alert(1)",
                                   "https://", "ftp://example.org/src", "https:// ",
                                   "https:///src", "https://example.org/src ",
                                   'https://example.org/src"', "https://example.org/<src>",
                                   "https://example.org/a b"])
def test_an_image_without_a_source_link_is_not_built(value):
    result = run_source_guard(value)
    assert result.returncode != 0
    assert SOURCE_ARG in result.stderr


@pytest.mark.parametrize("value", ["https://example.org/ledgerworld", "http://git.example:8080/lw"])
def test_an_image_with_a_source_link_builds(value):
    assert run_source_guard(value).returncode == 0


def test_the_documented_build_line_passes_the_source_link():
    lines = [line for line in (DEPLOY / "Dockerfile").read_text().splitlines()
             if line.startswith("#") and "docker build" in line]
    assert lines and all(f"--build-arg {SOURCE_ARG}=" in line for line in lines)


def test_compose_passes_the_source_link_to_every_build_of_the_image():
    for name, service in our_services().items():
        args = service["build"].get("args") or {}
        assert args.get(SOURCE_ARG) == "${VITE_SOURCE_URL:-}", name
    assert SOURCE_ARG in host()["build"]["required"]


# ------------------------------------------------------------------------------------- compose

def test_compose_runs_the_app_the_worker_postgres_and_redis():
    services = compose()["services"]
    assert set(services) == {"app", "sim", "postgres", "redis"}
    for name, image in SERVICE_IMAGES.items():
        assert services[name]["image"] == image
    for service in our_services().values():
        assert (DEPLOY / service["build"]["context"]).resolve() == ROOT
    assert set(our_services()) == {"app", "sim"}


def test_every_name_compose_reads_is_in_env_example():
    names = set(INTERPOLATION.findall((DEPLOY / "compose.yml").read_text()))
    for service in our_services().values():
        names |= set(environment(service))
    assert names - env_example() == set()


def test_no_value_in_compose_is_a_credential():
    """A credential is passed through by name, never written with a value."""
    for service in our_services().values():
        env = environment(service)
        assert all(env[name] is None for name in secret_names() & set(env))


def test_the_sim_role_environment_has_no_airwallex_name():
    services = compose()["services"]
    sims = [s for s in services.values() if environment(s).get("LEDGERWORLD_ROLE") == "sim"]
    assert sims
    for service in sims:
        assert "env_file" not in service
        assert not [n for n in environment(service) if n.upper().startswith("AIRWALLEX_")]


def test_the_sim_role_holds_no_credential_at_all():
    """The job worker builds no model client, so it is given no key of any provider."""
    for service in compose()["services"].values():
        env = environment(service)
        if env.get("LEDGERWORLD_ROLE") == "sim":
            assert not secret_names() & set(env)


def test_the_app_is_published_only_on_loopback_and_checks_the_v1_health():
    app = compose()["services"]["app"]
    port = host()["host"]["internal_port"]
    assert app["ports"] == [f"127.0.0.1:{port}:{port}"]
    assert host()["host"]["health_path"] in " ".join(app["healthcheck"]["test"])


# ---------------------------------------------------------------------------------- entrypoint

def test_every_name_the_entrypoint_reads_is_in_env_example():
    names = set(SHELL_NAME.findall(ENTRYPOINT.read_text())) - {"BASH_SOURCE"}
    assert names and names <= env_example()


@pytest.mark.parametrize("role", ["sim", "worker"])
def test_the_sim_role_starts_with_every_airwallex_name_removed(role):
    planted = {name: "x" for name in env_example() if name.startswith("AIRWALLEX_")}
    planted["airwallex_lowercase"] = "x"
    seen = entrypoint_env({"LEDGERWORLD_ROLE": role, "REDIS_URL": "x", **planted})
    assert not [n for n in seen if n.upper().startswith("AIRWALLEX_")]
    assert seen["LEDGERWORLD_ROLE"] == "sim"
    assert seen["REDIS_URL"] == "x"


def test_no_role_reads_a_dotenv_file(tmp_path):
    """A stray .env in the image cannot put back what the sim role's scrub removed: the app
    loads .env with override on import, so every role runs with dotenv loading disabled."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("".join(f"{name}=x\n" for name in sorted(env_example())
                              if name.startswith("AIRWALLEX_")))
    probe = ("import os, sys, dotenv; dotenv.load_dotenv(sys.argv[1], override=True); "
             "print(sorted(n for n in os.environ if n.startswith('AIRWALLEX_')))")
    for role in ("sim", "api"):
        result = run_entrypoint({"LEDGERWORLD_ROLE": role}, sys.executable, "-c", probe,
                                str(dotenv))
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "[]"


def test_the_api_role_keeps_its_environment():
    planted = {name: "x" for name in ("AIRWALLEX_MODE", "AIRWALLEX_API_KEY")}
    seen = entrypoint_env({"LEDGERWORLD_ROLE": "api", **planted})
    assert {n: seen.get(n) for n in planted} == planted


@pytest.mark.parametrize("role", ["", "simulation", "API"])
def test_an_unknown_role_is_refused(role):
    result = run_entrypoint({"LEDGERWORLD_ROLE": role}, "env")
    assert result.returncode == 64
    assert "LEDGERWORLD_ROLE must be" in result.stderr and not result.stdout


@pytest.fixture
def served(tmp_path, monkeypatch):
    """The api role's server program, run as the entrypoint runs it, on a stub app and a built
    frontend of two files; the WSGI app it would serve is captured instead of listening."""
    import werkzeug.serving
    from flask import Flask
    from werkzeug.test import Client

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>index</html>")
    (dist / "assets" / "app.js").write_text("app()")
    stub = Flask("stub")
    stub.add_url_rule("/api/v1/health", "health", lambda: {"ok": True})
    monkeypatch.setitem(sys.modules, "app", types.SimpleNamespace(create_app=lambda: stub))
    captured = {}
    monkeypatch.setattr(werkzeug.serving, "run_simple",
                        lambda host, port, wsgi, **kw: captured.update(wsgi=wsgi, port=port))
    monkeypatch.setattr(sys, "argv", ["-", str(dist)])
    program = tmp_path / "serve.py"
    program.write_text(ENTRYPOINT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0])
    runpy.run_path(str(program), run_name="__main__")
    assert captured["port"] == host()["host"]["internal_port"]
    return Client(captured["wsgi"])


def test_the_api_serves_the_api_the_build_and_the_frontend_routes(served):
    assert served.get("/api/v1/health").json == {"ok": True}
    assert served.get("/assets/app.js").get_data(as_text=True) == "app()"
    for path in ("/", "/simulation/run-1"):
        page = served.get(path)
        assert page.status_code == 200 and page.get_data(as_text=True) == "<html>index</html>"
    assert served.head("/decisions").status_code == 200


def test_a_missing_file_or_a_write_is_not_answered_with_the_index(served):
    assert served.get("/assets/index-old.js").status_code == 404
    assert served.get("/favicon.ico").status_code == 404
    assert served.post("/simulation/run-1").status_code in (404, 405)
    assert served.get("/api/v1/nope").status_code == 404
    assert served.get("/api").status_code == 404


# --------------------------------------------------------------------------------- host config

def test_the_host_config_targets_this_compose_file():
    h = host()["host"]
    assert h["target"] == "compose"
    assert (ROOT / h["compose_file"]).resolve() == DEPLOY / "compose.yml"
    assert h["public_service"] in compose()["services"]
    assert h["health_path"] == "/api/v1/health"
    assert h["url_env"] in env_example()


def test_the_host_roles_match_compose():
    services = compose()["services"]
    roles = host()["roles"]
    assert set(roles) == set(our_services())
    for service, role in roles.items():
        assert environment(services[service])["LEDGERWORLD_ROLE"] == role


def test_every_name_the_host_config_sets_is_in_env_example():
    h = host()
    names = {n for group in h["secrets"].values() for n in group} | set(h["settings"])
    names |= set(h["build"]["required"])
    assert names <= env_example()
    assert h["settings"]["AIRWALLEX_MODE"] == "fake"


def test_the_airwallex_secrets_reach_only_the_api_role():
    services = compose()["services"]
    for name in host()["secrets"]["airwallex"]:
        holders = {s for s, svc in services.items() if name in environment(svc)}
        assert {environment(services[s])["LEDGERWORLD_ROLE"] for s in holders} == {"api"}
