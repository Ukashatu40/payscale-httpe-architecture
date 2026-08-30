-- schemas/ddl/007-merchant-settlements.sql
-- Designed from scratch.

CREATE TYPE settlement_status_enum AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED');

CREATE TABLE merchant_settlements (
    settlement_id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),  -- = batch_id
    merchant_account_id       UUID NOT NULL,
    settlement_window_start     TIMESTAMPTZ NOT NULL,
    settlement_window_end        TIMESTAMPTZ NOT NULL,
    total_transaction_count       INTEGER NOT NULL CHECK (total_transaction_count <= 100000),  -- FR-006 ceiling
    processed_count                 INTEGER NOT NULL DEFAULT 0,
    failed_chunk_count               INTEGER NOT NULL DEFAULT 0,
    total_amount                      NUMERIC(18,4) NOT NULL,
    status                              settlement_status_enum NOT NULL DEFAULT 'PENDING',
    created_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at                           TIMESTAMPTZ,

    CONSTRAINT fk_settlements_merchant FOREIGN KEY (merchant_account_id) REFERENCES accounts(account_id)
);

-- Citus: distributed by merchant_account_id — co-located with accounts so
-- that settlement-status lookups for a given merchant are shard-local.
SELECT create_distributed_table('merchant_settlements', 'merchant_account_id', colocate_with => 'accounts');

-- Indexes
CREATE INDEX idx_settlements_status_processing ON merchant_settlements (settlement_id)
    WHERE status IN ('PENDING', 'PROCESSING');  -- partial index for the
                                                   -- settlement scheduler's
                                                   -- resume-on-restart query
CREATE INDEX idx_settlements_merchant_window ON merchant_settlements (merchant_account_id, settlement_window_start DESC);