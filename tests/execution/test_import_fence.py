"""Static import fence: simulation-side code never reaches the Airwallex client.

An AST scan of every module the simulation role runs. It fails on any import of the Airwallex
connector or the execution gateway (absolute, relative, `from app.connectors import airwallex`,
`importlib` or `getattr` with a constant name, a module path in a string such as `mock.patch`,
or a chain of in-repo imports that loads one) and on any `AIRWALLEX_*` name (an environment
read, a config attribute, a settings field, a key prefix). The connector's fake holds no
credential and stays importable, as the isolation fixture's `fake-allowed` case requires.

This is the static half of the credential-isolation check. The runtime half scrubs the
simulation worker's environment and refuses the live connector under the sim role; a name
assembled at run time (`"AIRWALLEX" + suffix`) is that half's to catch.
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
# The upstream simulation subprocess: its entry scripts and the logger they load by path.
SIM_FILES = ("backend/scripts/run_*_simulation.py", "backend/scripts/action_logger.py")
# Where in-repo modules resolve from: `app.*` and `oasis_finance.*`.
SOURCE_ROOTS = ("backend", "packages/oasis-finance/src")

CONNECTOR = re.compile(r"(?:^|\.)connectors\.airwallex(?:\.(\w+))?")
GATEWAY = re.compile(r"(?:^|\.)execution\.gateway(?:\.|$)")
CREDENTIAL_NAME = re.compile(r"^(?:AIRWALLEX|(?i:airwallex_))")
IMPORTERS = {"import_module", "__import__", "find_spec"}


def forbidden(name: str) -> bool:
    """A dotted name a simulation process must never load: the connector bar its fake, or
    the execution gateway."""
    match = CONNECTOR.search(name)
    if match:
        return match.group(1) != "fake"
    return bool(GATEWAY.search(name))


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def call_target(node: ast.Call) -> str | None:
    """The module or attribute a call loads by constant name, if it is an importer or getattr."""
    func = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
    args = [a.value if isinstance(a, ast.Constant) else None for a in node.args]
    if func in IMPORTERS and args and isinstance(args[0], str):
        name = args[0]
        package = args[1] if len(args) > 1 else None
        package = next(
            (k.value.value for k in node.keywords
             if k.arg == "package" and isinstance(k.value, ast.Constant)),
            package,
        )
        if name.startswith(".") and isinstance(package, str):
            return resolve(package, len(name) - len(name.lstrip(".")), name.lstrip("."))
        return name
    if func == "getattr" and len(node.args) > 1 and isinstance(args[1], str):
        base = dotted(node.args[0])
        return f"{base}.{args[1]}" if base else None
    return None


def resolve(package: str, level: int, name: str) -> str:
    parts = [p for p in package.split(".") if p]
    anchor = parts[: len(parts) - level + 1]
    return ".".join([*anchor, name] if name else anchor)


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
    inner = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    found = []

    def flag(node: ast.AST, reason: str) -> None:
        found.append(f"{path}:{node.lineno}: {reason}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if forbidden(alias.name):
                    flag(node, f"imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = f"{module}.{alias.name}" if module else alias.name
                if forbidden(name):
                    flag(node, f"imports {'.' * node.level}{name}")
        elif isinstance(node, ast.Call):
            target = call_target(node)
            if target and forbidden(target):
                flag(node, f"loads {target}")
        elif isinstance(node, ast.Attribute):
            if CREDENTIAL_NAME.match(node.attr):
                flag(node, f"reads {node.attr}")
            elif id(node) not in inner and forbidden(dotted(node) or ""):
                flag(node, f"reaches {dotted(node)}")
        elif isinstance(node, ast.Name) and CREDENTIAL_NAME.match(node.id):
            flag(node, f"reads {node.id}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            if forbidden(node.value):
                flag(node, f"names the client module in a string: {node.value!r}")
            elif CREDENTIAL_NAME.match(node.value):
                flag(node, f"names a credential variable: {node.value!r}")
    return found


def py_files(base: Path, pattern: str = "*.py") -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob(pattern) if ".venv" not in p.parts)


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


def import_time_nodes(tree: ast.Module):
    """Nodes that run when the module is imported: everything but function bodies."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def imported_names(path: Path, module: str | None, lazy: bool) -> list[tuple[int, str]]:
    """(line, absolute dotted name) for every module the file loads.

    `lazy` counts imports inside functions too; a module reached through another is followed
    only through what runs when it is imported. A file outside the source roots (`module` is
    None) has no package, so only its absolute imports resolve.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = (module or "") if path.name == "__init__.py" else (module or "").rpartition(".")[0]
    found = []
    for node in ast.walk(tree) if lazy else import_time_nodes(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level and module is None:
                continue
            base = resolve(package, node.level, node.module or "") if node.level else node.module
            found += [(node.lineno, f"{base}.{alias.name}") for alias in node.names]
        elif isinstance(node, ast.Call) and (target := call_target(node)):
            found.append((node.lineno, target))
    return found


def with_parents(name: str) -> list[str]:
    """Importing `a.b.c` runs `a`, `a.b` and `a.b.c`."""
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def reach_hits(root: Path, path: Path, start: str | None, index: dict[str, Path]) -> list[str]:
    """Chains of in-repo imports from a simulation module that load the client."""
    seen = {start}
    queue = deque((line, [name]) for line, name in imported_names(path, start, lazy=True))
    # Importing the module first runs its parent packages.
    for parent in with_parents(start)[:-1] if start else []:
        seen.add(parent)
        if parent in index:
            queue += [(1, [parent, child])
                      for _, child in imported_names(index[parent], parent, lazy=False)]
    found = []
    while queue:
        line, chain = queue.popleft()
        leaf = chain[-1]
        if forbidden(leaf):
            if len(chain) > 1:  # a direct import is already flagged by `violations`
                via = " -> ".join(chain[:-1])
                found.append(f"{path.relative_to(root)}:{line}: reaches {leaf} via {via}")
            continue
        for name in with_parents(leaf):
            if name in index and name not in seen:
                seen.add(name)
                queue += [
                    (line, [*chain[:-1], name, child])
                    for _, child in imported_names(index[name], name, lazy=False)
                ]
    return list(dict.fromkeys(found))


def sim_modules(root: Path) -> list[Path]:
    files = [path for tree in SIM_TREES for path in py_files(root / tree)]
    for pattern in SIM_FILES:
        files += sorted(p for p in root.glob(pattern) if p.is_file())
    return files


def scan(root: Path) -> list[str]:
    index = module_index(root)
    modules = {file: name for name, file in index.items()}
    hits = []
    for path in sim_modules(root):
        hits += violations(path.relative_to(root), path.read_text(encoding="utf-8"))
        hits += reach_hits(root, path, modules.get(path), index)
    return hits


def plant(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def plant_packages(root: Path, *packages: str) -> None:
    for package in packages:
        plant(root, f"backend/{package.replace('.', '/')}/__init__.py", "")


STORE_REACHES_LIVE = "from ..connectors.airwallex import live\n"


def test_simulation_side_never_reaches_airwallex():
    scanned = [str(p.relative_to(ROOT)) for p in sim_modules(ROOT)]
    assert "backend/scripts/run_parallel_simulation.py" in scanned, scanned
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
        "from app.connectors.airwallex.client import *\n",
        "from app.connectors import airwallex\n",
        "from ..connectors.airwallex import live\n",
        "from ..connectors import airwallex\n",
        "import backend.app.connectors.airwallex.client as client\n",
        "from app.execution import gateway\n",
        "from ..execution.gateway import submit\n",
        "import app.execution.gateway\n",
        "import importlib\nimportlib.import_module('app.connectors.airwallex.live')\n",
        "import importlib\nimportlib.import_module('.airwallex.live', 'app.connectors')\n",
        "import importlib\nimportlib.import_module('..gateway', package='app.execution.x')\n",
        "__import__('app.connectors.airwallex.live')\n",
        "from app import connectors\ngetattr(connectors, 'airwallex')\n",
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
        "class Settings(BaseSettings):\n    airwallex_api_key: str = ''\n",
    ],
)
def test_fence_catches_every_credential_read(tmp_path, source):
    plant(tmp_path, "packages/oasis-finance/src/oasis_finance/planted.py", source)
    hits = scan(tmp_path)
    assert hits and all("airwallex" in h.lower() for h in hits), hits


@pytest.mark.parametrize(
    "source",
    [
        "from app.finance import store\n",
        "from ..finance.store import Store\n",
        "import app.finance.store\n",
        "def later():\n    from app.finance import store\n",
    ],
)
def test_fence_catches_a_chain_through_another_module(tmp_path, source):
    plant_packages(tmp_path, "app", "app.finance", "app.simulation")
    plant(tmp_path, "backend/app/finance/store.py", STORE_REACHES_LIVE)
    plant(tmp_path, "backend/app/simulation/indirect.py", source)
    hits = scan(tmp_path)
    line = source.count("\n")
    chain = "reaches app.connectors.airwallex.live via app.finance.store"
    assert hits == [f"backend/app/simulation/indirect.py:{line}: {chain}"]


@pytest.mark.parametrize(
    ("rel", "source", "via"),
    [
        ("backend/app/finance/store.py",
         "import importlib\nlive = importlib.import_module('app.connectors.airwallex.live')\n",
         "app.finance.store"),
        ("backend/app/finance/store.py", "from ..execution.gateway import submit\n",
         "app.finance.store"),
        ("backend/app/connectors/airwallex/__init__.py", "from . import live\n",
         "app.connectors.airwallex"),
    ],
)
def test_fence_follows_what_a_reached_module_loads(tmp_path, rel, source, via):
    plant_packages(tmp_path, "app", "app.finance", "app.connectors", "app.simulation")
    plant(tmp_path, rel, source)
    plant(tmp_path, "backend/app/simulation/indirect.py", (
        "from app.finance import store\nfrom app.connectors.airwallex import fake\n"
    ))
    assert any(f"via {via}" in h for h in scan(tmp_path)), scan(tmp_path)


def test_fence_runs_the_parent_packages_of_a_simulation_module(tmp_path):
    plant_packages(tmp_path, "app", "app.finance")
    plant(tmp_path, "backend/app/finance/store.py", STORE_REACHES_LIVE)
    plant(tmp_path, "backend/app/simulation/__init__.py", "from app.finance import store\n")
    plant(tmp_path, "backend/app/simulation/world.py", "x = 1\n")
    live = "reaches app.connectors.airwallex.live via"
    assert scan(tmp_path) == [
        f"backend/app/simulation/__init__.py:1: {live} app.finance.store",
        f"backend/app/simulation/world.py:1: {live} app.simulation -> app.finance.store",
    ]


@pytest.mark.parametrize(
    "rel",
    ["backend/scripts/run_market_simulation.py", "packages/oasis-finance/tests/test_world.py"],
)
def test_fence_scans_the_simulation_entry_points_and_tests(tmp_path, rel):
    plant_packages(tmp_path, "app", "app.finance")
    plant(tmp_path, "backend/app/finance/store.py", STORE_REACHES_LIVE)
    plant(tmp_path, rel, "from app.finance import store\n")
    assert scan(tmp_path) == [
        f"{rel}:1: reaches app.connectors.airwallex.live via app.finance.store"
    ]


def test_fence_ignores_what_runs_only_when_a_reached_function_is_called(tmp_path):
    plant_packages(tmp_path, "app.finance", "app.api")
    plant(tmp_path, "backend/app/__init__.py", "def create_app():\n    from .api import v1\n")
    plant(tmp_path, "backend/app/api/v1.py", "from app.connectors.airwallex import live\n")
    plant(tmp_path, "backend/app/finance/ledger.py", "import decimal\n")
    plant(tmp_path, "backend/app/simulation/world.py", "from app.finance import ledger\n")
    assert scan(tmp_path) == []


def test_fence_passes_clean_simulation_code(tmp_path):
    plant(tmp_path, "backend/app/finance/ledger.py", "import decimal\n")
    plant(tmp_path, "backend/app/connectors/airwallex/fake.py", "class FakeTransport: ...\n")
    plant(tmp_path, "backend/app/simulation/clean.py", (
        '"""Never imports app.connectors.airwallex.live; AIRWALLEX_* stays out of reach."""\n'
        "import os\n"
        "import app.connectors.airwallex.fake\n"
        "from app.connectors.airwallex import fake\n"
        "from app.connectors.airwallex.fake import FakeTransport\n"
        "from unittest import mock\n"
        "from app.finance import ledger\n"
        "from ..execution import approval\n\n"
        "def model_name():\n"
        '    """Reads LLM_MODEL_NAME, never AIRWALLEX_MODE."""\n'
        "    mock.patch('app.connectors.airwallex.fake.FakeTransport.send')\n"
        "    transport = app.connectors.airwallex.fake.FakeTransport()\n"
        "    return os.getenv('LLM_MODEL_NAME'), ledger, approval, transport, 'Airwallex sandbox'\n"
    ))
    assert sim_modules(tmp_path)
    assert scan(tmp_path) == []
