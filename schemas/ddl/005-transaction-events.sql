-- schemas/ddl/005-transaction-events.sql
-- Designed from scratch. This IS the event-sourcing log for saga state
-- transitions (A1.4 Event Sourcing) and doubles as the immutable audit trail
-- for the orchestration layer specifically (transactions.status is the
-- current-state view; transaction_events is the full history).

CREATE TYPE event_type_enum AS ENUM ('STATE_TRANSITION', 'COMPENSATION', 'RETRY');

CREATE TABLE transaction_events (
    event_id        UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    transaction_id    UUID NOT NULL,
    saga_id            UUID NOT NULL,
    from_state          VARCHAR(50),          -- NULL for the initial event
    to_state             VARCHAR(50) NOT NULL,
    event_type            event_type_enum NOT NULL DEFAULT 'STATE_TRANSITION',
    actor                  VARCHAR(100) NOT NULL,   -- which service emitted this
                                                       -- (e.g., 'payment-processing-svc')
    payload                 JSONB DEFAULT '{}',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
                                                       -- append-only, no updated_at

    CONSTRAINT fk_events_transaction FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

-- Co-located with transactions for shard-local writes on the hot path
-- (every saga step writes an event here).
SELECT create_distributed_table('transaction_events', 'transaction_id', colocate_with => 'transactions');

REVOKE UPDATE, DELETE ON transaction_events FROM app_write_role;

-- Indexes
CREATE INDEX idx_events_saga_id_created ON transaction_events (saga_id, created_at ASC);
    -- primary access pattern: "replay the full saga history in order" —
    -- used both by the orchestrator's crash-recovery sweep and by audit queries
CREATE INDEX idx_events_transaction_id ON transaction_events (transaction_id, created_at ASC);