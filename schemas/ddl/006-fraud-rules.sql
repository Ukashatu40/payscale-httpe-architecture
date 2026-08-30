-- schemas/ddl/006-fraud-rules.sql
-- Designed from scratch.

CREATE TYPE fraud_rule_type_enum AS ENUM ('VELOCITY', 'AMOUNT_THRESHOLD', 'PATTERN', 'BLACKLIST');
CREATE TYPE fraud_rule_action_enum AS ENUM ('BLOCK', 'FLAG_REVIEW', 'ALLOW');

CREATE TABLE fraud_rules (
    rule_id       UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    rule_name       VARCHAR(255) NOT NULL,
    rule_type         fraud_rule_type_enum NOT NULL,
    condition           JSONB NOT NULL,        -- structured rule definition,
                                                  -- e.g. {"max_txn_per_minute": 5}
    action                fraud_rule_action_enum NOT NULL,
    priority                INTEGER NOT NULL DEFAULT 100,   -- lower = evaluated first
    is_active                BOOLEAN NOT NULL DEFAULT true,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by                   VARCHAR(100) NOT NULL
);

-- Citus: reference table — rule set is small (dozens to low hundreds of rows)
-- and must be read on every single fraud-check call (15ms SLA budget has no
-- room for a cross-shard lookup), so it's replicated to every worker.
SELECT create_reference_table('fraud_rules');

CREATE TRIGGER trg_fraud_rules_updated_at
    BEFORE UPDATE ON fraud_rules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Note: in practice, the Fraud Detection Service caches this entire table in
-- its Redis feature store / in-process cache with a short TTL — this table
-- is the source of truth, not the read path on the hot transaction flow
-- (see docs/03, Fraud Detection Service section).
CREATE INDEX idx_fraud_rules_active_priority ON fraud_rules (priority ASC) WHERE is_active = true;