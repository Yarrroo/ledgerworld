"""The container, compose and host config, read without Docker (the build box has none).

The Dockerfile and compose parse and point at files that exist; every variable they, the
entrypoint and the host config name is in `.env.example`; the simulation role's environment holds
no `AIRWALLEX_*` name, both as compose writes it and as the entrypoint hands it to the process.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import tomllib
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
    named: dict[str, list[tuple[str, str]]] = {}
    current = None
    for word, rest in dockerfile():
        if word == "FROM":
            parts = rest.split()
            current = parts[2] if len(parts) == 3 and parts[1].upper() == "AS" else str(len(named))
            named[current] = []
        assert current is not None, "the Dockerfile has an instruction before its first FROM"
        named[current].append((word, rest))
    return named


def compose() -> dict:
    return yaml.safe_load((DEPLOY / "compose.yml").read_text())


def environment(service: dict) -> dict[str, str | None]:
    """A service's environment as name → value (None: passed through from the host)."""
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {k: (None if v is None else str(v)) for k, v in env.items()}
    out: dict[str, str | None] = {}
    for item in env:
        name, sep, value = item.partition("=")
        out[name] = value if sep else None
    return out


def our_services() -> dict[str, dict]:
    return {name: s for name, s in compose()["services"].items()
            if (s.get("build") or {}).get("dockerfile") == "deploy/Dockerfile"}


def host() -> dict:
    return tomllib.loads((DEPLOY / "host.toml").read_text())


def run_entrypoint(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(ENTRYPOINT), *args], env={"PATH": "/usr/bin:/bin", **env},
                          capture_output=True, text=True, timeout=30, check=False)


# ---------------------------------------------------------------------------------- Dockerfile

def test_the_dockerfile_parses_into_known_instructions():
    instructions = dockerfile()
    assert instructions and instructions[0][0] == "FROM"
    unknown = [word for word, _ in instructions if word not in INSTRUCTIONS]
    assert not unknown


def test_the_image_is_python_312_slim_with_the_built_frontend():
    named = stages()
    final = list(named.values())[-1]
    assert final[0] == ("FROM", "python:3.12-slim AS app")
    assert "frontend" in named
    assert any(w == "RUN" and "run build" in r for w, r in named["frontend"])
    assert ("COPY", "--from=frontend /src/frontend/dist ./frontend/dist") in final
    assert any(w == "RUN" and "uv sync --frozen --no-dev" in r for w, r in final)


def test_every_copied_path_exists_in_the_repo():
    for word, rest in dockerfile():
        if word != "COPY" or rest.startswith("--from"):
            continue
        sources = shlex.split(rest)[:-1]
        missing = [s for s in sources if not (ROOT / s).exists()]
        assert not missing, f"COPY {rest}"


def test_the_entrypoint_is_the_role_switch():
    final = list(stages().values())[-1]
    entry = [json.loads(r) for w, r in final if w == "ENTRYPOINT"]
    assert entry == [["bash", "/app/deploy/entrypoint.sh"]]
    assert ("EXPOSE", str(host()["host"]["internal_port"])) in final
    assert ("ENV", "LEDGERWORLD_ROLE=api") in final


def test_the_dockerfile_sets_no_application_value_beyond_the_role():
    names = set()
    for word, rest in dockerfile():
        if word == "ENV":
            names |= {pair.split("=", 1)[0] for pair in shlex.split(rest)}
        if word == "ARG":
            names.add(rest.split("=", 1)[0])
    assert names - TOOLCHAIN_ENV == {"LEDGERWORLD_ROLE"}
    assert names - TOOLCHAIN_ENV <= env_example()


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
    secret_names = {n for n in env_example() if n.endswith(("_KEY", "_SECRET", "_TOKEN"))}
    secret_names.add("AIRWALLEX_CLIENT_ID")
    for service in our_services().values():
        env = environment(service)
        assert all(env[name] is None for name in secret_names & set(env))


def test_the_sim_role_environment_has_no_airwallex_name():
    services = compose()["services"]
    sims = [s for s in services.values() if environment(s).get("LEDGERWORLD_ROLE") == "sim"]
    assert sims
    for service in sims:
        assert "env_file" not in service
        assert not [n for n in environment(service) if n.upper().startswith("AIRWALLEX_")]


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
    result = run_entrypoint({"LEDGERWORLD_ROLE": role, "REDIS_URL": "x", **planted}, "env")
    assert result.returncode == 0, result.stderr
    seen = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    assert not [n for n in seen if n.upper().startswith("AIRWALLEX_")]
    assert seen["LEDGERWORLD_ROLE"] == "sim"
    assert seen["REDIS_URL"] == "x"


def test_the_api_role_keeps_its_environment():
    planted = {name: "x" for name in ("AIRWALLEX_MODE", "AIRWALLEX_API_KEY")}
    result = run_entrypoint({"LEDGERWORLD_ROLE": "api", **planted}, "env")
    assert result.returncode == 0, result.stderr
    seen = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    assert {n: seen.get(n) for n in planted} == planted


@pytest.mark.parametrize("role", ["", "simulation", "API"])
def test_an_unknown_role_is_refused(role):
    result = run_entrypoint({"LEDGERWORLD_ROLE": role}, "env")
    assert result.returncode == 64
    assert "LEDGERWORLD_ROLE must be" in result.stderr and not result.stdout


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
    assert names <= env_example()
    assert h["settings"]["AIRWALLEX_MODE"] == "fake"


def test_the_airwallex_secrets_reach_only_the_api_role():
    services = compose()["services"]
    for name in host()["secrets"]["airwallex"]:
        holders = {s for s, svc in services.items() if name in environment(svc)}
        assert {environment(services[s])["LEDGERWORLD_ROLE"] for s in holders} == {"api"}
