"""The two job kinds a simulation worker runs: a run and a fork.

``run``: the demo world hit by one scenario family (``simulation.scenarios``), round by round. Each
committed round is written to the run's record at once, so a reader sees a running run's
committed rounds and nothing past them. The base branch's transcript is kept for the interview.

``fork``: one fresh branch per policy at a committed round of a finished run
(``decisions.candidates.evaluate``, ranked by ``decisions.objective.rank``). The run's world is not
kept between jobs, so the fork rebuilds it on the same family, seed and script up to the
checkpoint and refuses to go on unless every round committed the same journals as the run did
(replay identity); the policies then run on that checkpoint to the horizon.

Only a scripted run can be forked: a live model asked again answers differently, so its replay
could never match. Each job works in a scratch directory removed when it ends.

A handler is re-run whole on retry: it rewrites what it writes. This module runs in the simulation
role and imports no provider connector and no execution gateway.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..decisions.candidates import ALL, evaluate
from ..decisions.objective import rank
from ..finance.spendability import state_of
from ..simulation.branches import checkpoint
from ..simulation.clock import ROUND_HOURS
from ..simulation.scenarios import DemoWorld, Family, build_world, load_family, load_world
from ..simulation.transcripts import ModelCall, Transcript
from ..simulation.world import ModelFactory, World
from .queue import Handler, JobContext
from .store import Job, JobStore

RUN, FORK = "run", "fork"
TREASURY = "treasury"
POLICIES = {p.id: p for p in ALL}
WEIGHT_KIND = "unweighted"


def base_branch(run_id: str) -> str:
    return f"{run_id}-base"


def fork_branch(run_id: str, scenario_id: str, policy: str) -> str:
    """The id ``evaluate`` gives a policy branch: ``<run_id>-<scenario>-<policy>``."""
    return f"{run_id}-{scenario_id}-{policy}"


def new_run(run_id: str, snapshot_id: str, as_of: datetime) -> dict:
    """A run's record before its first round: queued, nothing committed, on the run's clock."""
    return {"run_id": run_id, "snapshot_id": snapshot_id, "committed_round": None, "rounds": [],
            "feed": [], "cash_paths": [], "branches": [], "as_of": as_of.isoformat()}


def cohort(family: Family, scenarios: int) -> str:
    return (f"{family.id} seed {family.seed}: {scenarios} scenario"
            f"{'s' if scenarios != 1 else ''}, each policy in a fresh branch")


def pending_decisions(run_id: str, snapshot_id: str, checkpoint_round: int, family: Family,
                      job_id: str) -> dict:
    """A run's decisions while its fork job has not finished; the job id names the fork."""
    return {"run_id": run_id, "snapshot_id": snapshot_id, "checkpoint_round": checkpoint_round,
            "cohort": cohort(family, 1), "weight_kind": WEIGHT_KIND, "status": "pending",
            "results": [], "selected": None, "escalation": None, "job_id": job_id}


def family_of(scenario: Mapping[str, Any]) -> Family:
    """A C6 ``ScenarioSpec`` as a family; ``ValueError`` when the world cannot run it."""
    return load_family(scenario["family"], scenario["seed"], scenario.get("params") or None)


def transcript_key(run_id: str, branch_id: str) -> str:
    return f"{run_id}/{branch_id}"


def load_transcript(store: JobStore, run_id: str, branch_id: str) -> Transcript | None:
    raw = store.get("transcript", transcript_key(run_id, branch_id))
    if raw is None:
        return None
    return Transcript(raw["world_id"], raw["branch_id"],
                      calls=[ModelCall.from_json(c) for c in raw["calls"]])


def _settled(world: World, account_id: str) -> dict:
    """A cash point's value: settled when known, the last value when stale, none when unknown."""
    view = world.store.view(account_id)
    state = state_of(view, world.clock.now)
    return {"minor": None if state == "unknown" else view.settled_minor,
            "currency": view.currency, "status": state, "as_of": view.as_of.isoformat()}


def _feed(world: World) -> list[dict]:
    return [{"post_id": item["id"], "round": item["visible_from_h"] // ROUND_HOURS,
             "branch_id": world.branch_id, "author": item.get("owner") or "public",
             "text": item["text"][:4000]}
            for item in world.state.items if item["kind"] == "public_post"]


def _round_view(world: World, result: Any) -> dict:
    entry = result.transcript_entry
    return {"round": result.round, "branch_id": world.branch_id, "t_hours": entry["t_hours"],
            "intents": [world.state.intents[i] for i in entry["intents"]
                        if i in world.state.intents],
            "cleared": [c.model_dump(mode="json", exclude_none=True) for c in result.cleared],
            "journal_ids": list(entry["journal_ids"])}


@dataclass
class Runner:
    """The handlers of one worker. ``model`` answers a family run off its own parameters; a
    family on its file's parameters runs its own scripted plan."""

    store: JobStore
    workdir: Path
    model: ModelFactory | None = None
    world: DemoWorld | None = None

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.world = self.world or load_world()

    def handlers(self) -> dict[str, Handler]:
        return {RUN: self._in_scratch(self.run), FORK: self._in_scratch(self.fork)}

    def _in_scratch(self, body: Any) -> Handler:
        """``body(job, ctx, scratch)`` in a directory of its own, removed when it ends."""
        def handler(job: Job, ctx: JobContext) -> None:
            with tempfile.TemporaryDirectory(prefix=f"{job.job_id}-", dir=self.workdir,
                                             ignore_cleanup_errors=True) as scratch:
                body(job, ctx, Path(scratch))
        return handler

    def _world(self, family: Family, workdir: Path, branch_id: str) -> World:
        if family.scripted:
            return build_world(family, workdir=workdir, branch_id=branch_id, world=self.world)
        if self.model is None:
            raise ValueError(f"family {family.id} off its file's parameters needs a live model, "
                             "and this worker has none")
        return build_world(family, model=self.model, workdir=workdir, branch_id=branch_id,
                           world=self.world)

    # ------------------------------------------------------------------------------- run

    def run(self, job: Job, ctx: JobContext, scratch: Path) -> None:
        p = job.payload
        run_id = p["run_id"]
        family = family_of(p["scenario"])
        world = self._world(family, scratch, base_branch(run_id))
        doc = new_run(run_id, world.snapshot.snapshot_id, world.clock.now)
        doc["branches"] = [{"branch_id": world.branch_id, "parent_branch_id": None,
                            "checkpoint_round": None, "policy": None, "replay": False}]
        asyncio.run(self._simulate(world, p["rounds"], doc, ctx))
        self.store.put("transcript", transcript_key(run_id, world.branch_id), {
            "world_id": world.world_id, "branch_id": world.branch_id,
            "calls": [c.to_json() for c in world.transcript.calls()]})

    async def _simulate(self, world: World, rounds: int, doc: dict, ctx: JobContext) -> None:
        accounts = [world.operating(TREASURY)]
        async with world:
            doc["cash_paths"] = [{"branch_id": world.branch_id, "account_id": a,
                                  "points": [{"t": world.clock.now.isoformat(),
                                              "value": _settled(world, a)}]} for a in accounts]
            self.store.put("run", doc["run_id"], doc)
            for _ in range(rounds):
                ctx.checkpoint()
                result = await world.coordinator.run_round(world)
                doc["rounds"].append(_round_view(world, result))
                doc["feed"] = _feed(world)
                for path in doc["cash_paths"]:
                    path["points"].append({"t": world.clock.now.isoformat(),
                                           "value": _settled(world, path["account_id"])})
                doc["committed_round"] = result.round
                doc["as_of"] = world.clock.now.isoformat()
                self.store.put("run", doc["run_id"], doc)

    # ------------------------------------------------------------------------------ fork

    def fork(self, job: Job, ctx: JobContext, scratch: Path) -> None:
        p = job.payload
        run_id, cp_round = p["run_id"], p["checkpoint_round"]
        run = self.store.get("run", run_id)
        if run is None or (run.get("committed_round") or 0) < cp_round:
            raise ValueError(f"run {run_id} has not committed round {cp_round}")
        family = family_of(p["scenario"])
        policies = [POLICIES[pid] for pid in p["policies"]]
        (scratch / "base").mkdir()
        (scratch / "branches").mkdir()
        base = self._world(family, scratch / "base", base_branch(run_id))
        cp = asyncio.run(self._replay_to(base, run, cp_round, ctx))
        ctx.checkpoint()
        if family.scripted:
            plan = family.plan()
            model = lambda actor_id, w: plan.model(actor_id, lambda: w.clock.round)
        else:
            model = self.model
        evaluations = asyncio.run(evaluate(
            run_id, cp, {family.id: []}, policies, model=model, workdir=scratch / "branches",
            actor=TREASURY, hooks={"delivered": family.deliver_market}))
        ctx.checkpoint()
        escalate_to = next((e.escalation for e in cp.snapshot.entities
                            if e.entity_id == TREASURY), None)
        currency = next(a.currency for a in cp.snapshot.accounts
                        if a.id == base.operating(TREASURY))
        result = rank(evaluations, order=[q.id for q in policies], run_id=run_id,
                      checkpoint={"branch": cp.branch_id, "round": cp.round,
                                  "snapshot_id": cp.snapshot.snapshot_id},
                      escalate_to=escalate_to, currency=currency)
        current = self.store.get("decisions", run_id) or {}
        if current.get("job_id") not in (None, job.job_id):
            return  # a later fork of this run owns its decisions now
        self.store.put("decisions", run_id, {
            "run_id": run_id, "snapshot_id": cp.snapshot.snapshot_id, "checkpoint_round": cp.round,
            "cohort": cohort(family, len(result.scenarios)), "job_id": job.job_id,
            "weight_kind": WEIGHT_KIND, "status": result.status, "selected": result.selected,
            "label": result.label,
            "results": [{
                "policy": e.policy, "scenario_id": e.scenario, "branch_id": e.branch_id,
                "replay": e.replay, "obligations_unmet": e.feasibility.obligations_unmet,
                "floor_kept": not e.feasibility.breached,
                "min_cash": {"minor": e.feasibility.floor.min_cash, "currency": currency,
                             "status": "known"},
                "funding_cost": {"minor": e.feasibility.funding_cost_minor,
                                 "currency": currency},
                "feasible": e.feasibility.feasible} for e in evaluations],
            "escalation": None if result.escalation is None else {
                "earliest_unmet": ", ".join(f"{k} {v}" for k, v in
                                            (result.escalation["earliest_unmet"] or {}).items()),
                "binding": result.escalation["binding"],
                "contact": result.escalation["escalate_to"] or "treasury operator"},
        })
        run = self.store.get("run", run_id)
        mine = {e.branch_id for e in evaluations}
        run["branches"] = [b for b in run["branches"] if b["branch_id"] not in mine] + [
            {"branch_id": e.branch_id, "parent_branch_id": cp.branch_id,
             "checkpoint_round": cp.round, "policy": e.policy, "replay": e.replay}
            for e in evaluations]
        run["cash_paths"] = [c for c in run["cash_paths"] if c["branch_id"] not in mine] + [
            {"branch_id": e.branch_id, "account_id": e.feasibility.account,
             "points": [{"t": (cp.epoch + timedelta(hours=h)).isoformat(),
                         "value": {"minor": settled, "currency": currency, "status": "known"}}
                        for h, settled in sorted(e.feasibility.settled.items())]}
            for e in evaluations]
        self.store.put("run", run_id, run)

    async def _replay_to(self, world: World, run: dict, cp_round: int, ctx: JobContext) -> Any:
        """The run's world again up to ``cp_round``, checked round by round, checkpointed."""
        async with world:
            for recorded in run["rounds"][:cp_round]:
                ctx.checkpoint()
                result = await world.coordinator.run_round(world)
                if list(result.transcript_entry["journal_ids"]) != recorded["journal_ids"]:
                    raise ValueError(f"replay_mismatch: round {result.round} committed other "
                                       f"journals than run {run['run_id']}")
            return checkpoint(world)
