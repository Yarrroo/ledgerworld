"""Executable reference model of the agent tool boundary (system brief 7.1, 8 C1).

Stdlib only. It is the oracle the product implementation (T07, on OASIS) is checked
against for the g2 check "actions only through tools":

- build_observation: what one actor may see at simulated time t, and its obs_hash
  (sha256 of canonical JSON: sorted keys, no whitespace, integer minor units,
  ISO-8601 UTC times).
- gate_tool_call: a tool call is accepted only if the tool is in the actor's
  mandate and its arguments match the tool's schema; money is an int, never rounded.
- guard_model_output: one structured repair attempt, then no_action plus an alert.
  It never raises on model output, so a malformed answer is never a round failure.

Nothing here touches a ledger: an accepted call becomes a C1 ActionIntent, nothing more.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

# The simulated clock has no calendar date in the brief; the epoch is an explicit input.
DEFAULT_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Which world-item kinds each scope entry of actors.json `sees` admits, and whether the
# item must belong to the actor ("owner") or be addressed to it ("to").
SCOPE_RULES = {
    "own_accounts": ({"account", "own_account"}, "owner"),
    "own_contracts": ({"contract", "own_contract"}, "owner"),
    "messages_to_me": ({"message"}, "to"),
    "public_posts": ({"public_post", "scheduled_event"}, None),
    "public_prices": ({"public_price"}, None),
    "memory": ({"memory"}, "owner"),
}

MONEY_ARGS = {"amount_minor": int, "currency": str}

# Argument schemas: name -> (required {arg: type}, optional {arg: type}).
TOOL_SCHEMAS = {
    "request_advance": ({**MONEY_ARGS, "from": str}, {}),
    "offer": ({**MONEY_ARGS, "to": str}, {}),
    "accept": ({}, {"intent_id": str, "facility_id": str}),
    "disburse": ({**MONEY_ARGS, "to": str}, {"facility_id": str}),
    "repay": ({**MONEY_ARGS, "to": str}, {}),
    "convert": ({**MONEY_ARGS, "to_currency": str}, {}),
    "pay": ({**MONEY_ARGS, "to": str}, {}),
    "pledge": (MONEY_ARGS, {"account": str}),
    "release": ({}, {"facility_id": str, "account": str}),
    "defer": ({}, {"obligation_id": str, "until_h": int}),
    "create_post": ({"content": str}, {}),
    "no_action": ({}, {}),
}


class ToolRefusal(Exception):
    """A tool call that cannot become an intent. `reason` is the alert reason."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def iso_utc(sim_time_h: int, epoch: datetime = DEFAULT_EPOCH) -> str:
    return (epoch + timedelta(hours=sim_time_h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(value) -> str:
    """Sorted keys, no whitespace; a float anywhere is refused (money is integer minor units)."""

    def check(v):
        if isinstance(v, float):
            raise ValueError(f"float in canonical payload: {v!r}")
        if isinstance(v, dict):
            for x in v.values():
                check(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                check(x)

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def visible(item: dict, actor: dict, sim_time_h: int) -> bool:
    """True if `item` is inside `actor`'s scope at `sim_time_h`. Unknown kinds fail closed."""
    if item.get("visible_from_h", 0) > sim_time_h:
        return False
    for scope in actor.get("sees", []):
        kinds, bound = SCOPE_RULES.get(scope, (set(), None))
        if item.get("kind") not in kinds:
            continue
        if bound is None or item.get(bound) == actor["actor_id"]:
            return True
    return False


def build_observation(actor: dict, world_items: list, round_: int, sim_time_h: int,
                      epoch: datetime = DEFAULT_EPOCH):
    """-> (observation, obs_hash, evidence_ids). Items are ordered by id, so input order is irrelevant."""
    items = sorted((i for i in world_items if visible(i, actor, sim_time_h)), key=lambda i: i["id"])
    observation = {
        "actor_id": actor["actor_id"],
        "round": round_,
        "t": iso_utc(sim_time_h, epoch),
        "items": items,
    }
    obs_hash = hashlib.sha256(canonical_json(observation).encode("utf-8")).hexdigest()
    return observation, obs_hash, [i["id"] for i in items]


def check_args(name: str, args) -> dict:
    """Validate `args` against the tool schema; returns them unchanged. Raises ToolRefusal."""
    required, optional = TOOL_SCHEMAS[name]
    if not isinstance(args, dict):
        raise ToolRefusal("malformed_tool_args", f"{name}: arguments must be an object")
    errors = []
    for arg in sorted(set(args) - set(required) - set(optional)):
        errors.append(f"unexpected argument '{arg}'")
    for arg in sorted(set(required) - set(args)):
        errors.append(f"missing required argument '{arg}' ({required[arg].__name__})")
    for arg, typ in {**required, **optional}.items():
        if arg not in args:
            continue
        value = args[arg]
        # bool is an int subclass and 1200000.0 is not an int: neither is money.
        if not isinstance(value, typ) or isinstance(value, bool):
            errors.append(f"'{arg}' must be {typ.__name__}, got {type(value).__name__} {value!r}")
        elif arg == "amount_minor" and value <= 0:
            errors.append(f"'amount_minor' must be positive, got {value}")
    if errors:
        raise ToolRefusal("malformed_tool_args", f"{name}: " + "; ".join(errors))
    return args


def gate_tool_call(actor: dict, call: dict) -> dict:
    """Refuse a tool outside the actor's mandate, then check its arguments. -> args."""
    name = call.get("name") if isinstance(call, dict) else None
    if name not in actor.get("tools", []) or name not in TOOL_SCHEMAS:
        raise ToolRefusal("tool_not_in_mandate",
                          f"'{name}' is not one of {actor['actor_id']}'s tools {actor.get('tools', [])}")
    return check_args(name, call.get("args"))


def repair_prompt(refusal: ToolRefusal, actor: dict) -> str:
    """The single repair request: names the schema error and the tools the actor may use."""
    schemas = {
        t: {"required": {a: ty.__name__ for a, ty in TOOL_SCHEMAS[t][0].items()},
            "optional": {a: ty.__name__ for a, ty in TOOL_SCHEMAS[t][1].items()}}
        for t in actor.get("tools", []) if t in TOOL_SCHEMAS
    }
    return (f"Your tool call was refused ({refusal.reason}): {refusal.detail}. "
            f"Answer with exactly one call matching one of these schemas; money is "
            f"amount_minor, an integer in minor units: {canonical_json(schemas)}")


def make_intent(actor_id: str, round_: int, n: int, type_: str, params: dict,
                obs_hash: str, evidence_ids: list, branch_id: str = "main") -> dict:
    """A C1 ActionIntent; the id is i-r<round>-<actor_id>-<n>."""
    return {
        "intent_id": f"i-r{round_}-{actor_id}-{n}",
        "branch_id": branch_id,
        "round": round_,
        "actor_id": actor_id,
        "type": type_,
        "params": dict(params),
        "evidence_ids": list(evidence_ids),
        "obs_hash": obs_hash,
    }


def guard_model_output(actor: dict, first: dict, ask_repair, round_: int, obs_hash: str,
                       evidence_ids: list, n: int = 1, branch_id: str = "main") -> dict:
    """One repair attempt, then no_action + alert. `ask_repair(prompt) -> call` is called at most once.

    -> {intent, repair_attempts, alert, alert_reason, repair_prompt}. Never raises on model output.
    """
    def accept(call, attempts, prompt):
        args = gate_tool_call(actor, call)
        intent = make_intent(actor["actor_id"], round_, n, call["name"], args, obs_hash,
                             evidence_ids, branch_id)
        return {"intent": intent, "repair_attempts": attempts, "alert": False,
                "alert_reason": None, "repair_prompt": prompt}

    try:
        return accept(first, 0, None)
    except ToolRefusal as refusal:
        prompt = repair_prompt(refusal, actor)
    try:
        return accept(ask_repair(prompt), 1, prompt)
    except ToolRefusal as refusal:
        final = refusal
    intent = make_intent(actor["actor_id"], round_, n, "no_action", {}, obs_hash, evidence_ids, branch_id)
    return {"intent": intent, "repair_attempts": 1, "alert": True,
            "alert_reason": final.reason, "repair_prompt": prompt}
