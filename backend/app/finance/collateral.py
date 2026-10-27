"""The collateral facility's borrowing base (system brief §15; decisions HANDOFF `borrowing_base`).

Simulation and tests only: nothing under ``app.execution`` or ``app.connectors`` imports this
module, no route serves it and no leg kind names it. A draw against it is a check, never a leg.

    after haircut  = floor(value × (10000 − haircut_bps) / 10000)       per eligible lot
    pre-limit      = Σ after haircut
    borrowing base = pre-limit − obligor cut − type cut

The concentration limits are one pass, both measured on the pre-limit total: each obligor is
cut to ``per_obligor_bps`` of it first, then each limited asset type to ``per_type_bps`` of it,
on what of that type the obligor cuts left (an obligor's cut is shared across its types in
proportion, the units the rounding leaves going to the largest fractions, ties in lot order, so
its types keep exactly what it kept). A lot of an
ineligible type, one already pledged to another facility, one whose value is unknown and one
older than ``STALE_AFTER`` add nothing; unknown and stale also set ``authority = reduced``.
Every number is an integer in minor units; every rounding is down.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import STALE_AFTER, LedgerRefusal
from .spendability import Authority, grouped
from .store import LedgerStore

__all__ = ["DEFAULT_ELIGIBLE", "BorrowingBase", "borrowing_base", "draw", "pledge_lot"]

BPS = 10_000
DEFAULT_ELIGIBLE = ("receivable", "stablecoin")


@dataclass(frozen=True)
class BorrowingBase:
    after_haircut: dict[str, int]  # lot_id -> value after its haircut, eligible lots only
    excluded: dict[str, str]  # lot_id -> ineligible_type | already_pledged | unknown | stale
    pre_limit: int
    obligor_cut: dict[str, int]
    type_cut: dict[str, int]
    borrowing_base: int
    authority: Authority
    currency: str = "USD"

    def as_dict(self) -> dict:
        return {"after_haircut": dict(self.after_haircut), "excluded": dict(self.excluded),
                "pre_limit": self.pre_limit, "obligor_cut": dict(self.obligor_cut),
                "type_cut": dict(self.type_cut), "borrowing_base": self.borrowing_base,
                "authority": self.authority}


def _when(value: datetime | str) -> datetime:
    when = datetime.fromisoformat(value) if isinstance(value, str) else value
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _minor(value: Any, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{what} must be an integer >= 0 in minor units, not {value!r}")
    return value


def _bps(value: Any, what: str) -> int:
    if _minor(value, what) > BPS:
        raise ValueError(f"{what} must be at most {BPS} bps, not {value!r}")
    return value


def _exclusion(lot: Mapping[str, Any], eligible: Iterable[str], now: datetime,
               stale_after: timedelta, facility: str | None) -> str | None:
    if lot["type"] not in eligible:
        return "ineligible_type"
    if lot.get("pledged_to") not in (None, facility):
        return "already_pledged"
    if lot.get("value") is None or lot.get("as_of") is None:
        return "unknown"  # unknown is not zero: it is absent
    if now - _when(lot["as_of"]) > stale_after:
        return "stale"
    return None


def borrowing_base(lots: Iterable[Mapping[str, Any]], limits: Mapping[str, Any],
                   now: datetime | str, *, eligible_types: Iterable[str] = DEFAULT_ELIGIBLE,
                   stale_after: timedelta = STALE_AFTER, facility: str | None = None,
                   currency: str = "USD") -> BorrowingBase:
    """The borrowing base of ``lots`` at ``now`` under ``limits`` (``per_obligor_bps``,
    ``per_type_bps{type: bps}``). A lot pledged to ``facility`` itself still counts."""
    now, eligible = _when(now), tuple(eligible_types)
    after: dict[str, int] = {}
    excluded: dict[str, str] = {}
    by_obligor: dict[str, dict[str, int]] = {}  # obligor -> type -> after haircut
    for lot in lots:
        lot_id = lot["lot_id"]
        if lot_id in after or lot_id in excluded:
            raise ValueError(f"lot {lot_id} appears twice")
        why = _exclusion(lot, eligible, now, stale_after, facility)
        if why is not None:
            excluded[lot_id] = why
            continue
        value = _minor(lot["value"], f"{lot_id} value")
        haircut = _bps(lot["haircut_bps"], f"{lot_id} haircut")
        after[lot_id] = value * (BPS - haircut) // BPS
        types = by_obligor.setdefault(lot.get("obligor") or lot_id, {})
        types[lot["type"]] = types.get(lot["type"], 0) + after[lot_id]
    pre = sum(after.values())

    obligor_bps = _bps(limits.get("per_obligor_bps", BPS), "per_obligor_bps")
    obligor_cap = pre * obligor_bps // BPS
    obligor_cut: dict[str, int] = {}
    kept_by_type: dict[str, int] = {}
    for obligor, types in by_obligor.items():
        held = sum(types.values())
        cut = max(0, held - obligor_cap)
        if cut:
            obligor_cut[obligor] = cut
        shares = {kind: cut * amount // held for kind, amount in types.items()} if held else {}
        for kind in sorted(shares, key=lambda k: -(cut * types[k] % held))[
                :cut - sum(shares.values())]:
            shares[kind] += 1
        for kind, amount in types.items():
            kept_by_type[kind] = kept_by_type.get(kind, 0) + amount - shares.get(kind, 0)

    type_cut: dict[str, int] = {}
    for kind, bps in (limits.get("per_type_bps") or {}).items():
        cut = max(0, kept_by_type.get(kind, 0) - pre * _bps(bps, f"{kind} limit") // BPS)
        if cut:
            type_cut[kind] = cut

    reduced = any(why in ("unknown", "stale") for why in excluded.values())
    return BorrowingBase(after, excluded, pre, obligor_cut, type_cut,
                         pre - sum(obligor_cut.values()) - sum(type_cut.values()),
                         "reduced" if reduced else "full", currency)


def draw(base: BorrowingBase, amount_minor: int, *, drawn_minor: int = 0) -> dict:
    """A simulated draw of ``amount_minor`` on top of ``drawn_minor`` already outstanding:
    accepted within the borrowing base, else rejected naming it. A base resting on unknown or
    stale lots says ``authority: reduced`` beside the answer. Never a leg."""
    amount = _minor(amount_minor, "a draw")
    if amount == 0:
        raise ValueError("a draw moves a positive amount")
    headroom = base.borrowing_base - _minor(drawn_minor, "drawn")
    if amount > headroom:
        out = {"status": "rejected", "reason": "beyond_borrowing_base",
               "binding": f"borrowing base = {grouped(base.borrowing_base, base.currency)}"}
    else:
        out = {"status": "accepted", "headroom_after": headroom - amount}
    return out if base.authority == "full" else {**out, "authority": base.authority}


def pledge_lot(store: LedgerStore, account_id: str, lot: Mapping[str, Any],
               facility_id: str) -> dict:
    """Pledge ``lot`` to ``facility_id`` in the ledger. The ledger's one-active-pledge-per-ref
    index refuses the same lot twice, whatever the facility. A lot of unknown value is refused
    (``unknown``): nothing observed says what would be pledged."""
    if lot.get("value") is None:
        return {"status": "rejected", "reason": "unknown"}
    try:
        pledge_id = store.pledge(account_id, _minor(lot["value"], f"{lot['lot_id']} value"),
                                 lot["lot_id"], facility_id=facility_id)
    except LedgerRefusal as refusal:
        return {"status": "rejected", "reason": refusal.code}
    return {"status": "accepted", "pledge_id": pledge_id}
