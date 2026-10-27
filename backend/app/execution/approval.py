"""Approval binding (C3): a plan becomes money only as a bound approval, once.

`bind` fixes a plan's terms to one observed snapshot, one mode and a lifetime, and stamps them
with `plan_hash` = sha256 of the canonical JSON (sorted keys, no spaces) of
`{entity, account, legs, snapshot_id, mode}`; a leg is its C3 shape with defaulted fields left
out, so a field added to the contract later does not move the hash of an existing approval.
`verify` is the gateway's check before anything is written: any term outside the bound refuses
the whole approval (design/modules/execution/HANDOFF.md, `fixtures/approval-binding.json`).

This module holds the binding-level refusals, which need nothing but the approval itself:
`not_an_approval`, `not_observed_snapshot`, `approval_altered`, `approval_used`,
`approval_expired`, `mode_mismatch` and `snapshot_moved`. The ledger-backed ones (ownership,
the beneficiary allowlist, the held reservation, stale or unknown balances, the floor and
spendable cash) are the gateway's preflight and extend `verify` with the ledger's view.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar, Literal

from app.finance.schemas import ApprovalLeg, BoundApproval, Mode, Snapshot
from pydantic import ValidationError

TTL = timedelta(minutes=15)
# A branch store names its snapshots with this prefix; execution refuses anything so named.
BRANCH_PREFIX = "branch-"

RefusalCode = Literal[
    "approval_altered", "approval_expired", "approval_used", "mode_mismatch",
    "not_observed_snapshot", "snapshot_moved", "unowned_funds", "beneficiary_not_allowed",
    "reservation_mismatch", "stale_balance", "unknown_balance", "breaks_floor",
    "insufficient_spendable", "not_an_approval",
]


@dataclass(frozen=True)
class Ok:
    """The approval may execute: every term is inside the bound."""

    ok: ClassVar[bool] = True


@dataclass(frozen=True)
class Refusal:
    """The whole approval is refused; nothing moves and no outbox row is written."""

    code: RefusalCode
    detail: str
    ok: ClassVar[bool] = False


OK = Ok()


def is_observed_snapshot(snapshot_id: str) -> bool:
    """Execution reads the observed state, never a branch's."""
    return not snapshot_id.startswith(BRANCH_PREFIX)


def plan_hash(
    *, entity: str, account: str, legs: Sequence[ApprovalLeg], snapshot_id: str, mode: str
) -> str:
    """sha256 of the canonical JSON of the terms an approval binds."""
    terms = {
        "entity": entity,
        "account": account,
        "legs": [leg.model_dump(mode="json", exclude_defaults=True) for leg in legs],
        "snapshot_id": snapshot_id,
        "mode": mode,
    }
    canonical = json.dumps(terms, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _terms_hash(approval: BoundApproval) -> str:
    return plan_hash(entity=approval.entity, account=approval.account, legs=approval.legs,
                     snapshot_id=approval.snapshot_id, mode=approval.mode)


def request_id(approval: BoundApproval, leg: ApprovalLeg) -> str:
    """A leg's provider `request_id`: fixed by the binding, never changed on retry."""
    return f"{approval.plan_hash[:12]}-{leg.index}-{leg.kind}"


def bind(
    plan: Mapping[str, Any],
    snapshot: Snapshot | str,
    approver: str,
    mode: Mode,
    ttl: timedelta = TTL,
    *,
    now: datetime,
    approval_id: str | None = None,
) -> BoundApproval:
    """Bind a plan (`{entity, account, legs}`, decided on the observed snapshot) into C3.

    Raises `ValueError` for a branch's snapshot or a lifetime that is not positive; a plan
    that breaks the C3 contract raises pydantic's `ValidationError`.
    """
    snapshot_id = snapshot if isinstance(snapshot, str) else snapshot.snapshot_id
    if not is_observed_snapshot(snapshot_id):
        raise ValueError(f"not_observed_snapshot: {snapshot_id} is a branch's snapshot")
    if ttl <= timedelta(0):
        raise ValueError("an approval's lifetime is positive")
    legs = [ApprovalLeg.model_validate(leg) for leg in plan["legs"]]
    digest = plan_hash(entity=plan["entity"], account=plan["account"], legs=legs,
                       snapshot_id=snapshot_id, mode=mode)
    return BoundApproval(
        approval_id=approval_id or f"apr-{digest[:12]}",
        entity=plan["entity"],
        account=plan["account"],
        legs=legs,
        plan_hash=digest,
        snapshot_id=snapshot_id,
        expires_at=now + ttl,
        mode=mode,
        approver=approver,
    )


def _as_approval(value: object) -> BoundApproval | None:
    if isinstance(value, BoundApproval):
        return value
    if isinstance(value, Mapping):
        try:
            return BoundApproval.model_validate(value)
        except ValidationError:
            return None
    return None


def verify(
    approval: object,
    presented: object,
    now: datetime,
    current_snapshot_id: str,
    gateway_mode: Mode,
    *,
    used: Collection[str] = (),
) -> Ok | Refusal:
    """Check `presented` against the stored `approval` before anything is written.

    `approval` is what `bind` returned and the store kept; `used` holds the ids of approvals
    that already executed. The first refusal found is returned.
    """
    stored, shown = _as_approval(approval), _as_approval(presented)
    if stored is None or shown is None:
        return Refusal("not_an_approval", "only a bound approval (C3) executes")
    for sid in (stored.snapshot_id, shown.snapshot_id, current_snapshot_id):
        if not is_observed_snapshot(sid):
            return Refusal("not_observed_snapshot", f"{sid} is a branch's snapshot")
    if stored.plan_hash != _terms_hash(stored):
        return Refusal("approval_altered", "the stored approval no longer matches its hash")
    if _terms_hash(shown) != stored.plan_hash:
        return Refusal("approval_altered", "the bound hash no longer matches the terms presented")
    changed = [f for f in BoundApproval.model_fields if getattr(shown, f) != getattr(stored, f)]
    if changed:
        return Refusal("approval_altered", f"terms outside the bound: {', '.join(changed)}")
    if stored.approval_id in used:
        return Refusal("approval_used", f"{stored.approval_id} already executed")
    if now >= stored.expires_at:
        return Refusal("approval_expired", f"expired at {stored.expires_at.isoformat()}")
    if stored.mode != gateway_mode:
        return Refusal("mode_mismatch", f"bound for {stored.mode}, gateway runs {gateway_mode}")
    if stored.snapshot_id != current_snapshot_id:
        return Refusal("snapshot_moved",
                       f"bound on {stored.snapshot_id}, observed is now {current_snapshot_id}")
    return OK
