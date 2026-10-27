"""The application boundary between simulation and execution (T14).

A simulation is a fresh process, not an in-process role switch. Its launcher passes
``spawn_sim(parent_env)`` to the child; app bootstrap scrubs before loading config and
checks again afterward in case dotenv selected the sim role.
The live connector and gateway call ``require_execution`` before loading their dependencies.
This is not an arbitrary-Python sandbox: deployment must isolate users, files, database
permissions and provider network access (isolation.json assigns that boundary to T24).
"""

import os
from collections.abc import Mapping


class BoundaryViolation(ImportError):
    """A simulation process tried to load an execution-only module."""


def spawn_sim(env: Mapping[str, str]) -> dict[str, str]:
    """Return the child environment without changing the execution parent's environment."""
    clean = {name: value for name, value in env.items()
             if not name.startswith("AIRWALLEX_") and name != "LEDGERWORLD_DEMO_TOKEN"}
    return clean | {"LEDGERWORLD_ROLE": "sim", "PYTHON_DOTENV_DISABLED": "1"}


def enter_sim() -> None:
    """In a dedicated simulation child, before world work or dotenv loading."""
    clean = spawn_sim(os.environ)
    os.environ.clear()
    os.environ.update(clean)


def bootstrap() -> None:
    """Check both sides of config loading, including a sim role selected by dotenv."""
    if os.environ.get("LEDGERWORLD_ROLE") == "sim":
        enter_sim()


def require_execution() -> None:
    """Refuse execution-only imports before a provider client or gateway is constructed."""
    if os.environ.get("LEDGERWORLD_ROLE") == "sim":
        raise BoundaryViolation("the simulation role cannot load execution modules")
