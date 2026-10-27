"""The entry's docs do not claim less than the code does: retired claims stay retired."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ("README.md", "docs/submission.md", "docs/architecture.md")
CLIENT = ROOT / "backend/app/connectors/airwallex/client.py"

# Claims that were true once and are not now: (phrase, the change that retired it).
RETIRED = [
    ("no deposit lookup", "the connector looks a deposit up by reference and waits on it"),
    ("unknown deposit remains an operator incident because", "unknown only after the wait"),
]

# Each doc's corrected Mode B claim names the client methods that make it true.
SYMBOLS = ("find_deposit", "wait_for_deposit")


def _text(name: str) -> str:
    return " ".join((ROOT / name).read_text(encoding="utf-8").lower().split())


@pytest.mark.parametrize("name", DOCS)
@pytest.mark.parametrize("phrase", [phrase for phrase, _ in RETIRED])
def test_a_retired_claim_is_absent(name: str, phrase: str) -> None:
    assert phrase not in _text(name), f"{name} still says {phrase!r}"


def _methods() -> set[str]:
    tree = ast.parse(CLIENT.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


@pytest.mark.parametrize("name", DOCS)
def test_the_corrected_claim_names_symbols_that_exist(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    methods = _methods()
    for symbol in SYMBOLS:
        assert symbol in methods, f"{symbol} is gone from {CLIENT.name}; fix the docs"
        assert f"`{symbol}`" in text, f"{name} does not name `{symbol}`"
