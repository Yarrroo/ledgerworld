"""Static import fence: simulation-side code never reaches the Airwallex client.

An AST scan of every module the simulation role runs. It fails on any import of
`app.connectors.airwallex` (absolute, relative, `from app.connectors import airwallex`, a module
path held in a string for `importlib`, `__import__` or `mock.patch`, or a chain of in-repo
imports that ends there) and on any `AIRWALLEX_*` name (an environment read, a config
attribute, a key prefix). This is the static half of the credential-isolation check; the
runtime half checks the simulation worker's environment.
"""

from __future__ import annotations

import ast
import re
from collections import deque
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Every tree whose code runs inside a simulation process. A tree that does not exist yet is
# fenced from its first file on.
SIM_TREES = (
    "backend/app/simulation",
    "backend/app/testing",
    "packages/oasis-finance",
)
# Where in-repo modules resolve from: `app.*` and `oasis_finance.*`.
SOURCE_ROOTS = ("backend", "packages/oasis-finance/src")

CLIENT_PATH = re.compile(r"(^|\.)connectors\.airwallex(\.|$)")
CREDENTIAL_NAME = re.compile(r"^AIRWALLEX")


def docstring_nodes(tree: ast.Module) -> set[int]:
    owners = [tree] + [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    found = set()
    for owner in owners:
        body = owner.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            found.add(id(body[0].value))
    return found


def violations(path: Path, source: str) -> list[str]:
    """Return `path:line: reason` for every way this module itself names the client."""
    tree = ast.parse(source, filename=str(path))
    docstrings = docstring_nodes(tree)
    found = []

    def flag(node: ast.AST, reason: str) -> None:
        found.append(f"{path}:{node.lineno}: {reason}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if CLIENT_PATH.search(alias.name):
                    flag(node, f"imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = f"{module}.{alias.name}" if module else alias.name
                if CLIENT_PATH.search(module) or CLIENT_PATH.search(name):
                    flag(node, f"imports {'.' * node.level}{name}")
        elif isinstance(node, ast.Attribute):
            if node.attr == "airwallex":
                flag(node, "reaches the airwallex connector package as an attribute")
            elif CREDENTIAL_NAME.match(node.attr):
                flag(node, f"reads {node.attr}")
        elif isinstance(node, ast.Name) and CREDENTIAL_NAME.match(node.id):
            flag(node, f"reads {node.id}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            if CLIENT_PATH.search(node.value):
                flag(node, f"names the client module in a string: {node.value!r}")
            elif CREDENTIAL_NAME.match(node.value):
                flag(node, f"names a credential variable: {node.value!r}")
    return found


def py_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if ".venv" not in p.parts)


def module_index(root: Path) -> dict[str, Path]:
    """Dotted module name -> file, for every in-repo module a simulation process can import."""
    index = {}
    for src in SOURCE_ROOTS:
        for path in py_files(root / src):
            parts = path.relative_to(root / src).with_suffix("").parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                index[".".join(parts)] = path
    return index


def imported_names(path: Path, module: str) -> list[tuple[int, str]]:
    """(line, absolute dotted name) for every import statement in the file."""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*anchor, base] if base else anchor)
            found.append((node.lineno, base))
            found += [(node.lineno, f"{base}.{alias.name}") for alias in node.names]
    return found


def with_parents(name: str) -> list[str]:
    """Importing `a.b.c` runs `a`, `a.b` and `a.b.c`."""
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def reach_hits(root: Path, path: Path, index: dict[str, Path]) -> list[str]:
    """Chains of in-repo imports from a simulation module that end in the client."""
    names = {file: name for name, file in index.items()}
    start = names.get(path)
    if start is None:
        return []
    found = []
    seen = {start}
    queue = deque((line, [name]) for line, name in imported_names(path, start))
    while queue:
        line, chain = queue.popleft()
        for name in with_parents(chain[-1]):
            if CLIENT_PATH.search(name):
                if len(chain) > 1:  # a direct import is already flagged by `violations`
                    via = " -> ".join(chain[:-1])
                    found.append(f"{path.relative_to(root)}:{line}: reaches {name} via {via}")
                break
            if name in index and name not in seen:
                seen.add(name)
                queue += [
                    (line, [*chain[:-1], name, child])
                    for _, child in imported_names(index[name], name)
                ]
    return list(dict.fromkeys(found))


def sim_modules(root: Path) -> list[Path]:
    return [path for tree in SIM_TREES for path in py_files(root / tree)]


def scan(root: Path) -> list[str]:
    index = module_index(root)
    hits = []
    for path in sim_modules(root):
        hits += violations(path.relative_to(root), path.read_text(encoding="utf-8"))
        hits += reach_hits(root, path, index)
    return hits


def plant(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def test_simulation_side_never_reaches_airwallex():
    assert sim_modules(ROOT), "no simulation-side module found; the fence scans nothing"
    hits = scan(ROOT)
    assert not hits, "simulation code reaches the Airwallex client:\n" + "\n".join(hits)


def test_fence_catches_a_planted_live_import(tmp_path):
    rel = "backend/app/simulation/planted.py"
    plant(tmp_path, rel, '"""A sim module."""\n\nimport app.connectors.airwallex.live\n')
    assert scan(tmp_path) == [f"{rel}:3: imports app.connectors.airwallex.live"]


@pytest.mark.parametrize(
    "source",
    [
        "from app.connectors.airwallex import live\n",
        "from app.connectors.airwallex.live import LiveTransport\n",
        "from app.connectors import airwallex\n",
        "from ..connectors.airwallex import live\n",
        "from ..connectors import airwallex\n",
        "import backend.app.connectors.airwallex.client as client\n",
        "import importlib\nimportlib.import_module('app.connectors.airwallex.live')\n",
        "__import__('app.connectors.airwallex.live')\n",
        "from unittest import mock\nmock.patch('app.connectors.airwallex.live.login')\n",
        "from .. import connectors\nconnectors.airwallex.live\n",
    ],
)
def test_fence_catches_every_import_form(tmp_path, source):
    plant(tmp_path, "backend/app/testing/planted.py", source)
    hits = scan(tmp_path)
    assert hits and all(h.startswith("backend/app/testing/planted.py:") for h in hits), hits


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.environ['AIRWALLEX_API_KEY']\n",
        "import os\nos.environ.get('AIRWALLEX_CLIENT_ID')\n",
        "import os\nos.getenv('AIRWALLEX_MODE', 'fake')\n",
        "from os import environ\nenviron.pop('AIRWALLEX_WEBHOOK_SECRET')\n",
        "import os\n[k for k in os.environ if k.startswith('AIRWALLEX_')]\n",
        "import os\nos.environ[f'AIRWALLEX_{name}']\n",
        "from app.config import Config\nConfig.AIRWALLEX_API_KEY\n",
    ],
)
def test_fence_catches_every_credential_read(tmp_path, source):
    plant(tmp_path, "packages/oasis-finance/src/oasis_finance/planted.py", source)
    hits = scan(tmp_path)
    assert hits and all("AIRWALLEX" in h for h in hits), hits


@pytest.mark.parametrize(
    "source",
    [
        "from app.execution import gateway\n",
        "from ..execution.gateway import submit\n",
        "import app.execution.gateway\n",
    ],
)
def test_fence_catches_a_chain_through_another_module(tmp_path, source):
    plant(tmp_path, "backend/app/__init__.py", "")
    plant(tmp_path, "backend/app/execution/__init__.py", "")
    plant(tmp_path, "backend/app/execution/gateway.py", (
        "from ..connectors.airwallex import client\n\ndef submit():\n    return client\n"
    ))
    plant(tmp_path, "backend/app/simulation/__init__.py", "")
    plant(tmp_path, "backend/app/simulation/indirect.py", source)
    chain = "reaches app.connectors.airwallex via app.execution.gateway"
    assert scan(tmp_path) == [f"backend/app/simulation/indirect.py:1: {chain}"]


def test_fence_passes_clean_simulation_code(tmp_path):
    plant(tmp_path, "backend/app/finance/ledger.py", "import decimal\n")
    plant(tmp_path, "backend/app/simulation/clean.py", (
        '"""Never imports app.connectors.airwallex.live; AIRWALLEX_* stays out of reach."""\n'
        "import os\n"
        "from app.finance import ledger\n"
        "from ..execution import approval\n\n"
        "def model_name():\n"
        '    """Reads LLM_MODEL_NAME, never AIRWALLEX_MODE."""\n'
        "    return os.getenv('LLM_MODEL_NAME'), ledger, approval, 'Airwallex sandbox'\n"
    ))
    assert sim_modules(tmp_path)
    assert scan(tmp_path) == []
