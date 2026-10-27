"""Validate a demo receipt and count its live sandbox checkpoints.

Usage: python checks/demo_receipt.py FILE [--require-live] [--json]

The receipt is the one `scripts/demo.sh` writes (shape: the execution module's
`fixtures/demo-receipt.json`). Exit 0 when it is valid; with `--require-live`, only when all three
checkpoints — fresh_branch, advance_reconciled, payout_reconciled — are live. A live checkpoint is
one from a sandbox run with no run-level refusal, carrying no refusal of its own and a provider id
where it moves money. Their number is the g3 KPI `demo_checkpoints_live`; `checks/goals/g3.py`
takes the same count of a well-shaped receipt that carries both `started_at` and the branch's
`created_at` (g3 needs both to call a branch fresh, the fixture does not). A missing receipt
counts 0. Setup movements (funding the sandbox wallet) are listed apart and never count as a
checkpoint. Exit 1 on a refusal, 2 on bad usage. Stdlib only.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

MODES = ("fake", "sandbox")
MODELS = ("scripted", "live")
BEATS = ["state", "world", "shock", "fork", "break", "execute", "reconcile"]
CHECKPOINTS = ("fresh_branch", "advance_reconciled", "payout_reconciled")


def _utc(value: object) -> datetime | None:
    """The instant in UTC; None when absent, malformed or without an offset (any offset is fine)."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.utcoffset() is not None else None


KINDS = {
    "str": lambda v: isinstance(v, str) and v != "",
    "str?": lambda v: v is None or isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "mode": lambda v: v in MODES,
    "model": lambda v: v in MODELS,
    "utc": lambda v: _utc(v) is not None,
    "list": lambda v: isinstance(v, list),
    "dict": lambda v: isinstance(v, dict),
}

# A field kind from KINDS; "str?" means str or null. A field named in an *_OPTIONAL set may be
# absent; every other one must be present.
RUN_FIELDS = {
    "run_id": "str",
    "started_at": "utc",
    "finished_at": "utc",
    "mode": "mode",
    "connected": "bool",
    "model": "model",
    "seed": "int",
    "beats": "list",
    "setup": "list",
    "checkpoints": "dict",
    "incidents_open": "int",
}
RUN_OPTIONAL = {"started_at", "finished_at"}
SETUP_FIELDS = {"kind": "str", "label": "str", "provider_id": "str?", "amount": "str"}
LEG_FIELDS = {
    "leg_id": "str",
    "request_id": "str",
    "provider_id": "str?",
    "label": "str",
    "status": "str",
    "journal_id": "str",
    "reconciled": "bool",
    "mode": "mode",
    "at": "utc",
}
CHECKPOINT_FIELDS = {
    "fresh_branch": {
        "branch_id": "str",
        "created_at": "utc",
        "rounds": "int",
        "model_calls": "int",
        "parent_snapshot_id": "str",
        "cached": "bool",
        "mode": "mode",
    },
    "advance_reconciled": LEG_FIELDS,
    "payout_reconciled": LEG_FIELDS,
}
CHECKPOINT_OPTIONAL = {
    "fresh_branch": {"created_at", "mode"},
    "advance_reconciled": {"leg_id", "at"},
    "payout_reconciled": {"leg_id", "at"},
}


def _shape(where: str, obj: object, fields: dict[str, str], optional: set[str]) -> list[str]:
    if not isinstance(obj, dict):
        return [f"shape: {where} is not an object"]
    out = []
    for name, kind in fields.items():
        if name not in obj:
            if name not in optional:
                out.append(f"shape: {where}.{name} missing")
        elif not KINDS[kind](obj[name]):
            out.append(f"shape: {where}.{name} is not {kind}")
    return out


def _setup_moves(receipt: dict) -> list:
    setup = receipt.get("setup")
    return setup if isinstance(setup, list) else []


def _run_refusals(receipt: dict) -> list[str]:
    out = _shape("receipt", receipt, RUN_FIELDS, RUN_OPTIONAL)
    if "beats" in receipt and receipt["beats"] != BEATS:
        out.append("beats are not the seven of the demo")
    for i, move in enumerate(_setup_moves(receipt)):
        out += _shape(f"setup[{i}]", move, SETUP_FIELDS, set())
        if isinstance(move, dict) and "setup" not in str(move.get("label", "")):
            out.append(f"setup[{i}] is not labelled as setup")
    incidents = receipt.get("incidents_open")
    if KINDS["int"](incidents) and incidents != 0:
        out.append("open incident")
    started, finished = _utc(receipt.get("started_at")), _utc(receipt.get("finished_at"))
    if started and finished and finished < started:
        out.append("run finished before it started")
    return out


def _branch_rules(receipt: dict, branch: dict) -> list[str]:
    started, created = _utc(receipt.get("started_at")), _utc(branch.get("created_at"))
    if branch["cached"] or branch["rounds"] < 1 or (started and created and created < started):
        return ["branch not fresh"]
    return []


def _advance_rules(receipt: dict, advance: dict) -> list[str]:
    out = []
    if not advance["reconciled"] or advance["status"] != "SETTLED":
        out.append("advance not reconciled")
    if receipt.get("connected") is False and "simulation" not in advance["label"]:
        out.append("Mode B advance must carry the simulation label")
    return out


def _payout_rules(receipt: dict, payout: dict) -> list[str]:
    out = []
    if payout["status"] != "PAID":
        out.append("payout not settled")
    if not payout["reconciled"]:
        out.append("payout not reconciled")
    if not payout["provider_id"]:
        out.append("payout without provider id")
    return out


RULES = {
    "fresh_branch": _branch_rules,
    "advance_reconciled": _advance_rules,
    "payout_reconciled": _payout_rules,
}


def _checkpoint_refusals(receipt: dict) -> dict[str, list[str]]:
    """Each checkpoint's own refusals. Its rules run only once its own shape holds.

    Empty when `checkpoints` is not an object: the run-level shape check already refuses it.
    """
    checkpoints = receipt.get("checkpoints")
    if not isinstance(checkpoints, dict):
        return {}
    setup_ids = {
        move["provider_id"]
        for move in _setup_moves(receipt)
        if isinstance(move, dict) and KINDS["str"](move.get("provider_id"))
    }
    found = {}
    for name in CHECKPOINTS:
        cp = checkpoints.get(name)
        out = _shape(f"checkpoints.{name}", cp, CHECKPOINT_FIELDS[name], CHECKPOINT_OPTIONAL[name])
        if not out:
            if cp.get("mode", receipt.get("mode")) != receipt.get("mode"):
                out.append(f"{name} mode differs from the run's mode")
            out += RULES[name](receipt, cp)
            if cp.get("provider_id") in setup_ids:
                out.append("a setup movement is not a checkpoint")
        found[name] = out
    return found


def assess(receipt: object, require_live: bool = False) -> tuple[list[str], int]:
    """(every refusal, in order; the live checkpoint count). No refusal means valid."""
    if not isinstance(receipt, dict):
        return ["shape: receipt is not an object"], 0
    run = _run_refusals(receipt)
    per_checkpoint = _checkpoint_refusals(receipt)
    reasons = run + [reason for refusals in per_checkpoint.values() for reason in refusals]
    clean = [name for name in CHECKPOINTS if per_checkpoint.get(name) == []]
    # A clean checkpoint shares the run's mode; a clean payout already has a provider id.
    advance_without_id = (
        "advance_reconciled" in clean
        and not receipt["checkpoints"]["advance_reconciled"]["provider_id"]
    )
    sandbox = receipt.get("mode") == "sandbox"
    live = 0 if run or not sandbox else len(clean) - advance_without_id
    if require_live:
        checkpoints = receipt.get("checkpoints")
        present = [
            name
            for name in CHECKPOINTS
            if isinstance(checkpoints, dict) and isinstance(checkpoints.get(name), dict)
        ]
        if not sandbox and present:
            plural = "s" if len(present) != 1 else ""
            reasons.append(f"mode {receipt.get('mode')} on {len(present)} checkpoint{plural}")
        elif advance_without_id:
            reasons.append("advance without provider id")
    # Two legs can share one reason (both reusing the setup funding's id); list it once.
    return list(dict.fromkeys(reasons)), live


def check(receipt: object, require_live: bool = False) -> list[str]:
    """Every refusal of the receipt; empty means valid."""
    return assess(receipt, require_live)[0]


def live_checkpoints(receipt: object) -> int:
    """The g3 KPI `demo_checkpoints_live` for a parsed receipt."""
    return assess(receipt)[1]


def main(argv: list[str]) -> int:
    flags = {arg for arg in argv if arg.startswith("--")}
    paths = [arg for arg in argv if not arg.startswith("--")]
    if len(paths) != 1 or flags - {"--require-live", "--json"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(paths[0])
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reasons, live = [f"no readable receipt at {path}"], 0
    else:
        reasons, live = assess(receipt, require_live="--require-live" in flags)
    if "--json" in flags:
        print(json.dumps({"ok": not reasons, "refused": reasons, "live_checkpoints": live}))
    else:
        for reason in reasons:
            print(f"demo_receipt: refused: {reason}", file=sys.stderr)
        print(f"demo_receipt: {'ok' if not reasons else 'refused'} · live checkpoints {live}/3")
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
