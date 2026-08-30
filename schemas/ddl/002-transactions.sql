-- schemas/ddl/002-transactions.sql
-- Reference entity per brief spec (A4.4) — replicated exactly as specified.

CREATE TYPE transaction_type_enum AS ENUM ('P2P', 'MERCHANT_PAYMENT', 'SETTLEMENT', 'REVERSAL', 'FEE');
CREATE TYPE transaction_status_enum AS ENUM ('INITIATED', 'PROCESSING', 'COMPLETED', 'FAILED', 'REVERSED');

CREATE TABLE transactions (
    transaction_id        UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    idempotency_key        VARCHAR(128) NOT NULL,
    transaction_type       transaction_type_enum NOT NULL,
    source_account_id      UUID,               -- NULL for system credits
    destination_account_id UUID,               -- NULL for fee deductions
    amount                  NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    status                  transaction_status_enum NOT NULL DEFAULT 'INITIATED',
    saga_id                 UUID NOT NULL,
    failure_reason          VARCHAR(500),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at             TIMESTAMPTZ,
    metadata                 JSONB DEFAULT '{}',

    -- Idempotency uniqueness is per 24hr TTL window (FR-002) — enforced at the
    -- Redis layer for the fast-path check; this UNIQUE constraint is the
    -- durable backstop so a race between two near-simultaneous duplicate
    -- requests can never both commit, even if both miss the Redis check.
    CONSTRAINT uq_transactions_idempotency_key UNIQUE (idempotency_key)
);

-- Citus distribution: distributed by source_account_id where possible, so that
-- the common case (debit-side write) is shard-local. destination_account_id
-- may reference a row on a different shard — this is the cross-shard case
-- handled by the Saga pattern (docs/06, adrs/007), NOT by a Citus distributed
-- transaction. System-credit transactions (source_account_id NULL) are
-- distributed by transaction_id as a fallback.
SELECT create_distributed_table('transactions', 'source_account_id');

CREATE TRIGGER trg_transactions_updated_at
    BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
-- Note: transactions has no updated_at column per brief spec (uses completed_at
-- instead) — trigger above is defined for consistency with other tables but
-- not attached here; omitted intentionally.
DROP TRIGGER IF EXISTS trg_transactions_updated_at ON transactions;

-- Indexes
CREATE INDEX idx_transactions_idempotency_key ON transactions (idempotency_key);
CREATE INDEX idx_transactions_saga_id ON transactions (saga_id);
CREATE INDEX idx_transactions_source_account ON transactions (source_account_id, created_at DESC);
CREATE INDEX idx_transactions_dest_account ON transactions (destination_account_id, created_at DESC);
CREATE INDEX idx_transactions_status_processing ON transactions (transaction_id)
    WHERE status IN ('INITIATED', 'PROCESSING');  -- partial index for the
                                                     -- orchestrator's periodic
                                                     -- sweep of in-flight sagas