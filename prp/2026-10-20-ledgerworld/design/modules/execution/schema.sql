-- LedgerWorld execution schema (design, DDL only). Lives in the OBSERVED ledger store next to the ledger
-- module's tables (accounts, journals, reservations), never in a branch store. Portable across SQLite
-- (tests) and PostgreSQL (deploy). State changes and their leg_events row are written in one transaction
-- by the gateway (no triggers by design).

CREATE TABLE approvals (
    approval_id      VARCHAR(64) PRIMARY KEY,
    entity_id        VARCHAR(64) NOT NULL,
    account_id       VARCHAR(128) NOT NULL,
    snapshot_id      VARCHAR(96) NOT NULL,
    plan_hash        CHAR(64) NOT NULL,
    mode             VARCHAR(8) NOT NULL CHECK (mode IN ('fake', 'sandbox')),
    approver         VARCHAR(64) NOT NULL,
    created_at       TIMESTAMP NOT NULL,
    expires_at       TIMESTAMP NOT NULL,
    used_at          TIMESTAMP,
    CHECK (expires_at > created_at),
    UNIQUE (plan_hash, snapshot_id)
);

-- The outbox: one row per leg, written before any provider call. request_id never changes.
CREATE TABLE execution_legs (
    leg_id           VARCHAR(96) PRIMARY KEY,
    approval_id      VARCHAR(64) NOT NULL REFERENCES approvals (approval_id),
    leg_index        INTEGER NOT NULL CHECK (leg_index >= 1),
    kind             VARCHAR(12) NOT NULL CHECK (kind IN ('advance', 'repayment', 'fx', 'payout')),
    request_id       VARCHAR(96) NOT NULL UNIQUE,
    source_account   VARCHAR(128) NOT NULL,
    counterparty     VARCHAR(128) NOT NULL,
    currency         CHAR(3) NOT NULL CHECK (length(currency) = 3 AND currency = upper(currency)),
    amount_minor     BIGINT NOT NULL CHECK (amount_minor > 0),
    funded_by        VARCHAR(96),
    after_legs       VARCHAR(64),
    provider_op      VARCHAR(48),
    ledger_only      BOOLEAN NOT NULL DEFAULT FALSE,
    state            VARCHAR(10) NOT NULL CHECK (state IN ('pending', 'submitted', 'settled', 'failed', 'unknown')),
    provider_id      VARCHAR(96),
    provider_status  VARCHAR(32),
    receipt_label    VARCHAR(80) NOT NULL,
    journal_id       VARCHAR(64),
    reconciled       BOOLEAN NOT NULL DEFAULT FALSE,
    attempts         INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    updated_at       TIMESTAMP NOT NULL,
    UNIQUE (approval_id, leg_index),
    CHECK (state <> 'settled' OR journal_id IS NOT NULL),
    CHECK (ledger_only OR state NOT IN ('settled') OR provider_id IS NOT NULL)
);
CREATE INDEX execution_legs_open ON execution_legs (state);
CREATE UNIQUE INDEX execution_legs_one_journal ON execution_legs (journal_id);

CREATE TABLE leg_events (
    event_seq        INTEGER PRIMARY KEY,
    leg_id           VARCHAR(96) NOT NULL REFERENCES execution_legs (leg_id),
    from_state       VARCHAR(10),
    to_state         VARCHAR(10) NOT NULL,
    cause            VARCHAR(48) NOT NULL,
    provider_status  VARCHAR(32),
    raw_keys         TEXT,
    at               TIMESTAMP NOT NULL
);
CREATE INDEX leg_events_by_leg ON leg_events (leg_id, event_seq);

CREATE TABLE incidents (
    incident_id      VARCHAR(64) PRIMARY KEY,
    kind             VARCHAR(32) NOT NULL CHECK (kind IN ('outcome_unknown', 'paid_then_failed', 'amount_mismatch',
                                                         'currency_mismatch', 'unknown_provider_object', 'lookup_ambiguous',
                                                         'ledger_refused')),
    leg_id           VARCHAR(96) REFERENCES execution_legs (leg_id),
    provider_id      VARCHAR(96),
    detail           TEXT NOT NULL,
    opened_at        TIMESTAMP NOT NULL,
    closed_at        TIMESTAMP,
    closed_by        VARCHAR(32) CHECK (closed_by IS NULL OR closed_by IN ('lookup', 'operator')),
    CHECK ((closed_at IS NULL) = (closed_by IS NULL))
);
CREATE INDEX incidents_open ON incidents (closed_at);
-- At most one open incident of a kind per leg.
CREATE UNIQUE INDEX incidents_one_open_per_leg_kind ON incidents (leg_id, kind) WHERE closed_at IS NULL;

-- Verified webhook events, deduped by the provider's event id. An event never changes a leg by itself.
CREATE TABLE webhook_events (
    event_id         VARCHAR(96) PRIMARY KEY,
    name             VARCHAR(64) NOT NULL,
    object_id        VARCHAR(96),
    received_at      TIMESTAMP NOT NULL,
    timestamp_ms     BIGINT NOT NULL,
    handled          BOOLEAN NOT NULL DEFAULT FALSE
);
