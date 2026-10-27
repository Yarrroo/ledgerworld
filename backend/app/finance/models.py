"""The ledger's tables and its write shapes (system brief §5, design/modules/ledger/schema.sql).

The tables mirror `schema.sql` column for column; a test loads both and compares them. Settled
balance is never a column: it is the sum of an account's postings, so it cannot drift from the
journals. Money is integer minor units (BIGINT) with an ISO-4217 code everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, get_args

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    false,
    text,
    true,
)

STALE_AFTER = timedelta(hours=6)  # a balance strictly older than this (simulated) is stale
HORIZON = timedelta(hours=72)  # the default planning horizon (system brief §6)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)  # the time of what has no time of its own

RefusalCode = Literal[
    "journal_unbalanced", "no_journal", "zero_amount", "amount_not_integer_minor",
    "reserved_exceeds_settled", "pledge_exceeds_free", "already_pledged", "reservation_not_held",
    "insufficient_spendable", "breaks_floor", "stale_balance", "unknown_balance",
    "beyond_capacity",
]
REFUSAL_CODES = frozenset(get_args(RefusalCode))


class LedgerRefusal(Exception):
    """A write the ledger refuses; the store is left exactly as it was."""

    def __init__(self, code: RefusalCode, **detail: Any) -> None:
        if code not in REFUSAL_CODES:
            raise ValueError(f"unknown refusal code {code!r}")
        self.code = code
        self.detail = detail
        super().__init__(f"{code} {detail}" if detail else code)


class UnknownAccount(LookupError):
    """A write or read names an account the ledger does not hold."""


@dataclass(frozen=True)
class Posting:
    """One signed line of a journal: positive = debit, negative = credit, never zero."""

    account_id: str
    amount_minor: int
    currency: str | None = None  # taken from the account when omitted; must match it when given


@dataclass(frozen=True)
class Journal:
    """A double-entry journal: Σ amount = 0 per currency; it commits whole or not at all."""

    journal_id: str
    postings: tuple[Posting, ...]
    kind: str = "transfer"
    round: int = 0
    sim_time: datetime = EPOCH
    source_intent_id: str | None = None
    source_leg_id: str | None = None
    mode: Literal["simulation", "fake", "sandbox", "sandbox_simulation"] = "simulation"
    seq: int | None = None  # assigned by the store at commit


metadata = MetaData()


def _ccy() -> Column:
    return Column("currency", CHAR(3), nullable=False)


def _ts(name: str, nullable: bool = False) -> Column:
    return Column(name, DateTime(), nullable=nullable)  # naive UTC; the store adds the zone


def _amount() -> Column:
    return Column("amount_minor", BigInteger, nullable=False)


branch_meta = Table(
    "branch_meta", metadata,
    Column("branch_id", String(64), primary_key=True),
    Column("world_id", String(64), nullable=False),
    Column("parent_branch_id", String(64)),
    Column("checkpoint_round", Integer),
    Column("replay", Boolean, nullable=False, server_default=false()),
    _ts("created_at"),
)

entities = Table(
    "entities", metadata,
    Column("entity_id", String(64), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("synthetic", Boolean, nullable=False, server_default=true()),
    CheckConstraint(
        "kind IN ('treasury', 'lender pool', 'borrower', 'counterparty', 'venue', 'external')"),
)

accounts = Table(
    "accounts", metadata,
    Column("account_id", String(128), primary_key=True),
    Column("entity_id", String(64), ForeignKey("entities.entity_id"), nullable=False),
    _ccy(),
    Column("kind", String(16), nullable=False),
    Column("venue", String(64)),
    Column("floor_minor", BigInteger),
    CheckConstraint("length(currency) = 3 AND currency = upper(currency)"),
    CheckConstraint("kind IN ('cash', 'receivable', 'payable', 'income', 'expense', 'external')"),
    CheckConstraint("floor_minor IS NULL OR floor_minor >= 0"),
    Index("accounts_by_entity", "entity_id"),
)

account_observations = Table(
    "account_observations", metadata,
    Column("account_id", String(128), ForeignKey("accounts.account_id"), primary_key=True),
    Column("observability", String(8), nullable=False),
    _ts("as_of"),
    CheckConstraint("observability IN ('known', 'unknown')"),
)

journals = Table(
    "journals", metadata,
    Column("journal_id", String(64), primary_key=True),
    Column("kind", String(32), nullable=False),
    Column("round", Integer, nullable=False),
    _ts("sim_time"),
    Column("seq", Integer, nullable=False),
    Column("source_intent_id", String(96)),
    Column("source_leg_id", String(96)),
    Column("mode", String(24), nullable=False, server_default=text("'simulation'")),
    CheckConstraint("round >= 0"),
    CheckConstraint("mode IN ('simulation', 'fake', 'sandbox', 'sandbox_simulation')"),
    UniqueConstraint("seq"),
    Index("journals_by_round", "round"),
)

# Signed postings: positive = debit, negative = credit. Settled = Σ postings of the account.
postings = Table(
    "postings", metadata,
    Column("posting_id", Integer, primary_key=True, autoincrement=True),
    Column("journal_id", String(64), ForeignKey("journals.journal_id"), nullable=False),
    Column("account_id", String(128), ForeignKey("accounts.account_id"), nullable=False),
    _ccy(),
    _amount(),
    CheckConstraint("amount_minor <> 0"),
    Index("postings_by_account", "account_id"),
    Index("postings_by_journal", "journal_id"),
)

# pending_in / pending_out not yet settled; a delay rewrites expected_at.
expected_flows = Table(
    "expected_flows", metadata,
    Column("flow_id", String(64), primary_key=True),
    Column("account_id", String(128), ForeignKey("accounts.account_id"), nullable=False),
    Column("direction", String(3), nullable=False),
    _ccy(),
    _amount(),
    _ts("expected_at"),
    Column("state", String(12), nullable=False),
    Column("reservation_id", String(64)),
    Column("kind", String(32), nullable=False),
    CheckConstraint("direction IN ('in', 'out')"),
    CheckConstraint("amount_minor > 0"),
    CheckConstraint("state IN ('pending', 'settled', 'cancelled')"),
    Index("expected_flows_open", "account_id", "state", "expected_at"),
)

obligations = Table(
    "obligations", metadata,
    Column("obligation_id", String(64), primary_key=True),
    Column("entity_id", String(64), ForeignKey("entities.entity_id"), nullable=False),
    Column("account_id", String(128), ForeignKey("accounts.account_id"), nullable=False),
    _ccy(),
    _amount(),
    _ts("due_at"),
    Column("kind", String(32), nullable=False),
    Column("mandatory", Boolean, nullable=False, server_default=true()),
    Column("state", String(12), nullable=False),
    Column("reservation_id", String(64)),
    CheckConstraint("amount_minor > 0"),
    CheckConstraint("state IN ('open', 'met', 'missed', 'deferred')"),
    Index("obligations_open", "account_id", "state", "due_at"),
    # One reservation backs at most one obligation, so one payment never meets two. Null repeats.
    # Not partial on state: a met obligation keeps its payment, which no later one may claim.
    Index("obligations_one_per_reservation", "reservation_id", unique=True),
)

reservations = Table(
    "reservations", metadata,
    Column("reservation_id", String(64), primary_key=True),
    Column("account_id", String(128), ForeignKey("accounts.account_id"), nullable=False),
    _ccy(),
    _amount(),
    Column("state", String(12), nullable=False),
    Column("purpose", String(32), nullable=False),
    _ts("created_at"),
    _ts("expires_at", nullable=True),
    CheckConstraint("amount_minor > 0"),
    CheckConstraint("state IN ('held', 'committed', 'released', 'expired', 'settled')"),
    Index("reservations_held", "account_id", "state"),
)

pledges = Table(
    "pledges", metadata,
    Column("pledge_id", String(64), primary_key=True),
    Column("account_id", String(128), ForeignKey("accounts.account_id"), nullable=False),
    Column("collateral_ref", String(128), nullable=False),
    _ccy(),
    _amount(),
    Column("state", String(12), nullable=False),
    Column("facility_id", String(64)),
    CheckConstraint("amount_minor > 0"),
    CheckConstraint("state IN ('active', 'released')"),
    # The same units are never pledged twice: one active pledge per collateral reference.
    Index("pledges_one_active_per_ref", "collateral_ref", unique=True,
          sqlite_where=text("state = 'active'"), postgresql_where=text("state = 'active'")),
)

lending_pools = Table(
    "lending_pools", metadata,
    Column("pool_entity_id", String(64), ForeignKey("entities.entity_id"), primary_key=True),
    _ccy(),
    Column("floor_minor", BigInteger, nullable=False),
    CheckConstraint("floor_minor >= 0"),
)

facilities = Table(
    "facilities", metadata,
    Column("facility_id", String(64), primary_key=True),
    Column("pool_entity_id", String(64), ForeignKey("lending_pools.pool_entity_id"),
           nullable=False),
    Column("borrower_entity_id", String(64), ForeignKey("entities.entity_id"), nullable=False),
    Column("kind", String(20), nullable=False),
    _ccy(),
    Column("limit_minor", BigInteger, nullable=False),
    Column("fee_bps", Integer, nullable=False, server_default=text("0")),
    Column("repay_share_bps", Integer),
    Column("reservation_id", String(64)),
    Column("state", String(12), nullable=False),
    Column("receivable_account", String(128), ForeignKey("accounts.account_id")),
    CheckConstraint("kind IN ('committed_line', 'revenue_advance', 'collateral')"),
    CheckConstraint("limit_minor > 0"),
    CheckConstraint("fee_bps >= 0 AND fee_bps <= 10000"),
    CheckConstraint(
        "repay_share_bps IS NULL OR (repay_share_bps > 0 AND repay_share_bps <= 10000)"),
    CheckConstraint("state IN ('offered', 'active', 'repaid', 'defaulted', 'closed')"),
    Index("facilities_by_pool", "pool_entity_id", "state"),
)

# Repayment is computed from observed revenue only; a forecast never enters this table.
revenue_observations = Table(
    "revenue_observations", metadata,
    Column("facility_id", String(64), ForeignKey("facilities.facility_id"), primary_key=True),
    Column("period_end", DateTime(), primary_key=True),
    _ccy(),
    Column("revenue_minor", BigInteger, nullable=False),
    _ts("observed_at"),
    Column("source", String(64), nullable=False),
    CheckConstraint("revenue_minor >= 0"),
)
