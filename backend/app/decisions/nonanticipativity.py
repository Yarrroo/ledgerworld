"""Nonanticipativity: a decision at round r reads only what is observable at t = 4r h (§9, g1).

Two guards (design/modules/decisions/HANDOFF.md, fixture `nonanticipativity.json`):

- `PolicyView`, a read-only view over a world whose every leaf carries `available_at`. A read of a
  leaf not yet available at t, or of one that is never observable (scenario parameters, scheduled
  future events, the rng, another branch), raises `AnticipationViolation` naming the path. The
  violation is also kept on the view, so a policy that catches it is rejected all the same.
- `paired_history_check`, which runs a policy over every scenario of a tree: two scenarios whose
  observable histories (the hash of the full view each round) are equal through round r must get
  equal decisions at r. It catches a policy that reaches the future without touching the view.
  `check_pairs` is its comparison; `candidates.evaluate` runs it over each policy's branches too.

A world is a flat mapping from a dotted path (ids in brackets,
`accounts[borrower-a/operating].pending_in[rcv-1].expected_h`) to a `Leaf`: the values the leaf
takes, each with the hour it becomes observable. `snapshot_world` builds one from a C5 snapshot,
every leaf observable from its `as_of` (t = 0).
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations
from types import MappingProxyType
from typing import Any, Literal

from app.finance.schemas import Snapshot

HOURS_PER_ROUND = 4
NEVER: Literal["never"] = "never"

Hour = int | Literal["never"]


class AnticipationViolation(Exception):
    """A policy used information not observable when it decided.

    A view read names `path`, `read_at_h` and `available_at_h`; a side channel caught by the
    paired-history check names `node = {round, scenarios}` and leaves `path` None.
    """

    def __init__(self, reason: str, *, path: str | None = None, read_at_h: int | None = None,
                 available_at_h: Hour | None = None, node: dict | None = None) -> None:
        self.reason = reason
        self.path = path
        self.read_at_h = read_at_h
        self.available_at_h = available_at_h
        self.node = node
        where = f"path {path}" if path is not None else f"node {node}"
        super().__init__(f"{reason}: {where}")

    @classmethod
    def early_read(cls, path: str, read_at_h: int, available_at_h: Hour) -> AnticipationViolation:
        return cls(f"read at t={read_at_h} h of a leaf available at {available_at_h}", path=path,
                   read_at_h=read_at_h, available_at_h=available_at_h)

    @classmethod
    def side_channel(cls, round_: int, scenarios: list[str],
                     policy: str | None = None) -> AnticipationViolation:
        node: dict = {"round": round_, "scenarios": scenarios}
        if policy is not None:
            node["policy"] = policy
        return cls("decisions differ on identical observable history", node=node)


@dataclass(frozen=True, slots=True)
class Leaf:
    """One observable quantity: `(available_at_h, value)` versions in strictly rising hours.

    No version means never observable. A read at t sees the latest version with hour <= t.
    """

    versions: tuple[tuple[int, Any], ...] = ()

    def __post_init__(self) -> None:
        hours = [h for h, _ in self.versions]
        if any(type(h) is not int or h < 0 for h in hours) or hours != sorted(set(hours)):
            raise ValueError(f"leaf hours must be whole, >= 0 and strictly rising: {hours}")

    @classmethod
    def at(cls, available_at_h: int, value: Any) -> Leaf:
        return cls(((available_at_h, value),))

    @classmethod
    def never(cls) -> Leaf:
        return cls()

    def then(self, available_at_h: int, value: Any) -> Leaf:
        """This leaf, taking `value` from `available_at_h` on."""
        return Leaf((*self.versions, (available_at_h, value)))

    @property
    def available_at_h(self) -> Hour:
        return self.versions[0][0] if self.versions else NEVER

    def visible_at(self, t_h: int) -> tuple[bool, Any]:
        for h, value in reversed(self.versions):
            if h <= t_h:
                return True, value
        return False, None


World = Mapping[str, Leaf]


def canonical(value: Any) -> str:
    """The canonical JSON both guards compare and hash; a value JSON cannot hold is refused."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def under(path: str, prefix: str) -> bool:
    """True when `path` is `prefix` or a leaf inside it (segment-aligned, never mid-id)."""
    return not prefix or path == prefix or path.startswith((prefix + ".", prefix + "["))


class PolicyView:
    """The world at round r as a policy may see it: read-only, every read recorded."""

    __slots__ = ("_leaves", "_reads", "_round", "_violations")

    def __init__(self, world: World, round_: int) -> None:
        if type(round_) is not int or round_ < 0:
            raise ValueError(f"round must be a whole number >= 0, got {round_!r}")
        self._leaves = MappingProxyType(dict(world))
        self._round = round_
        self._reads: list[str] = []
        self._violations: list[AnticipationViolation] = []

    @property
    def round(self) -> int:
        return self._round

    @property
    def t_h(self) -> int:
        return self._round * HOURS_PER_ROUND

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        """The paths read, first read first; they become the C1 intent's `evidence_ids`."""
        return tuple(self._reads)

    @property
    def violations(self) -> tuple[AnticipationViolation, ...]:
        return tuple(self._violations)

    def get(self, path: str) -> Any:
        """The value at `path` as observable now (a copy); an early read raises."""
        leaf = self._leaves.get(path)
        if leaf is None:
            raise KeyError(path)
        visible, value = leaf.visible_at(self.t_h)
        if not visible:
            violation = AnticipationViolation.early_read(path, self.t_h, leaf.available_at_h)
            self._violations.append(violation)
            raise violation
        if path not in self._reads:
            self._reads.append(path)
        return copy.deepcopy(value)

    def paths(self, prefix: str = "") -> list[str]:
        """The observable leaf paths under `prefix`; a leaf not yet observable is not listed."""
        return sorted(p for p, _ in self._observable() if under(p, prefix))

    def obs_hash(self) -> str:
        """sha256 of the full observation at t: the history the paired check compares."""
        observation = {path: value for path, value in self._observable()}
        return hashlib.sha256(canonical(observation).encode()).hexdigest()

    def _observable(self) -> Iterator[tuple[str, Any]]:
        for path, leaf in self._leaves.items():
            visible, value = leaf.visible_at(self.t_h)
            if visible:
                yield path, value


Policy = Callable[[PolicyView], list] | Any  # a callable, or an object with `decide(view)`


@dataclass(frozen=True, slots=True)
class Decision:
    """What a policy decided at one round, what it read and what it could see."""

    round: int
    t_h: int
    actions: list
    evidence_ids: tuple[str, ...]
    obs_hash: str


def guarded_decide(policy: Policy, world: World, round_: int) -> Decision:
    """Run `policy` on the guarded view of `world` at `round_`; any early read rejects it."""
    decide = getattr(policy, "decide", policy)
    view = PolicyView(world, round_)
    obs_hash = view.obs_hash()  # taken before the policy can touch the view
    try:
        actions = decide(view)
    except AnticipationViolation:
        raise
    except Exception as exc:
        if view.violations:
            raise view.violations[0] from exc
        raise
    if view.violations:
        raise view.violations[0]
    if not isinstance(actions, list):
        raise TypeError(f"a policy returns a list of actions, got {type(actions).__name__}")
    canonical(actions)
    return Decision(round_, round_ * HOURS_PER_ROUND, actions, view.evidence_ids, obs_hash)


@dataclass(frozen=True, slots=True)
class ScenarioTree:
    """Scenarios forked from one checkpoint, each a world, decided on at rounds 0..rounds-1."""

    scenarios: Mapping[str, World]
    rounds: int


def observable_histories(tree: ScenarioTree) -> dict[str, list[str]]:
    """Per scenario, the hash of the full view at each round."""
    return {sid: [PolicyView(world, r).obs_hash() for r in range(tree.rounds)]
            for sid, world in tree.scenarios.items()}


def paired_history_check(policy: Policy, tree: ScenarioTree) -> dict[str, list[Decision]]:
    """Every decision of `policy` on `tree`, once both guards pass.

    Raises `AnticipationViolation`: with the path for the first early read (scenarios in tree
    order, rounds rising), else with the first round and scenario pair whose observable
    histories are equal through that round while their decisions at it differ. The histories
    come from the tree itself, never from what a policy's run reports.
    """
    seen = observable_histories(tree)
    decisions = {sid: [guarded_decide(policy, world, r) for r in range(tree.rounds)]
                 for sid, world in tree.scenarios.items()}
    check_pairs(seen, {sid: [d.actions for d in ds] for sid, ds in decisions.items()})
    return decisions


def check_pairs(histories: Mapping[str, list[str]], actions: Mapping[str, list[list]],
                rounds: list[int] | None = None, *, policy: str | None = None) -> None:
    """Raise `AnticipationViolation` at the first round (rising, then scenario pairs in order)
    where two scenarios' observable histories are equal through it and one policy's decisions
    at it differ. ``histories[sid][i]`` is the view's hash at the i-th decision, taken before
    the policy saw it; ``rounds[i]`` names that decision's round (``i`` by default)."""
    acted = {sid: [canonical(a) for a in ds] for sid, ds in actions.items()}
    for i in range(max((len(h) for h in histories.values()), default=0)):
        for a, b in combinations(histories, 2):
            if i < min(len(acted[a]), len(acted[b])) \
                    and histories[a][: i + 1] == histories[b][: i + 1] \
                    and acted[a][i] != acted[b][i]:
                raise AnticipationViolation.side_channel(
                    rounds[i] if rounds is not None else i, [a, b], policy=policy)


# ----------------------------------------------------------------------- the C5 snapshot as a world

_ITEM_KEYS = {
    "entities": "entity_id", "accounts": "id", "obligations": "obligation_id",
    "contracts": "contract_id", "exposures": "exposure_id", "pools": "entity",
    "pending_in": "flow_id", "pending_out": "flow_id",
}


def _hours(when: datetime, t0: datetime) -> int:
    hours, rest = divmod(when - t0, timedelta(hours=1))
    if rest:
        raise ValueError(f"{when.isoformat()} is not a whole hour from the snapshot's as_of")
    return hours


def snapshot_world(snapshot: Snapshot) -> dict[str, Leaf]:
    """The observed snapshot as a world, every leaf available at t = 0.

    Lists of records are keyed by their id (`accounts[<id>]`), an account's buckets sit on the
    account, money stays one leaf `{minor, currency}`, a time `<x>_at` (or `as_of`) becomes
    `<x>_h` (`as_of_h`) in whole hours from the snapshot's `as_of`, and a pending inflow carries
    `status = "expected"`, which the round coordinator moves on to `overdue` or `arrived`. An
    account observed after the snapshot's `as_of` is refused: it would be read before it was seen.
    """
    t0 = snapshot.as_of
    for account in snapshot.accounts:
        if account.as_of > t0:
            raise ValueError(f"account {account.id} is observed at {account.as_of.isoformat()}, "
                             "after the snapshot's as_of")
    leaves: dict[str, Leaf] = {}

    def walk(path: str, value: Any, list_name: str | None = None) -> None:
        if isinstance(value, dict) and set(value) != {"minor", "currency"}:
            for key, item in value.items():
                if key == "buckets":
                    walk(path, item)
                    continue
                if isinstance(item, datetime):
                    key = "as_of_h" if key == "as_of" else key.removesuffix("_at") + "_h"
                    item = _hours(item, t0)
                walk(f"{path}.{key}" if path else key, item, key)
            if list_name == "pending_in":
                leaves[f"{path}.status"] = Leaf.at(0, "expected")
        elif isinstance(value, list) and list_name in _ITEM_KEYS:
            for item in value:
                walk(f"{path}[{item[_ITEM_KEYS[list_name]]}]", item, list_name)
        else:
            leaves[path] = Leaf.at(0, value)

    walk("", snapshot.model_dump(mode="python"))
    return leaves
