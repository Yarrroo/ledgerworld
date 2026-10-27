"""The demo: one command, the beats of system brief §13, one receipt (T23, g3).

``python -m app.demo.run --mode fake|sandbox --out FILE`` (``scripts/demo.sh`` wraps it):

1. **state** — the demo world's C5 snapshot (``scenarios/world.json``: LF-1's treasury and LF-2's
   pool) with LF-2's revenue advance ``adv-a`` on offer to the treasury, frozen.
2. **world** — its eight actors, and one actor's objective and information scope.
3. **shock** — the delayed-receipt and confidence-rumour families, both from round 3.
4. **fork** — the world runs to its checkpoint, then the three policies each run in a fresh
   branch on the same shock (``decisions.candidates.evaluate``) and are ranked.
5. **break** — reverse stress is not built (the cut line, §15), so this beat is the failure
   conditions of the policies that did not hold: their earliest breach in their own branch.
6. **execute** — the selected policy decides again on the observed snapshot at t = 12 h
   (``plan_for_now``), the plan is bound (C3) and crosses the gateway: the advance, then the
   payroll payout after it.
7. **reconcile** — the payout is moved to ``PAID`` and the sweep closes both legs against the
   ledger; the receipt is written.

The simulation runs in a child process (``python -m app.demo.run simulate``) whose environment
has no ``AIRWALLEX_*`` variable and no demo token, under ``LEDGERWORLD_ROLE=sim``; it never
imports the live connector or the gateway, and says so in its output, which the parent checks.
Its branches live in a new temporary directory, so every run simulates them afresh.

Fake mode: the connector's ``FakeTransport`` (never the process's Airwallex variables) and the
confidence-rumour family's ``ScriptedModel`` plan. Sandbox mode: the Airwallex sandbox from the
environment and the configured model (``LLM_BASE_URL=scripted://…`` is a scripted plan, anything
else a live OpenAI-compatible model); its payroll beneficiary is ``--beneficiary`` and a Mode A
run needs ``--connected-account``. In Mode B a short sandbox wallet is funded first by one
deposit listed under ``setup``, never as a checkpoint. The payout is walked along the transfer
statuses the fake accepts (``PROCESSING → SENT → PAID``); a live run (T31) confirms the sandbox's.

Receipt timestamps are wall-clock UTC; the ledger and the gateway run on the world's simulated
clock, which ``story.execute.simulated_now`` names. Exit 0 when the run finished and its receipt
was written; 1 when a step failed (a receipt is still written, carrying ``failed``); 2 on bad
usage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..finance.schemas import Money, Snapshot, to_provider_decimal
from ..finance.spendability import grouped
from ..simulation.scenarios import DemoWorld, load_family, load_world

BEATS = ["state", "world", "shock", "fork", "break", "execute", "reconcile"]
FAMILIES = ("delayed-receipt", "confidence-rumour")  # the shock; the rumour's script drives
TREASURY, LENDER = "treasury", "lender"
CP_ROUND = 2  # the committed boundary the branches fork from; the shock lands in round 3
HORIZON_H = 72
OBSERVED_T_H = 12  # the selected policy decides again on the world as observed then
TERMS = {"adv-a": {"arrive_by_h": 18}}  # LF-1: the advance is eligible when it lands by t = 18
ADVANCE = {  # LF-2's advance to borrower-a: 10,000.00, flat fee 8 %, repaid at 15 % of revenue
    "contract_id": "adv-a", "lender": LENDER, "borrower": TREASURY, "state": "offered",
    "kind": "revenue_advance", "principal": {"minor": 1_000_000, "currency": "USD"},
    "fee_bps": 800, "repay_share_bps": 1500}
PAYROLL = "payroll-1"
FAKE_BENEFICIARY = "ben-payroll-1"  # the fake provider's allowlisted payroll beneficiary
APPROVER = "demo operator"
PAYOUT_PATH = ("PROCESSING", "SENT", "PAID")
SETUP_LABEL = "sandbox wallet funding (setup, not part of the plan)"
SIM_ROLE = "sim"
LIVE_CONNECTOR = "app.connectors.airwallex.live"
GATEWAY = "app.execution.gateway"
ROOT = Path(__file__).resolve().parents[3]
SOURCES = (ROOT / "backend", ROOT / "packages" / "oasis-finance" / "src")


class DemoFailed(RuntimeError):
    """A step of the demo did not happen; the receipt says which."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def usd(minor: int) -> str:
    return grouped(minor, "USD")


# ------------------------------------------------------------------------------- the world


def demo_snapshot(world: DemoWorld) -> Snapshot:
    """The frozen snapshot: the demo world with ``adv-a`` on offer, checked by both families."""
    data = world.snapshot.model_dump(mode="json")
    data["contracts"].append(ADVANCE)
    snap = Snapshot.model_validate(data)
    for family_id in FAMILIES:
        snap = load_family(family_id).snapshot(snap)
    return snap


def observed_snapshot(world: DemoWorld) -> Snapshot:
    """The world as observed at t = 12 h: the receivable still pending past its promise."""
    data = demo_snapshot(world).model_dump(mode="json")
    as_of = (world.epoch + timedelta(hours=OBSERVED_T_H)).isoformat().replace("+00:00", "Z")
    data["snapshot_id"] = f"obs-{world.world_id}-r{OBSERVED_T_H // 4}"
    data["as_of"] = as_of
    for account in data["accounts"]:
        account["as_of"] = as_of
    return Snapshot.model_validate(data)


def shock_events() -> list[dict]:
    return [event for family_id in FAMILIES for event in load_family(family_id).events]


def describe(event: dict) -> str:
    if event["kind"] == "delay_receipt":
        return f"round {event['round']}: {event['flow_id']} delayed {event['delay_h']} h"
    if event["kind"] == "public_post":
        return f"round {event['round']}: {event['author']} posts \"{event['text']}\""
    return f"round {event['round']}: {event['kind']}"


# ----------------------------------------------------------------- the simulation (child)


def model_factory(source: str) -> tuple[str, Any]:
    """(``scripted|live``, a ``World`` model factory). ``family`` is the rumour's script;
    ``configured`` is ``LLM_BASE_URL``'s plan or a live OpenAI-compatible model."""
    from ..testing.scripted_model import ScriptedPlan

    plan = load_family(FAMILIES[1]).plan() if source == "family" else ScriptedPlan.from_env()
    if plan is not None:
        return "scripted", lambda actor_id, w: plan.model(actor_id, lambda: w.clock.round)
    missing = [n for n in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_NAME") if not os.environ.get(n)]
    if missing:
        raise DemoFailed(f"a live model needs {', '.join(missing)}")
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType

    def live(actor_id: str, w: Any) -> Any:
        return ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type=os.environ["LLM_MODEL_NAME"], api_key=os.environ["LLM_API_KEY"],
            url=os.environ["LLM_BASE_URL"])

    return "live", live


async def simulate(run_id: str, seed: int, source: str, workdir: Path) -> dict:
    """Freeze, shock, fork three fresh branches, rank: everything before money moves."""
    from ..decisions.candidates import ALL, evaluate
    from ..decisions.objective import rank
    from ..finance.lending import capacity
    from ..simulation.branches import checkpoint
    from ..simulation.coordinator import Coordinator
    from ..simulation.world import World

    world = load_world()
    snap = demo_snapshot(world)
    events = shock_events()
    kind, model = model_factory(source)
    base = World(world.world_id, "base", snap, world.actors, model=model, workdir=workdir,
                 seed=seed, epoch=world.epoch, coordinator=Coordinator())
    k_p0 = capacity(base.store, LENDER, base.clock.now).K_p
    async with base:
        await base.run(CP_ROUND)
        cp = checkpoint(base)

    created: dict[str, tuple[str, Any]] = {}

    def branch_model(actor_id: str, w: Any) -> Any:  # called first while the branch is built
        created.setdefault(w.branch_id, (utc_now(), w))
        return model(actor_id, w)

    evaluations = await evaluate(run_id, cp, {"shock": events}, ALL, model=branch_model,
                                 workdir=workdir, terms=TERMS, horizon_h=HORIZON_H)
    escalate_to = next(e.escalation for e in snap.entities if e.entity_id == TREASURY)
    result = rank(evaluations, order=[p.id for p in ALL], run_id=run_id,
                  checkpoint={"branch": cp.branch_id, "round": cp.round,
                              "snapshot_id": cp.snapshot.snapshot_id},
                  escalate_to=escalate_to)
    fresh = next((e for e in evaluations if e.policy == result.selected), None)
    fresh_branch = None
    if fresh is not None:
        at, w = created[fresh.branch_id]
        fresh_branch = {
            "branch_id": fresh.branch_id, "created_at": at, "rounds": w.clock.round - cp.round,
            "model_calls": len(w.transcript.calls(cp.transcript_cursor)),
            "parent_snapshot_id": cp.snapshot.snapshot_id, "cached": fresh.replay}
    treasury = next(a for a in world.actors if a["actor_id"] == TREASURY)
    names = {e.entity_id: e.name for e in snap.entities}
    operating = next(a for a in snap.accounts if a.id == f"{TREASURY}/operating")
    return {
        "run_id": run_id, "seed": seed, "model": kind,
        "state": {
            "snapshot_id": snap.snapshot_id, "as_of": snap.as_of.isoformat(),
            "accounts": [{"id": a.id, "settled": a.buckets.settled.minor,
                          "reserved": a.buckets.reserved.minor} for a in snap.accounts],
            "floor": operating.floor.minor,
            "obligations": [{"id": o.obligation_id, "amount": o.amount.minor,
                             "due_at": o.due_at.isoformat()} for o in snap.obligations],
            "lender_K_p": k_p0},
        "world": {
            "actors": [{"actor_id": a["actor_id"], "name": names[a["actor_id"]],
                        "on_model": bool(a.get("llm"))} for a in world.actors],
            "focus": {k: treasury[k] for k in ("actor_id", "objective", "tools", "sees")}},
        "shock": {"events": events, "checkpoint": {"branch": cp.branch_id, "round": cp.round}},
        "fork": {
            "policies": [{"id": e.policy, "branch_id": e.branch_id,
                          "feasible": e.feasibility.feasible, "actions": e.actions,
                          "lender_K_p_by_round": e.capacity.get(LENDER, {}),
                          "treasury_model_calls": e.treasury_model_calls}
                         for e in evaluations],
            "ranking": result.ranking, "selected": result.selected, "status": result.status,
            "label": result.label, "escalation": result.escalation},
        "break": [{"policy": e.policy, "floor": e.feasibility.floor.as_dict(),
                   "obligations": [o.as_dict() for o in e.feasibility.obligations if not o.met]}
                  for e in evaluations if not e.feasibility.feasible],
        "fresh_branch": fresh_branch,
        "isolation": {
            "role": os.environ.get("LEDGERWORLD_ROLE"),
            "airwallex_vars": sorted(k for k in os.environ if k.startswith("AIRWALLEX_")),
            "demo_token": "LEDGERWORLD_DEMO_TOKEN" in os.environ,
            "imported": sorted(m for m in (LIVE_CONNECTOR, GATEWAY) if m in sys.modules)},
    }


def sim_env(env: dict[str, str]) -> dict[str, str]:
    """The child's environment: no provider variable, no demo token, the sim role, and this
    tree's own sources first on its path."""
    scrubbed = {k: v for k, v in env.items()
                if not k.startswith("AIRWALLEX_") and k != "LEDGERWORLD_DEMO_TOKEN"}
    path = [str(SOURCES[0]), str(SOURCES[1]), *filter(None, [env.get("PYTHONPATH")])]
    return scrubbed | {"LEDGERWORLD_ROLE": SIM_ROLE, "PYTHONPATH": os.pathsep.join(path)}


def run_simulation(run_id: str, seed: int, source: str, scratch: Path) -> dict:
    """The simulation in its own process; its platform log is shown only when it fails."""
    out = scratch / "simulation.json"
    proc = subprocess.run(
        [sys.executable, "-m", "app.demo.run", "simulate", "--run-id", run_id, "--seed",
         str(seed), "--model", source, "--out", str(out)],
        env=sim_env(dict(os.environ)), check=False, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        print("\n".join((proc.stdout + proc.stderr).splitlines()[-40:]), file=sys.stderr)
        raise DemoFailed(f"the simulation process exited {proc.returncode}")
    sim = json.loads(out.read_text(encoding="utf-8"))
    iso = sim["isolation"]
    if iso["role"] != SIM_ROLE or iso["airwallex_vars"] or iso["demo_token"] or iso["imported"]:
        raise DemoFailed(f"the simulation process was not isolated: {iso}")
    return sim


# ------------------------------------------------------------- execution (parent process)


def provider(mode: str) -> Any:
    """The Airwallex client: the fake from an environment of its own, or the sandbox's."""
    from ..connectors.airwallex.client import client_from_env

    if mode == "fake":
        return client_from_env({"AIRWALLEX_MODE": "fake"})
    if os.environ.get("AIRWALLEX_MODE") != "sandbox":
        raise DemoFailed("--mode sandbox needs AIRWALLEX_MODE=sandbox in the environment")
    return client_from_env()


def fund_wallet(client: Any, plan: dict, global_account_id: str | None) -> list[dict]:
    """Mode B, sandbox: top the platform wallet up to the payouts with one setup deposit."""
    need = sum(leg["amount"]["minor"] for leg in plan["legs"] if leg["kind"] == "payout")
    held = {b.currency: b.available.minor for b in client.balances()}
    short = need - held.get("USD", 0)
    if short <= 0:
        return []
    if not global_account_id:
        found = [a["id"] for a in client.global_accounts()
                 if isinstance(a, dict) and a.get("currency") == "USD"]
        if not found:
            raise DemoFailed("no USD Global Account to fund the sandbox wallet from")
        global_account_id = found[0]
    amount = Money(minor=short, currency="USD")
    obj = client.simulate_deposit(amount=amount, global_account_id=global_account_id,
                                  reference=SETUP_LABEL)
    return [{"kind": "wallet_funding", "label": SETUP_LABEL, "provider_id": obj.provider_id,
             "amount": to_provider_decimal(amount)}]


def pay(client: Any, leg: Any) -> None:
    """Walk a submitted payout to ``PAID`` from whatever status it shows now."""
    path = list(PAYOUT_PATH)
    if leg.provider_status in path:
        path = path[path.index(leg.provider_status) + 1:]
    for status in path:
        client.simulate_transition(leg.provider_id, status)


def execute(selected: str, mode: str, *, beneficiary: str,
            connected_account: str | None) -> dict:
    """The selected policy's plan on the observed snapshot, bound, executed and reconciled."""
    from ..connectors.airwallex.client import connected_setting
    from ..decisions.candidates import ALL, plan_for_now
    from ..execution import reconcile
    from ..execution.approval import bind
    from ..execution.gateway import Gateway
    from ..finance.ledger import from_snapshot
    from ..finance.store import LedgerStore

    world = load_world()
    observed = observed_snapshot(world)
    now = observed.as_of
    policy = next(p for p in ALL if p.id == selected)
    plan = plan_for_now(policy, observed, epoch=world.epoch, terms=TERMS,
                        beneficiaries={PAYROLL: beneficiary})
    if plan is None:
        raise DemoFailed(f"{selected} proposes nothing on {observed.snapshot_id}")
    client = provider(mode)
    leg_mode = client.probe_connected(connected_setting({} if mode == "fake" else None))
    if leg_mode == "A" and not connected_account:
        raise DemoFailed("Mode A needs --connected-account")
    global_account_id = os.environ.get("AIRWALLEX_GLOBAL_ACCOUNT_ID") or None
    setup = fund_wallet(client, plan, global_account_id) \
        if mode == "sandbox" and leg_mode == "B" else []
    store = LedgerStore("sqlite://")
    from_snapshot(store, observed)
    gateway = Gateway(store, client, mode=mode, leg_mode=leg_mode, beneficiaries=[beneficiary],
                      clock=lambda: now, connected_account=connected_account,
                      global_account_id=global_account_id)
    approval = bind(plan, observed, APPROVER, mode, now=now)
    gateway.record(approval)
    done = gateway.execute(approval.model_dump(mode="json"),
                           current_snapshot_id=observed.snapshot_id)
    story = {"simulated_now": now.isoformat(), "observed_snapshot_id": observed.snapshot_id,
             "leg_mode": leg_mode, "approval": {
                 "approval_id": approval.approval_id, "plan_hash": approval.plan_hash,
                 "legs": [leg.model_dump(mode="json", exclude_none=True)
                          for leg in approval.legs]}}
    if not done.ok:
        raise DemoFailed(f"the gateway refused the approval: {done.code} ({done.detail})")
    stamps: dict[str, str] = {}

    def stamp_settled() -> None:
        for leg in gateway.legs(done.execution_id):
            if leg.state == "settled" and leg.reconciled:
                stamps.setdefault(leg.leg_id, utc_now())

    stamp_settled()
    for leg in gateway.legs(done.execution_id):
        if leg.kind == "payout" and leg.state == "submitted":
            pay(client, leg)
    reconcile.sweep(gateway)
    stamp_settled()
    legs = {leg.kind: leg for leg in gateway.legs(done.execution_id)}

    def checkpoint(kind: str) -> dict | None:
        leg = legs.get(kind)
        if leg is None:
            return None
        return {"leg_id": leg.leg_id, "request_id": leg.request_id,
                "provider_id": leg.provider_id, "label": leg.receipt_label,
                "status": leg.provider_status, "journal_id": leg.journal_id,
                "reconciled": leg.reconciled, "mode": mode,
                "at": stamps.get(leg.leg_id, utc_now()), "state": leg.state}

    return {"connected": leg_mode == "A", "setup": setup, "story": story,
            "advance": checkpoint("advance"), "payout": checkpoint("payout"),
            "incidents_open": len(gateway.incidents(open_only=True))}


# ----------------------------------------------------------------------------- the receipt


def say(beat: str, text: str) -> None:
    print(f"[{BEATS.index(beat) + 1}/7 {beat}] {text}", flush=True)


def tell(sim: dict) -> None:
    state, world, fork = sim["state"], sim["world"], sim["fork"]
    cash = ", ".join(f"{a['id']} {usd(a['settled'])}" for a in state["accounts"])
    owed = ", ".join(f"{o['id']} {usd(o['amount'])} due {o['due_at']}"
                     for o in state["obligations"])
    say("state", f"snapshot {state['snapshot_id']} as of {state['as_of']}: {cash}; "
                 f"floor {usd(state['floor'])}; {owed}; lender K_p {usd(state['lender_K_p'])}")
    focus = world["focus"]
    say("world", f"{len(world['actors'])} actors ("
                 + ", ".join(a["name"] for a in world["actors"])
                 + f"); {focus['actor_id']}: {focus['objective']}; sees "
                 + ", ".join(focus["sees"]))
    say("shock", "; ".join(describe(e) for e in sim["shock"]["events"])
        + f" (forked from {sim['shock']['checkpoint']['branch']} at round "
          f"{sim['shock']['checkpoint']['round']})")
    rows = []
    for p in fork["policies"]:
        k_p = p["lender_K_p_by_round"]
        low = f", lender K_p down to {usd(min(k_p.values()))}" if k_p else ""
        rows.append(f"{p['id']} {'feasible' if p['feasible'] else 'infeasible'} in "
                    f"{p['branch_id']}{low}")
    say("fork", "; ".join(rows) + f" -> {fork['label']}")
    breaks = [f"{b['policy']}: cash {usd(b['floor']['min_cash'])} at t={b['floor']['at_h']} h, "
              f"{usd(b['floor']['short_minor'])} under the floor" for b in sim["break"]]
    say("break", "; ".join(breaks) or "every policy held on this shock")


def receipt_of(sim: dict | None, done: dict | None, *, mode: str, seed: int, run_id: str,
               started: str, failed: str | None) -> dict:
    done = done or {}
    checkpoints = {}
    if sim and sim.get("fresh_branch"):
        checkpoints["fresh_branch"] = sim["fresh_branch"] | {"mode": mode}
    for name, kind in (("advance_reconciled", "advance"), ("payout_reconciled", "payout")):
        if done.get(kind):
            checkpoints[name] = {k: v for k, v in done[kind].items() if k != "state"}
    story = {k: sim[k] for k in ("state", "world", "shock", "fork", "break")} if sim else {}
    if "story" in done:
        story["execute"] = done["story"]
    receipt = {
        "run_id": run_id, "started_at": started, "finished_at": utc_now(), "mode": mode,
        "connected": done.get("connected", False),
        "model": sim["model"] if sim else ("scripted" if mode == "fake" else "live"),
        "seed": seed, "beats": BEATS, "setup": done.get("setup", []),
        "checkpoints": checkpoints, "incidents_open": done.get("incidents_open", 0),
        "story": story,
    }
    if failed:
        receipt["failed"] = failed
    return receipt


def demo(mode: str, out: Path, seed: int | None, *, beneficiary: str | None,
         connected_account: str | None) -> int:
    started = utc_now()
    run_id = "demo-" + started.replace("-", "").replace(":", "")
    seed = load_family(FAMILIES[0]).seed if seed is None else seed
    sim = done = None
    failed = None
    try:
        if mode == "sandbox" and not beneficiary:
            raise DemoFailed("--mode sandbox needs --beneficiary (the sandbox payroll "
                             "beneficiary id)")
        with tempfile.TemporaryDirectory(prefix="ledgerworld-demo-") as scratch:
            sim = run_simulation(run_id, seed, "family" if mode == "fake" else "configured",
                                 Path(scratch))
        tell(sim)
        if sim["fork"]["selected"] is None:
            raise DemoFailed(f"no feasible plan: {sim['fork']['escalation']}")
        done = execute(sim["fork"]["selected"], mode, beneficiary=beneficiary or FAKE_BENEFICIARY,
                       connected_account=connected_account)
        approval = done["story"]["approval"]
        say("execute", f"approval {approval['approval_id']} ({len(approval['legs'])} legs, "
                       f"mode {mode}, leg mode {done['story']['leg_mode']}) on "
                       f"{done['story']['observed_snapshot_id']}"
                       + "".join(f"; setup {s['label']} {s['amount']}" for s in done["setup"]))
        for kind in ("advance", "payout"):
            leg = done[kind]
            if leg is None or leg["state"] != "settled" or not leg["reconciled"]:
                raise DemoFailed(f"the {kind} leg did not settle: {leg}")
        say("reconcile", "; ".join(
            f"{k} {done[k]['status']} {done[k]['provider_id']} -> {done[k]['journal_id']} "
            f"({done[k]['label']})" for k in ("advance", "payout"))
            + f"; incidents open {done['incidents_open']}")
    except DemoFailed as failure:
        failed = str(failure)
        print(f"demo: failed: {failed}", file=sys.stderr)
    receipt = receipt_of(sim, done, mode=mode, seed=seed, run_id=run_id, started=started,
                         failed=failed)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"receipt: {out}")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["simulate"]:
        parser = argparse.ArgumentParser(prog="app.demo.run simulate")
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--seed", type=int, required=True)
        parser.add_argument("--model", choices=("family", "configured"), required=True)
        parser.add_argument("--out", type=Path, required=True)
        args = parser.parse_args(argv[1:])
        with tempfile.TemporaryDirectory(prefix="ledgerworld-branches-") as workdir:
            sim = asyncio.run(simulate(args.run_id, args.seed, args.model, Path(workdir)))
        args.out.write_text(json.dumps(sim, default=str), encoding="utf-8")
        return 0
    parser = argparse.ArgumentParser(prog="scripts/demo.sh", description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=("fake", "sandbox"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--beneficiary", default=None,
                        help="sandbox: the payroll beneficiary id (fake: its own)")
    parser.add_argument("--connected-account", default=None,
                        help="sandbox Mode A: borrower-a's connected account id")
    args = parser.parse_args(argv)
    if args.mode == "fake" and (args.beneficiary or args.connected_account):
        parser.error("--beneficiary and --connected-account are sandbox options")
    return demo(args.mode, args.out, args.seed, beneficiary=args.beneficiary,
                connected_account=args.connected_account)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
