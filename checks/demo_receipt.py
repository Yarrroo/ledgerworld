"""Validate a demo receipt and count its live sandbox checkpoints.

Usage: python checks/demo_receipt.py FILE [--require-live] [--json]

The receipt is the one `scripts/demo.sh` writes (shape: the execution module's
`fixtures/demo-receipt.json`). Exit 0 when it is valid; with `--require-live`, only when all three
checkpoints — fresh_branch, advance_reconciled, payout_reconciled — are live. A live checkpoint is
one from a sandbox run, in mode sandbox, with a provider id where it moves money, and with no
refusal of its own; their number is the g3 KPI `demo_checkpoints_live`. A missing receipt counts 0.
Setup movements (funding the sandbox wallet) are listed apart and never count as a checkpoint.
Exit 1 on a refusal, 2 on bad usage. Stdlib only.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

MODES = ("fake", "sandbox")
BEATS = ["state", "world", "shock", "fork", "break", "execute", "reconcile"]
CHECKPOINTS = ("fresh_branch", "advance_reconciled", "payout_reconciled")
MODELS = ("scripted", "live")
MODE_B_ADVANCE_LABEL = "advance inflow (sandbox simulation)"

# Field kinds: "str", "str?" (str or null), "int", "bool", "mode", "model", "utc", "list", "dict".
# A field named in an *_OPTIONAL set may be absent; every other one must be present.
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
RUN_OPTIONAL = {"started_at", "finished_at"}
CHECKPOINT_OPTIONAL = {
    "fresh_branch": {"created_at", "mode"},
    "advance_reconciled": {"leg_id", "at"},
    "payout_reconciled": {"leg_id", "at"},
}


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
        return None
    return stamp.astimezone(UTC)


def _kind_ok(kind: str, value: object) -> bool:
    if kind == "str":
        return isinstance(value, str) and value != ""
    if kind == "str?":
        return value is None or isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "mode":
        return value in MODES
    if kind == "model":
        return value in MODELS
    if kind == "utc":
        return _utc(value) is not None
    if kind == "list":
        return isinstance(value, list)
    if kind == "dict":
        return isinstance(value, dict)
    raise ValueError(kind)


def _shape(where: str, obj: object, fields: dict[str, str], optional: set[str]) -> list[str]:
    if not isinstance(obj, dict):
        return [f"shape: {where} is not an object"]
    out = []
    for name, kind in fields.items():
        if name not in obj:
            if name not in optional:
                out.append(f"shape: {where}.{name} missing")
        elif not _kind_ok(kind, obj[name]):
            out.append(f"shape: {where}.{name} is not {kind}")
    return out


def _run_refusals(receipt: dict) -> list[str]:
    out = _shape("receipt", receipt, RUN_FIELDS, RUN_OPTIONAL)
    if "beats" in receipt and receipt["beats"] != BEATS:
        out.append("beats are not the seven of the demo")
    setup = receipt.get("setup")
    for i, move in enumerate(setup if isinstance(setup, list) else []):
        out += _shape(f"setup[{i}]", move, SETUP_FIELDS, set())
        if isinstance(move, dict) and "setup" not in str(move.get("label", "")):
            out.append(f"setup[{i}] is not labelled as setup")
    incidents = receipt.get("incidents_open")
    if isinstance(incidents, int) and incidents != 0:
        out.append("open incident")
    started, finished = _utc(receipt.get("started_at")), _utc(receipt.get("finished_at"))
    if started and finished and finished < started:
        out.append("run finished before it started")
    return out


def _checkpoint_refusals(receipt: dict) -> dict[str, list[str]]:
    """Each checkpoint's own refusals; a checkpoint with none can count as live."""
    found: dict[str, list[str]] = {name: [] for name in CHECKPOINTS}
    checkpoints = receipt.get("checkpoints")
    if not isinstance(checkpoints, dict):
        return {name: ["shape: receipt.checkpoints is not an object"] for name in CHECKPOINTS}
    for name in CHECKPOINTS:
        cp = checkpoints.get(name)
        found[name] += _shape(
            f"checkpoints.{name}", cp, CHECKPOINT_FIELDS[name], CHECKPOINT_OPTIONAL[name]
        )
        if isinstance(cp, dict) and cp.get("mode", receipt.get("mode")) != receipt.get("mode"):
            found[name].append(f"{name} mode differs from the run's mode")
    if any(not isinstance(checkpoints.get(name), dict) for name in CHECKPOINTS):
        return found

    branch = checkpoints["fresh_branch"]
    advance = checkpoints["advance_reconciled"]
    payout = checkpoints["payout_reconciled"]

    started, created = _utc(receipt.get("started_at")), _utc(branch.get("created_at"))
    rounds = branch.get("rounds")
    if (
        branch.get("cached") is not False
        or (isinstance(rounds, int) and rounds < 1)
        or (started and created and created < started)
    ):
        found["fresh_branch"].append("branch not fresh")

    if (
        advance.get("reconciled") is not True
        or advance.get("status") != "SETTLED"
        or not advance.get("journal_id")
    ):
        found["advance_reconciled"].append("advance not reconciled")
    if receipt.get("connected") is False and advance.get("label") != MODE_B_ADVANCE_LABEL:
        found["advance_reconciled"].append("Mode B advance must carry the simulation label")

    if payout.get("status") != "PAID":
        found["payout_reconciled"].append("payout not settled")
    if payout.get("reconciled") is not True or not payout.get("journal_id"):
        found["payout_reconciled"].append("payout not reconciled")
    if not payout.get("provider_id"):
        found["payout_reconciled"].append("payout without provider id")

    setup = receipt.get("setup")
    setup_ids = {
        move.get("provider_id")
        for move in (setup if isinstance(setup, list) else [])
        if isinstance(move, dict) and move.get("provider_id")
    }
    for name in ("advance_reconciled", "payout_reconciled"):
        if checkpoints[name].get("provider_id") in setup_ids:
            found[name].append("a setup movement is not a checkpoint")
    return found


def _is_live(receipt: dict, name: str, refusals: list[str]) -> bool:
    if refusals or receipt.get("mode") != "sandbox":
        return False
    cp = receipt["checkpoints"][name]
    if cp.get("mode", receipt["mode"]) != "sandbox":
        return False
    return name == "fresh_branch" or bool(cp.get("provider_id"))


def live_checkpoints(receipt: object) -> int:
    """The g3 KPI: checkpoints that are sandbox, carry a provider id and pass on their own."""
    if not isinstance(receipt, dict):
        return 0
    per_checkpoint = _checkpoint_refusals(receipt)
    return sum(_is_live(receipt, name, per_checkpoint[name]) for name in CHECKPOINTS)


def check(receipt: object, require_live: bool = False) -> list[str]:
    """Every refusal of the receipt, in order, without repeats; empty means valid."""
    if not isinstance(receipt, dict):
        return ["shape: receipt is not an object"]
    per_checkpoint = _checkpoint_refusals(receipt)
    reasons = _run_refusals(receipt)
    for name in CHECKPOINTS:
        reasons += per_checkpoint[name]
    if require_live:
        not_sandbox: dict[str, int] = {}
        checkpoints = receipt.get("checkpoints")
        for name in CHECKPOINTS:
            cp = checkpoints.get(name) if isinstance(checkpoints, dict) else None
            if not isinstance(cp, dict):
                continue
            mode = cp.get("mode", receipt.get("mode"))
            if receipt.get("mode") != "sandbox" or mode != "sandbox":
                key = mode if mode != "sandbox" else receipt.get("mode")
                not_sandbox[str(key)] = not_sandbox.get(str(key), 0) + 1
            elif name != "fresh_branch" and not cp.get("provider_id"):
                reasons.append(f"{name.split('_')[0]} without provider id")
        for mode, n in not_sandbox.items():
            reasons.append(f"mode {mode} on {n} checkpoint{'s' if n != 1 else ''}")
    return list(dict.fromkeys(reasons))


def load(path: Path) -> object:
    """The receipt at PATH, or None when it is absent or not JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str]) -> int:
    flags = {arg for arg in argv if arg.startswith("--")}
    paths = [arg for arg in argv if not arg.startswith("--")]
    if len(paths) != 1 or flags - {"--require-live", "--json"}:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(paths[0])
    receipt = load(path)
    if receipt is None:
        reasons = [f"no readable receipt at {path}"]
    else:
        reasons = check(receipt, require_live="--require-live" in flags)
    live = live_checkpoints(receipt)
    if "--json" in flags:
        print(json.dumps({"ok": not reasons, "refused": reasons, "live_checkpoints": live}))
    else:
        for reason in reasons:
            print(f"demo_receipt: refused: {reason}", file=sys.stderr)
        print(f"demo_receipt: {'ok' if not reasons else 'refused'} · live checkpoints {live}/3")
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
