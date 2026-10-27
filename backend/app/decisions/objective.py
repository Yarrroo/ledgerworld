"""The objective: rank policies lexicographically on their paired branches (§9, HANDOFF `rank`).

Key per policy, smaller first, all integers: ``(obligations_unmet, branches_breached,
max_short_minor, funding_cost_minor)``. Counts and cost are summed over scenarios; the short is
the largest single-branch short. Nothing is averaged. Equal keys keep the declared order and are
reported as ties. Selected = the first ranked policy feasible on every scenario; when there is
none the result is ``all_infeasible``: no plan, the floor and the reservations untouched, and the
earliest unmet constraint, the binding constraint and the role to escalate to named.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from ..finance.spendability import grouped
from .feasibility import Feasibility

__all__ = ["KEY_FIELDS", "DecisionResult", "Evaluation", "policy_key", "rank"]

KEY_FIELDS = ("obligations_unmet", "branches_breached", "max_short_minor", "funding_cost_minor")


@dataclass(frozen=True)
class Evaluation:
    """One policy on one scenario, in its own fresh branch."""

    scenario: str
    policy: str
    branch_id: str
    feasibility: Feasibility
    actions: list[dict] = field(default_factory=list)  # [{round, type, ...}] as decided
    c2: list[dict] = field(default_factory=list)  # the policy's intents as the world cleared them
    intents: list[dict] = field(default_factory=list)  # the C1 the policy queued
    decisions: list[dict] = field(default_factory=list)  # per round: obs_hash, actions, evidence
    capacity: dict[str, dict[int, int]] = field(default_factory=dict)  # pool -> round -> K_p
    schedule_hash: str = ""
    seed: int = 0
    treasury_model_calls: int = 0
    replay: bool = False

    def row(self) -> dict:
        return {"scenario": self.scenario, "branch_id": self.branch_id, "replay": self.replay,
                "actions": self.actions, "c2": self.c2,
                "feasibility": self.feasibility.as_dict()}


def policy_key(feasibilities: Sequence[Feasibility]) -> tuple[int, int, int, int]:
    return (sum(f.obligations_unmet for f in feasibilities),
            sum(1 for f in feasibilities if f.breached),
            max((f.floor.short_minor for f in feasibilities), default=0),
            sum(f.funding_cost_minor for f in feasibilities))


@dataclass(frozen=True)
class DecisionResult:
    run_id: str
    checkpoint: dict
    scenarios: list[str]
    policies: list[dict]
    ranking: list[str]
    ties: list[list[str]]
    selected: str | None
    status: str  # selected | all_infeasible
    label: str
    escalation: dict | None = None
    plan_for_now: dict | None = None
    floor_relaxed: bool = False
    reservation_raided: bool = False

    def with_plan(self, plan: dict | None) -> DecisionResult:
        if plan is not None and self.status != "selected":
            raise ValueError("no plan is offered when every policy is infeasible")
        return replace(self, plan_for_now=plan)

    def as_dict(self) -> dict:
        out = {k: getattr(self, k) for k in (
            "run_id", "checkpoint", "scenarios", "policies", "ranking", "ties", "selected",
            "status", "plan_for_now", "label", "floor_relaxed", "reservation_raided")}
        if self.escalation is not None:
            out["escalation"] = self.escalation
        return out


def _earliest_unmet(policy: str, evals: list[Evaluation]) -> dict | None:
    found = []
    for e in evals:
        f = e.feasibility
        for o in f.unmet:
            found.append(((o.due_h, 0), {"kind": "obligation", "id": o.id, "due_h": o.due_h,
                                         "short_minor": o.short_minor, "scenario": e.scenario}))
        if f.breached:
            found.append(((f.floor.breach_h[0], 1), {
                "kind": "reserve_floor", "account": f.account, "at_h": f.floor.breach_h[0],
                "short_minor": f.floor.short_minor, "scenario": e.scenario}))
    if not found:
        return None
    _, earliest = min(found, key=lambda x: x[0])
    return {**earliest, "under": f"{policy} (best ranked)"}


def _binding(earliest: dict, evals: list[Evaluation], tried: list[Evaluation],
             currency: str) -> str:
    """What binds: a remedy the world refused (``tried``, best ranked first) names its own
    constraint; else the cash short of the best-ranked policy's earliest unmet constraint."""
    refused = [(c, {i["intent_id"]: i.get("params", {}) for i in e.intents}
                .get(c["intent_id"], {}))
               for e in tried for c in e.c2
               if c.get("status") == "rejected" and c.get("binding")]
    for c, p in refused:  # a refused draw first: it is the remedy that would have closed it
        if p.get("facility_id") and p.get("amount"):
            return (f"{c['binding']} < {p['facility_id']} principal "
                    f"{grouped(p['amount']['minor'], p['amount']['currency'])}")
    if refused:
        return str(refused[0][0]["binding"])
    e = next(e for e in evals if e.scenario == earliest["scenario"])
    if earliest["kind"] == "obligation":
        o = next(o for o in e.feasibility.obligations if o.id == earliest["id"])
        owed = f"{o.id} {grouped(o.amount_minor, currency)}"
        if o.overdue_h is not None:  # outstanding past its deadline at the checkpoint
            owed += f" overdue since t={o.due_h}"
            if not o.short_minor:
                return f"{owed}, paid after the checkpoint"
        at_h = o.due_h if o.overdue_h is None else o.overdue_h
        return (f"free cash {grouped(o.amount_minor - o.short_minor, currency)} at "
                f"t={at_h}{_unknown(e.feasibility, at_h)} < {owed}; no reservation is touched")
    f = e.feasibility.floor
    return (f"min cash {grouped(f.min_cash, currency)} at t={f.at_h}"
            f"{_unknown(e.feasibility, f.at_h)} < floor "
            f"{grouped(f.min_cash + f.short_minor, currency)}; no remedy closed it")


def _unknown(f: Feasibility, h: int) -> str:
    """Says so when hour ``h`` fell in a round that ended unknown: the shortfall is what could
    not be used, not what the ledger held."""
    return " (balance unknown)" if f.unknown_at(h) else ""


def rank(evaluations: Sequence[Evaluation], *, order: Sequence[str] | None = None,
         run_id: str = "", checkpoint: dict | None = None, escalate_to: str | None = None,
         currency: str = "USD") -> DecisionResult:
    """Rank the policies of ``evaluations``; every policy must cover the same scenarios."""
    order = list(order or dict.fromkeys(e.policy for e in evaluations))
    scenarios = list(dict.fromkeys(e.scenario for e in evaluations))
    by_policy: dict[str, list[Evaluation]] = {p: [] for p in order}
    for e in evaluations:
        if e.policy not in by_policy:
            raise ValueError(f"{e.policy} is not in the declared order {order}")
        by_policy[e.policy].append(e)
    for policy, evals in by_policy.items():
        if sorted(e.scenario for e in evals) != sorted(scenarios):
            raise ValueError(f"{policy} was not evaluated once on every scenario {scenarios}")
        evals.sort(key=lambda e: scenarios.index(e.scenario))
    keys = {p: policy_key([e.feasibility for e in evals]) for p, evals in by_policy.items()}
    ranking = sorted(order, key=lambda p: (keys[p], order.index(p)))  # stable on equal keys
    groups: dict[tuple, list[str]] = {}
    for p in ranking:
        groups.setdefault(keys[p], []).append(p)
    ties = [g for g in groups.values() if len(g) > 1]
    feasible = {p: all(e.feasibility.feasible for e in evals) for p, evals in by_policy.items()}
    selected = next((p for p in ranking if feasible[p]), None)
    policies = [{"id": p, "branches": [e.row() for e in by_policy[p]],
                 "key": list(keys[p]), "feasible": feasible[p]} for p in order]
    common = {"run_id": run_id, "checkpoint": dict(checkpoint or {}), "scenarios": scenarios,
              "policies": policies, "ranking": ranking, "ties": ties}
    if selected is not None:
        return DecisionResult(
            **common, selected=selected, status="selected",
            label=(f"{selected} keeps every obligation and the floor on {len(scenarios)} "
                   f"scenario{'s' if len(scenarios) != 1 else ''}; a decision, not an approval"))
    best = ranking[0]
    earliest = _earliest_unmet(best, by_policy[best])
    nowhere = sum(1 for s in scenarios
                  if not any(e.feasibility.feasible for e in evaluations if e.scenario == s))
    return DecisionResult(
        **common, selected=None, status="all_infeasible",
        escalation={"earliest_unmet": earliest,
                    "binding": _binding(earliest, by_policy[best],
                                        [e for p in ranking for e in by_policy[p]], currency),
                    "escalate_to": escalate_to},
        label=(f"no feasible plan on {nowhere} scenario{'s' if nowhere != 1 else ''}; "
               "nothing can be approved from this run"))
