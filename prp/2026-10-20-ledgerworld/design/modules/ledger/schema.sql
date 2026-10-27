-- LedgerWorld ledger schema (design, DDL only). Portable across SQLite (tests) and PostgreSQL (deploy).
-- One schema (PostgreSQL) or one database file (SQLite) holds one branch; a fork copies it at the checkpoint.
-- Money is integer minor units (BIGINT) with an ISO-4217 code. Per-journal balance per currency is
-- enforced by the store in the same transaction (a CHECK cannot span rows; no triggers by design).

CREATE TABLE branch_meta (
    branch_id          VARCHAR(64) PRIMARY KEY,
    world_id           VARCHAR(64) NOT NULL,
    parent_branch_id   VARCHAR(64),
    checkpoint_round   INTEGER,
    replay             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMP NOT NULL
);

CREATE TABLE entities (
    entity_id   VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    kind        VARCHAR(32) NOT NULL CHECK (kind IN ('treasury', 'lender pool', 'borrower', 'counterparty', 'venue', 'external')),
    synthetic   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE accounts (
    account_id     VARCHAR(128) PRIMARY KEY,
    entity_id      VARCHAR(64) NOT NULL REFERENCES entities (entity_id),
    currency       CHAR(3) NOT NULL CHECK (length(currency) = 3 AND currency = upper(currency)),
    kind           VARCHAR(16) NOT NULL CHECK (kind IN ('cash', 'receivable', 'payable', 'income', 'expense', 'external')),
    venue          VARCHAR(64),
    floor_minor    BIGINT CHECK (floor_minor IS NULL OR floor_minor >= 0)
);
CREATE INDEX accounts_by_entity ON accounts (entity_id);

-- Observability of a cash account: known with an as_of, or unknown (value not observable). Stale is
-- derived at read time (as_of older than STALE_AFTER), never stored.
CREATE TABLE account_observations (
    account_id     VARCHAR(128) PRIMARY KEY REFERENCES accounts (account_id),
    observability  VARCHAR(8) NOT NULL CHECK (observability IN ('known', 'unknown')),
    as_of          TIMESTAMP NOT NULL
);

CREATE TABLE journals (
    journal_id         VARCHAR(64) PRIMARY KEY,
    kind               VARCHAR(32) NOT NULL,
    round              INTEGER NOT NULL CHECK (round >= 0),
    sim_time           TIMESTAMP NOT NULL,
    seq                INTEGER NOT NULL,
    source_intent_id   VARCHAR(96),
    source_leg_id      VARCHAR(96),
    mode               VARCHAR(24) NOT NULL DEFAULT 'simulation' CHECK (mode IN ('simulation', 'fake', 'sandbox', 'sandbox_simulation')),
    UNIQUE (seq)
);
CREATE INDEX journals_by_round ON journals (round);

-- Signed postings: positive = debit, negative = credit. Settled balance of an account = sum of its postings.
CREATE TABLE postings (
    posting_id    INTEGER PRIMARY KEY,
    journal_id    VARCHAR(64) NOT NULL REFERENCES journals (journal_id),
    account_id    VARCHAR(128) NOT NULL REFERENCES accounts (account_id),
    currency      CHAR(3) NOT NULL,
    amount_minor  BIGINT NOT NULL CHECK (amount_minor <> 0)
);
CREATE INDEX postings_by_account ON postings (account_id);
CREATE INDEX postings_by_journal ON postings (journal_id);

-- Expected movements not yet settled: pending_in (receivables, withdrawals, advances in flight) and
-- pending_out (committed outflows). A delay event rewrites expected_at; history lives in the transcript.
CREATE TABLE expected_flows (
    flow_id         VARCHAR(64) PRIMARY KEY,
    account_id      VARCHAR(128) NOT NULL REFERENCES accounts (account_id),
    direction       VARCHAR(3) NOT NULL CHECK (direction IN ('in', 'out')),
    currency        CHAR(3) NOT NULL,
    amount_minor    BIGINT NOT NULL CHECK (amount_minor > 0),
    expected_at     TIMESTAMP NOT NULL,
    state           VARCHAR(12) NOT NULL CHECK (state IN ('pending', 'settled', 'cancelled')),
    reservation_id  VARCHAR(64),
    kind            VARCHAR(32) NOT NULL
);
CREATE INDEX expected_flows_open ON expected_flows (account_id, state, expected_at);

CREATE TABLE obligations (
    obligation_id   VARCHAR(64) PRIMARY KEY,
    entity_id       VARCHAR(64) NOT NULL REFERENCES entities (entity_id),
    account_id      VARCHAR(128) NOT NULL REFERENCES accounts (account_id),
    currency        CHAR(3) NOT NULL,
    amount_minor    BIGINT NOT NULL CHECK (amount_minor > 0),
    due_at          TIMESTAMP NOT NULL,
    kind            VARCHAR(32) NOT NULL,
    mandatory       BOOLEAN NOT NULL DEFAULT TRUE,
    state           VARCHAR(12) NOT NULL CHECK (state IN ('open', 'met', 'missed', 'deferred')),
    reservation_id  VARCHAR(64)
);
CREATE INDEX obligations_open ON obligations (account_id, state, due_at);

CREATE TABLE reservations (
    reservation_id  VARCHAR(64) PRIMARY KEY,
    account_id      VARCHAR(128) NOT NULL REFERENCES accounts (account_id),
    currency        CHAR(3) NOT NULL,
    amount_minor    BIGINT NOT NULL CHECK (amount_minor > 0),
    state           VARCHAR(12) NOT NULL CHECK (state IN ('held', 'committed', 'released', 'expired', 'settled')),
    purpose         VARCHAR(32) NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    expires_at      TIMESTAMP
);
CREATE INDEX reservations_held ON reservations (account_id, state);

-- The same units are never pledged twice: one active pledge per collateral reference.
CREATE TABLE pledges (
    pledge_id       VARCHAR(64) PRIMARY KEY,
    account_id      VARCHAR(128) NOT NULL REFERENCES accounts (account_id),
    collateral_ref  VARCHAR(128) NOT NULL,
    currency        CHAR(3) NOT NULL,
    amount_minor    BIGINT NOT NULL CHECK (amount_minor > 0),
    state           VARCHAR(12) NOT NULL CHECK (state IN ('active', 'released')),
    facility_id     VARCHAR(64)
);
CREATE UNIQUE INDEX pledges_one_active_per_ref ON pledges (collateral_ref) WHERE state = 'active';

CREATE TABLE lending_pools (
    pool_entity_id  VARCHAR(64) PRIMARY KEY REFERENCES entities (entity_id),
    currency        CHAR(3) NOT NULL,
    floor_minor     BIGINT NOT NULL CHECK (floor_minor >= 0)
);

CREATE TABLE facilities (
    facility_id         VARCHAR(64) PRIMARY KEY,
    pool_entity_id      VARCHAR(64) NOT NULL REFERENCES lending_pools (pool_entity_id),
    borrower_entity_id  VARCHAR(64) NOT NULL REFERENCES entities (entity_id),
    kind                VARCHAR(20) NOT NULL CHECK (kind IN ('committed_line', 'revenue_advance', 'collateral')),
    currency            CHAR(3) NOT NULL,
    limit_minor         BIGINT NOT NULL CHECK (limit_minor > 0),
    fee_bps             INTEGER NOT NULL DEFAULT 0 CHECK (fee_bps >= 0 AND fee_bps <= 10000),
    repay_share_bps     INTEGER CHECK (repay_share_bps IS NULL OR (repay_share_bps > 0 AND repay_share_bps <= 10000)),
    reservation_id      VARCHAR(64),
    state               VARCHAR(12) NOT NULL CHECK (state IN ('offered', 'active', 'repaid', 'defaulted', 'closed')),
    receivable_account  VARCHAR(128) REFERENCES accounts (account_id)
);
CREATE INDEX facilities_by_pool ON facilities (pool_entity_id, state);

-- Repayment is computed from observed revenue only; a forecast never enters this table.
CREATE TABLE revenue_observations (
    facility_id     VARCHAR(64) NOT NULL REFERENCES facilities (facility_id),
    period_end      TIMESTAMP NOT NULL,
    currency        CHAR(3) NOT NULL,
    revenue_minor   BIGINT NOT NULL CHECK (revenue_minor >= 0),
    observed_at     TIMESTAMP NOT NULL,
    source          VARCHAR(64) NOT NULL,
    PRIMARY KEY (facility_id, period_end)
);
