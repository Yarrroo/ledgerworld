"""Contracts C1–C6 and the domain shapes (system brief §8, design/modules/ledger/HANDOFF.md).

The pydantic models here are the source; `contracts/*.schema.json` are generated from them with
`python -m app.finance.schemas` and a test fails when the two drift. Every rule a JSON Schema can
state is in both. Three kinds of rule live in the models only, because JSON Schema cannot state
them: equality across fields (a bucket's currency equals its account's, a receipt's request id
equals its leg's), references inside one document (an account's entity exists, a leg's `after`
names another leg), and `100.0` as an amount (JSON Schema counts it as an integer; `StrictInt`
refuses it).

Money is `{minor: int, currency: ISO-4217}` everywhere. `to_provider_decimal` is the one way to a
provider's decimal string.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)
from pydantic.json_schema import models_json_schema

# ---------------------------------------------------------------------------------------- money

Currency = Literal["USD", "EUR", "GBP", "JPY", "AUD", "HKD", "SGD", "CNY"]
EXPONENT: dict[str, int] = {
    "USD": 2, "EUR": 2, "GBP": 2, "JPY": 0, "AUD": 2, "HKD": 2, "SGD": 2, "CNY": 2,
}
assert set(EXPONENT) == set(get_args(Currency))

Id = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, StringConstraints(max_length=4000)]
Bps = Annotated[StrictInt, Field(ge=0, le=10000)]
Count = Annotated[StrictInt, Field(ge=0)]

type Param = StrictStr | StrictInt | StrictBool | None | list[Param] | dict[str, Param]
"""A JSON value with no float anywhere in it: a model's float never reaches a posting."""


class _Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Money(_Shape):
    """An amount in integer minor units of an ISO-4217 currency; signed inside the ledger."""

    minor: StrictInt
    currency: Currency


class Amount(Money):
    """A strictly positive amount: what an intent, a leg or an obligation moves."""

    minor: StrictInt = Field(gt=0)


class NonNegativeMoney(Money):
    """An amount that is zero or more: a reserved or pledged bucket, a floor, a fee."""

    minor: StrictInt = Field(ge=0)


def to_decimal(money: Money) -> str:
    """Minor units as a signed decimal string by the currency's exponent (USD 2, JPY 0)."""
    if not isinstance(money, Money):
        raise TypeError("to_decimal takes Money, never a bare number")
    exponent = EXPONENT[money.currency]
    sign = "-" if money.minor < 0 else ""
    whole, frac = divmod(abs(money.minor), 10**exponent)
    return f"{sign}{whole}.{frac:0{exponent}d}" if exponent else f"{sign}{whole}"


def to_provider_decimal(money: Money) -> str:
    """The provider request's decimal string; a negative amount is refused at this boundary."""
    if not isinstance(money, Money):
        raise TypeError("to_provider_decimal takes Money, never a bare number")
    if money.minor < 0:
        raise ValueError("negative amount at the provider boundary")
    return to_decimal(money)


# ----------------------------------------------------------------------------- C1 ActionIntent

IntentType = Literal[
    "request_advance", "offer", "accept", "disburse", "repay", "convert", "pay", "pledge",
    "release", "defer", "no_action",
]
MONEY_INTENTS = ("request_advance", "offer", "disburse", "repay", "convert", "pay", "pledge")


class IntentParams(_Shape):
    """An intent's arguments: `amount` is Money; any other argument is JSON with no float."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, Param] = Field(init=False)

    amount: Amount | None = None


class ActionIntent(_Shape):
    """C1: what an actor proposes in a round; a rejected or malformed one becomes `no_action`."""

    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"properties": {"type": {"enum": list(MONEY_INTENTS)}}, "required": ["type"]},
        "then": {"properties": {"params": {
            "required": ["amount"], "properties": {"amount": {"type": "object"}},
        }}},
    }]})

    intent_id: Id
    branch_id: Id
    round: StrictInt = Field(ge=0)
    actor_id: Id
    type: IntentType
    params: IntentParams
    evidence_ids: list[Id]
    obs_hash: Sha256
    priority_class: Annotated[StrictInt, Field(ge=0, le=3)] | None = None
    sim_minute: Count | None = None

    @model_validator(mode="after")
    def _money_intents_carry_an_amount(self) -> ActionIntent:
        if self.type in MONEY_INTENTS and self.params.amount is None:
            raise ValueError(f"a {self.type} intent needs params.amount")
        return self


# ---------------------------------------------------------------------------- C2 ClearedAction


class ClearedAction(_Shape):
    """C2: the coordinator's verdict on one intent; the actor sees it the next round."""

    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"properties": {"status": {"const": "rejected"}}, "required": ["status"]},
        "then": {
            "required": ["reason"],
            "properties": {"reason": {"type": "string"}, "journal_id": {"type": "null"}},
        },
    }]})

    intent_id: Id
    status: Literal["accepted", "rejected", "pending"]
    reason: Code | None = None
    binding: Text | None = None
    journal_id: Id | None = None
    round: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _a_rejection_names_its_reason(self) -> ClearedAction:
        if self.status == "rejected" and (self.reason is None or self.journal_id is not None):
            raise ValueError("a rejection names its reason and posts no journal")
        return self


# --------------------------------------------------------------------------- C3 BoundApproval

LegKind = Literal["advance", "repayment", "fx", "payout"]
Mode = Literal["fake", "sandbox"]
RequestId = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{12}-[1-9][0-9]*-(advance|repayment|fx|payout)$")
]


class ApprovalLeg(_Shape):
    """One provider operation the approval binds, in execution order by `after`."""

    index: StrictInt = Field(ge=1)
    kind: LegKind
    amount: Amount
    source: Id
    counterparty: Id
    funded_by: Annotated[
        str, StringConstraints(pattern=r"^(spendable|reservation:[A-Za-z0-9._:/-]+)$")
    ] | None = None
    after: list[Annotated[StrictInt, Field(ge=1)]] = []
    facility_id: Id | None = None
    to_currency: Currency | None = None


class BoundApproval(_Shape):
    """C3: the operator's approval of one plan; any term outside it invalidates the whole."""

    approval_id: Id
    entity: Id
    account: Id
    legs: list[ApprovalLeg] = Field(min_length=1)
    plan_hash: Sha256
    snapshot_id: Id
    expires_at: AwareDatetime
    mode: Mode
    approver: Id

    @model_validator(mode="after")
    def _legs_are_ordered_by_known_legs(self) -> BoundApproval:
        indices = [leg.index for leg in self.legs]
        if len(set(indices)) != len(indices):
            raise ValueError("leg indices repeat")
        for leg in self.legs:
            if leg.index in leg.after or not set(leg.after) <= set(indices):
                raise ValueError(f"leg {leg.index} runs after a leg that is not another leg")
        return self


# ------------------------------------------------------------------------------ C4 ProviderOp

LegState = Literal["pending", "submitted", "settled", "failed", "unknown"]


class Receipt(_Shape):
    """What the provider's `GET` showed for a leg; `amount` is the provider's decimal string."""

    provider_id: Id
    request_id: RequestId
    kind: LegKind
    status: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z_]*$")]
    amount: Annotated[str, StringConstraints(pattern=r"^[0-9]+(\.[0-9]+)?$")]
    currency: Currency
    label: Text
    mode: Mode
    raw_keys: list[Annotated[str, StringConstraints(max_length=128)]]
    observed_at: AwareDatetime


class ProviderOp(_Shape):
    """C4: one leg's provider state; `unknown` opens an incident and is looked up by its ids."""

    model_config = ConfigDict(json_schema_extra={"allOf": [
        {
            "if": {"properties": {"state": {"const": "settled"}}, "required": ["state"]},
            "then": {"required": ["journal_id"], "properties": {"journal_id": {"type": "string"}}},
        },
        {
            "if": {"properties": {"reconciled": {"const": True}}, "required": ["reconciled"]},
            "then": {"properties": {"state": {"enum": ["settled", "failed"]}}},
        },
    ]})

    leg_id: RequestId
    request_id: RequestId
    kind: LegKind
    provider_id: Id | None = None
    state: LegState
    receipt: Receipt | None
    reconciled: StrictBool
    journal_id: Id | None = None

    @model_validator(mode="after")
    def _one_leg_one_identity(self) -> ProviderOp:
        if self.state == "settled" and self.journal_id is None:
            raise ValueError("a settled leg has a journal")
        if self.reconciled and self.state not in ("settled", "failed"):
            raise ValueError("only a settled or failed leg is reconciled")
        if self.leg_id != self.request_id:
            raise ValueError("the request id is the leg id")
        if self.receipt and (
            self.receipt.request_id != self.request_id or self.receipt.kind != self.kind
            or (self.provider_id is not None and self.receipt.provider_id != self.provider_id)
        ):
            raise ValueError("the receipt belongs to another leg")
        return self


# -------------------------------------------------------------------------------- C5 Snapshot

EntityKind = Literal["treasury", "lender pool", "borrower", "counterparty", "venue", "external"]
ContractState = Literal["offered", "active", "repaid", "defaulted", "closed"]


class Entity(_Shape):
    """A synthetic organisation; `escalation` is the role to call when every plan fails."""

    entity_id: Id
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    kind: EntityKind
    escalation: Id | None = None
    synthetic: StrictBool = True


class Flow(_Shape):
    """An expected movement not yet settled: pending_in by `expected_at`, pending_out by due."""

    flow_id: Id
    amount: Amount
    expected_at: AwareDatetime
    kind: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    reservation_id: Id | None = None


class Buckets(_Shape):
    """An account's buckets; `settled` is null exactly when the account is unknown."""

    settled: Money | None
    reserved: NonNegativeMoney
    pledged: NonNegativeMoney
    pending_in: list[Flow]
    pending_out: list[Flow]


class Account(_Shape):
    """One account of one entity in one currency; stale is derived from `as_of`, never stored."""

    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"properties": {"observability": {"const": "known"}}, "required": ["observability"]},
        "then": {"properties": {"buckets": {"properties": {"settled": {"type": "object"}}}}},
    }]})

    id: Id
    entity: Id
    currency: Currency
    kind: Literal["cash", "receivable", "payable", "income", "expense", "external"] = "cash"
    venue: Id | None = None
    floor: NonNegativeMoney | None = None
    observability: Literal["known", "unknown"]
    as_of: AwareDatetime
    buckets: Buckets

    @model_validator(mode="after")
    def _one_currency(self) -> Account:
        if self.observability == "known" and self.buckets.settled is None:
            raise ValueError("a known account has a settled balance")
        b = self.buckets
        moneys = [b.settled, b.reserved, b.pledged, self.floor]
        moneys += [flow.amount for flow in b.pending_in + b.pending_out]
        if any(m is not None and m.currency != self.currency for m in moneys):
            raise ValueError(f"account {self.id} holds {self.currency} only")
        return self


class Obligation(_Shape):
    """A payment owed by a deadline; it is never removed by inaction."""

    obligation_id: Id
    entity: Id
    account: Id
    amount: Amount
    due_at: AwareDatetime
    kind: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    mandatory: StrictBool = True
    reservation_id: Id | None = None
    state: Literal["open", "met", "missed", "deferred"] = "open"


class CommittedLine(_Shape):
    """A committed undrawn line: held for the borrower, never discretionary for the lender."""

    contract_id: Id
    kind: Literal["committed_line"]
    lender: Id
    borrower: Id
    limit: Amount
    drawn: NonNegativeMoney
    state: ContractState
    reservation_id: Id | None = None
    reserved_on: Id | None = None


class RevenueAdvance(_Shape):
    """A revenue-based advance: a flat fee on principal, repaid as a share of observed revenue."""

    contract_id: Id
    kind: Literal["revenue_advance"]
    lender: Id
    borrower: Id
    principal: Amount
    fee_bps: Bps
    repay_share_bps: Annotated[StrictInt, Field(ge=1, le=10000)]
    state: ContractState


class CollateralFacility(_Shape):
    """A facility secured by pledged collateral (simulation and tests only)."""

    contract_id: Id
    kind: Literal["collateral"]
    lender: Id
    borrower: Id
    limit: Amount
    collateral_ref: Id
    advance_rate_bps: Annotated[StrictInt, Field(ge=1, le=10000)]
    state: ContractState


SnapshotContract = Annotated[
    CommittedLine | RevenueAdvance | CollateralFacility, Field(discriminator="kind")
]


class Exposure(_Shape):
    """A venue or counterparty that two entities depend on: one shock reaches both."""

    exposure_id: Id
    venue: Id
    shared_with: list[Id] = Field(min_length=1)
    account: Id | None = None
    flow_id: Id | None = None


class Pool(_Shape):
    """A lender pool's reserve floor."""

    entity: Id
    floor: NonNegativeMoney


class Snapshot(_Shape):
    """C5: the frozen observed state the world starts from and every plan is decided on."""

    snapshot_id: Id
    as_of: AwareDatetime
    entities: list[Entity] = Field(min_length=1)
    accounts: list[Account]
    obligations: list[Obligation]
    contracts: list[SnapshotContract]
    exposures: list[Exposure]
    pools: list[Pool]

    @model_validator(mode="after")
    def _references_resolve(self) -> Snapshot:
        entities = {e.entity_id for e in self.entities}
        accounts = {a.id for a in self.accounts}
        if len(entities) != len(self.entities) or len(accounts) != len(self.accounts):
            raise ValueError("an entity or account id repeats")
        refs = [("entity", a.entity, entities) for a in self.accounts]
        refs += [("entity", o.entity, entities) for o in self.obligations]
        refs += [("account", o.account, accounts) for o in self.obligations]
        refs += [("entity", p.entity, entities) for p in self.pools]
        for what, ref, known in refs:
            if ref not in known:
                raise ValueError(f"unknown {what} {ref!r}")
        return self


# ------------------------------------------------------------------------------------ C6 API

MetricStatus = Literal["known", "unknown", "stale", "unassessed"]
PolicyId = Literal["no-action", "fixed-reserve", "integrated"]
Family = Literal[
    "delayed_receipt", "confidence_rumour", "stablecoin_depeg", "borrower_silence",
    "redemption_spike", "fx_gap",
]


class Response(_Shape):
    """Every /api/v1 response carries `as_of` and the provider mode."""

    as_of: AwareDatetime
    mode: Mode


class Metric(_Shape):
    """One figure on screen: a value only when known or stale; unknown is never zero."""

    model_config = ConfigDict(json_schema_extra={"allOf": [
        {
            "if": {"properties": {"status": {"enum": ["known", "stale"]}}, "required": ["status"]},
            "then": {"properties": {"minor": {"type": "integer"}}},
            "else": {"properties": {"minor": {"type": "null"}}},
        },
    ]})

    minor: StrictInt | None
    currency: Currency
    status: MetricStatus
    as_of: AwareDatetime | None = None

    @model_validator(mode="after")
    def _value_only_when_assessed(self) -> Metric:
        if (self.minor is None) == (self.status in ("known", "stale")):
            raise ValueError("a known or stale metric has a value; any other has none")
        return self


class ErrorBody(_Shape):
    code: Code
    detail: Text


class ErrorResponse(Response):
    """A refused or failed request."""

    error: ErrorBody


class HealthResponse(Response):
    """GET /api/v1/health."""

    ok: StrictBool
    airwallex: Mode
    connected: StrictBool
    model: Literal["scripted", "live"]
    version: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class DemoContext(_Shape):
    """The prepared demonstration run and its execution; null is unavailable, never a guess."""

    run_id: Id | None
    execution_id: Id | None


class UpcomingOutflow(_Shape):
    obligation_id: Id
    kind: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    amount: Amount
    due_at: AwareDatetime
    reserved: StrictBool


class Coverage(_Shape):
    """Minimum projected cash P over the horizon against the reserve floor."""

    min_projected: Metric
    at: AwareDatetime | None
    floor: Metric
    headroom: Metric


class Completeness(_Shape):
    status: Literal["complete", "partial"]
    missing: list[Annotated[str, StringConstraints(max_length=128)]]


class OverviewResponse(Response):
    """GET /api/v1/overview."""

    snapshot_id: Id
    cash: Metric
    spendable: Metric
    upcoming_outflows: list[UpcomingOutflow]
    coverage: Coverage
    lender_capacity: Metric
    completeness: Completeness
    demo: DemoContext


class CashPoint(_Shape):
    t: AwareDatetime
    value: Metric


class TreasuryAccount(_Shape):
    """An account with S (spendable now) and P (projected cash) kept as separate measures."""

    account_id: Id
    entity: Id
    currency: Currency
    observability: Literal["known", "unknown"]
    as_of: AwareDatetime
    buckets: Buckets
    spendable: Metric
    authority: Literal["full", "reduced"]
    floor: Metric
    projected: list[CashPoint]


class TreasuryResponse(Response):
    """GET /api/v1/treasury."""

    snapshot_id: Id
    accounts: list[TreasuryAccount]
    obligations: list[Obligation]


class CapacityParts(_Shape):
    settled_known: Metric
    committed_undrawn: Metric
    pledged: Metric
    obligations_due: Metric
    floor: Metric


class Capacity(_Shape):
    """K_p and the parts it is computed from."""

    K_p: Metric
    authority: Literal["full", "reduced"]
    parts: CapacityParts


class FacilityView(_Shape):
    facility_id: Id
    kind: Literal["committed_line", "revenue_advance", "collateral"]
    borrower: Id
    principal: Amount
    fee: NonNegativeMoney
    owed: NonNegativeMoney
    observed_revenue: Metric
    outstanding: NonNegativeMoney
    state: ContractState


class LendingResponse(Response):
    """GET /api/v1/lending."""

    snapshot_id: Id
    pool: Id
    capacity: Capacity
    facilities: list[FacilityView]


class ScenarioSpec(_Shape):
    family: Family
    seed: StrictInt
    params: dict[str, Param]


class RunRequest(_Shape):
    """POST /api/v1/runs."""

    snapshot_id: Id
    scenario: ScenarioSpec
    rounds: StrictInt = Field(ge=1, le=18)


class ForkRequest(_Shape):
    """POST /api/v1/runs/{id}/fork: one fresh branch per policy at a committed round."""

    checkpoint_round: StrictInt = Field(ge=0)
    policies: list[PolicyId] = Field(min_length=1)


class JobAccepted(Response):
    """202 from POST /api/v1/runs and POST /api/v1/runs/{id}/fork."""

    job_id: Id
    run_id: Id
    branch_ids: list[Id]


class Post(_Shape):
    post_id: Id
    round: StrictInt = Field(ge=0)
    branch_id: Id
    author: Id
    text: Text


class RoundView(_Shape):
    """One committed round of one branch."""

    round: StrictInt = Field(ge=0)
    branch_id: Id
    t_hours: StrictInt = Field(ge=0)
    intents: list[ActionIntent]
    cleared: list[ClearedAction]
    journal_ids: list[Id]


class CashPath(_Shape):
    branch_id: Id
    account_id: Id
    points: list[CashPoint]


class BranchView(_Shape):
    branch_id: Id
    parent_branch_id: Id | None
    checkpoint_round: Count | None
    policy: PolicyId | None
    replay: StrictBool


class RunResponse(Response):
    """GET /api/v1/runs/{id}."""

    run_id: Id
    snapshot_id: Id
    status: Literal["queued", "running", "done", "failed"]
    committed_round: Count | None
    rounds: list[RoundView]
    feed: list[Post]
    cash_paths: list[CashPath]
    branches: list[BranchView]


class PolicyResult(_Shape):
    """One policy on one scenario, read from its branch's realised ledger."""

    policy: PolicyId
    scenario_id: Id
    branch_id: Id
    replay: StrictBool
    obligations_unmet: StrictInt = Field(ge=0)
    floor_kept: StrictBool
    min_cash: Metric
    funding_cost: NonNegativeMoney
    feasible: StrictBool


class Escalation(_Shape):
    """When every policy fails: the earliest unmet constraint, the binding one, whom to call."""

    earliest_unmet: Text
    binding: Text
    contact: Id


class DecisionsResponse(Response):
    """GET /api/v1/decisions/{run_id}; a selection is never an approval."""

    model_config = ConfigDict(json_schema_extra={"allOf": [
        {
            "if": {"properties": {"status": {"const": "selected"}}, "required": ["status"]},
            "then": {"properties": {"selected": {"type": "string"}}},
        },
        {
            "if": {"properties": {"status": {"const": "all_infeasible"}}, "required": ["status"]},
            "then": {"properties": {"selected": {"type": "null"},
                                    "escalation": {"type": "object"}}},
        },
    ]})

    run_id: Id
    snapshot_id: Id
    checkpoint_round: StrictInt = Field(ge=0)
    cohort: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    weight_kind: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    status: Literal["pending", "selected", "all_infeasible"]
    results: list[PolicyResult]
    selected: PolicyId | None
    escalation: Escalation | None

    @model_validator(mode="after")
    def _status_matches_selection(self) -> DecisionsResponse:
        if self.status == "selected" and self.selected is None:
            raise ValueError("a selected decision names its policy")
        if self.status == "all_infeasible" and (self.selected or self.escalation is None):
            raise ValueError("all infeasible selects nothing and escalates")
        return self


class ApprovalRequest(_Shape):
    """POST /api/v1/approvals: the selected policy decides again on the observed snapshot."""

    run_id: Id
    policy: PolicyId


class ApprovalResponse(Response):
    """201 from POST /api/v1/approvals."""

    approval: BoundApproval


class ExecutionRequest(_Shape):
    """POST /api/v1/executions."""

    approval_id: Id


class ExecutionAccepted(Response):
    """202 from POST /api/v1/executions; the execution id is the approval id."""

    execution_id: Id


class ExecutionLeg(ProviderOp):
    """A C4 leg with the label the connector's leg plan gives it."""

    label: Text


class Incident(_Shape):
    incident_id: Id
    leg_id: RequestId
    kind: Code
    state: Literal["open", "closed"]
    opened_at: AwareDatetime


class ExecutionResponse(Response):
    """GET /api/v1/executions/{id}."""

    execution_id: Id
    approval_id: Id
    snapshot_id: Id
    legs: list[ExecutionLeg]
    incidents: list[Incident]


class WebhookAck(Response):
    """POST /api/v1/webhooks/airwallex: a verified hint that triggers a GET."""

    accepted: StrictBool


class InterviewRequest(_Shape):
    """POST /api/v1/interview: read-only, still behind the demo token."""

    run_id: Id
    branch_id: Id
    round: StrictInt = Field(ge=0)
    actor_id: Id
    question: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class InterviewResponse(Response):
    run_id: Id
    branch_id: Id
    round: StrictInt = Field(ge=0)
    actor_id: Id
    answer: Text
    read_only: Literal[True]
    replay: StrictBool
    evidence_ids: list[Id]


class FigureSource(_Shape):
    run_id: Id
    branch_id: Id
    round: StrictInt = Field(ge=0)
    journal_id: Id | None = None
    intent_id: Id | None = None


class ReportFigure(_Shape):
    """A number in a report, with the structured result it came from."""

    label: Text
    value: Metric
    source: FigureSource


class ReportSection(_Shape):
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text: Text
    figures: list[ReportFigure]


class ReportResponse(Response):
    """GET /api/v1/reports/{run_id}."""

    run_id: Id
    snapshot_id: Id
    model: Literal["scripted", "live"]
    replay: StrictBool
    sections: list[ReportSection]


def _route(response: str, request: str | None = None, status: int = 200,
           token: bool = False) -> dict[str, Any]:
    return {"request": request, "response": response, "status": status, "token": token}


C6_ROUTES: dict[str, dict[str, Any]] = {
    "GET /api/v1/health": _route("HealthResponse"),
    "GET /api/v1/overview": _route("OverviewResponse"),
    "GET /api/v1/treasury": _route("TreasuryResponse"),
    "GET /api/v1/lending": _route("LendingResponse"),
    "POST /api/v1/runs": _route("JobAccepted", "RunRequest", 202, True),
    "GET /api/v1/runs/{id}": _route("RunResponse"),
    "POST /api/v1/runs/{id}/fork": _route("JobAccepted", "ForkRequest", 202, True),
    "GET /api/v1/decisions/{run_id}": _route("DecisionsResponse"),
    "POST /api/v1/approvals": _route("ApprovalResponse", "ApprovalRequest", 201, True),
    "POST /api/v1/executions": _route("ExecutionAccepted", "ExecutionRequest", 202, True),
    "GET /api/v1/executions/{id}": _route("ExecutionResponse"),
    "POST /api/v1/webhooks/airwallex": _route("WebhookAck"),
    "POST /api/v1/interview": _route("InterviewResponse", "InterviewRequest", 200, True),
    "GET /api/v1/reports/{run_id}": _route("ReportResponse"),
}

C6_MODELS: dict[str, type[BaseModel]] = {
    model.__name__: model for model in (
        ErrorResponse, HealthResponse, OverviewResponse, TreasuryResponse, LendingResponse,
        RunRequest, ForkRequest, JobAccepted, RunResponse, DecisionsResponse, ApprovalRequest,
        ApprovalResponse, ExecutionRequest, ExecutionAccepted, ExecutionResponse, WebhookAck,
        InterviewRequest, InterviewResponse, ReportResponse,
    )
}

# --------------------------------------------------------------------------------- registry

CONTRACTS: dict[str, type[BaseModel] | None] = {
    "c1_action_intent": ActionIntent,
    "c2_cleared_action": ClearedAction,
    "c3_bound_approval": BoundApproval,
    "c4_provider_op": ProviderOp,
    "c5_snapshot": Snapshot,
    "c6_api": None,  # many shapes: every request and response of C6_ROUTES under $defs
}
CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def contract_schema(name: str) -> dict[str, Any]:
    """The JSON Schema of one contract, as committed in `contracts/<name>.schema.json`."""
    head = {
        "$schema": DRAFT,
        "$comment": "Generated from backend/app/finance/schemas.py by "
                    "`python -m app.finance.schemas`; edit the model, not this file.",
    }
    model = CONTRACTS[name]
    if model is not None:
        return head | model.model_json_schema()
    _, defs = models_json_schema([(m, "validation") for m in C6_MODELS.values()])
    for route in C6_ROUTES.values():
        assert route["response"] in C6_MODELS and route["request"] in (None, *C6_MODELS)
    return head | {
        "title": "C6 API",
        "description": "The /api/v1 shapes (system brief §11). Each route names its request and "
                       "response under $defs; validate a body against `#/$defs/<name>`.",
        "x-routes": C6_ROUTES,
    } | defs


def contract_text(name: str) -> str:
    return json.dumps(contract_schema(name), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    CONTRACTS_DIR.mkdir(exist_ok=True)
    for name in CONTRACTS:
        (CONTRACTS_DIR / f"{name}.schema.json").write_text(contract_text(name), encoding="utf-8")
        print(f"wrote contracts/{name}.schema.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
