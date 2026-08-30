-- schemas/ddl/001-accounts.sql
-- Reference entity per brief spec (A4.4) — replicated exactly as specified.

CREATE TYPE account_type_enum AS ENUM ('SAVINGS', 'CURRENT', 'WALLET', 'MERCHANT', 'SETTLEMENT_POOL');
CREATE TYPE account_status_enum AS ENUM ('ACTIVE', 'FROZEN', 'SUSPENDED', 'CLOSED');
CREATE TYPE account_tier_enum AS ENUM ('BASIC', 'PREMIUM', 'MERCHANT');

CREATE TABLE accounts (
    account_id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),  -- UUIDv7: time-ordered, avoids random-insert
                                                                        -- write amplification across Citus shards
    user_id             UUID NOT NULL,
    account_type        account_type_enum NOT NULL,
    currency             CHAR(3) NOT NULL DEFAULT 'INR',
    available_balance    NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (available_balance >= 0),
    ledger_balance       NUMERIC(18,4) NOT NULL DEFAULT 0,
    version              BIGINT NOT NULL DEFAULT 1,                    -- OCC version counter (FR-009)
    status                account_status_enum NOT NULL DEFAULT 'ACTIVE',
    tier                  account_tier_enum NOT NULL DEFAULT 'BASIC',
    shard_key             INTEGER NOT NULL,                            -- hash(account_id) mod N, precomputed
                                                                        -- for explicit routing (see docs/06)
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_accounts_user FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Citus distribution: sharded by account_id (the primary access pattern is always
-- "operate on one account" — see docs/06 for full sharding rationale)
SELECT create_distributed_table('accounts', 'account_id');

-- Trigger: updated_at auto-maintained (never trust the application layer alone
-- for this — Section 6 principle)
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Indexes (see docs/05 for full indexing rationale table)
CREATE INDEX idx_accounts_user_id ON accounts (user_id);
CREATE INDEX idx_accounts_status_active ON accounts (account_id) WHERE status = 'ACTIVE';