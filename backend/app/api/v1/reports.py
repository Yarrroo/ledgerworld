"""GET /api/v1/reports/{run_id}: a run's report, every figure from the run's own results.

Each section is a set of signed structured results (`reports.grounded`) written out by the
template, so every number in its text is one of its figures and each figure names the run, branch
and round it came from. No model writes these sections, so the report says `scripted`.
"""

from __future__ import annotations

from typing import Any

from ...finance.schemas import Money
from ...jobs.runner import base_branch
from ...reports.grounded import ground, sign_result, template_draft


def _section(title: str, results: list[tuple[Any, dict, dict]]) -> dict:
    """``results``: (signed result, {figure: Metric}, source) triples of one section."""
    signed = [r for r, _, _ in results]
    text, _, problems = ground(template_draft(signed), signed)
    if problems:  # the template only places the figures it lists
        raise RuntimeError(f"report section {title!r} is not grounded: {problems}")
    figures = [{"label": f"{r.kind.replace('_', ' ')}: {name.replace('_', ' ')}",
                "value": value, "source": source}
               for r, values, source in results for name, value in values.items()]
    return {"title": title, "text": text, "figures": figures}


def _money(metric: dict) -> Money | None:
    if metric["status"] not in ("known", "stale") or metric["minor"] is None:
        return None
    return Money(minor=metric["minor"], currency=metric["currency"])


def report(run: dict, decisions: dict | None, *, key: bytes) -> dict:
    run_id = run["run_id"]
    sections = []
    base = next((p for p in run["cash_paths"] if p["branch_id"] == base_branch(run_id)), None)
    if base and base["points"]:
        first, last = base["points"][0], base["points"][-1]
        values = {k: m for k, m in (("opening_cash", first["value"]),
                                    ("cash_at_last_round", last["value"])) if _money(m)}
        if values:
            result = sign_result(f"{run_id}:cash", "treasury_cash",
                                 {k: _money(m) for k, m in values.items()}, key=key)
            source = {"run_id": run_id, "branch_id": base["branch_id"],
                      "round": run["committed_round"] or 0}
            sections.append(_section("Treasury cash", [(result, values, source)]))
    if decisions and decisions["status"] != "pending":
        triples = []
        for r in decisions["results"]:
            values = {"min_cash": r["min_cash"],
                      "funding_cost": {**r["funding_cost"], "status": "known"}}
            result = sign_result(f"{r['branch_id']}:outcome",
                                 r["policy"].replace("-", "_"),
                                 {k: _money(m) for k, m in values.items()}, key=key)
            triples.append((result, values, {"run_id": run_id, "branch_id": r["branch_id"],
                                             "round": decisions["checkpoint_round"]}))
        if triples:
            sections.append(_section("Policies on the same shocks", triples))
    return {"run_id": run_id, "snapshot_id": run["snapshot_id"], "model": "scripted",
            "replay": any(b["replay"] for b in run["branches"]), "sections": sections}
