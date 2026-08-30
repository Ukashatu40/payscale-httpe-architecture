-- schemas/ddl/003-ledger-entries.sql
-- Designed from scratch — equivalent rigor to reference entities per brief instruction.
-- Double-entry bookkeeping: every transaction produces exactly one DEBIT leg and
-- one CREDIT leg (or more, for fee-inclusive transactions). Rows are immutable —
-- corrections are new compensating entries, never UPDATE/DELETE (FR-004, A1.2).

CREATE TYPE ledger_entry_type_enum AS ENUM ('DEBIT', 'CREDIT');

CREATE TABLE ledger_entries (
    ledger_entry_id     UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    transaction_id       UUID NOT NULL,
    account_id            UUID NOT NULL,
    entry_type             ledger_entry_type_enum NOT NULL,
    amount                  NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    currency                CHAR(3) NOT NULL DEFAULT 'INR',
    balance_after           NUMERIC(18,4) NOT NULL,    -- snapshot at write time,
                                                          -- for point-in-time audit
                                                          -- reconstruction without
                                                          -- replaying the full event log
    entry_sequence           SMALLINT NOT NULL,          -- ordering within a
                                                          -- multi-leg transaction
                                                          -- (e.g., fee splits)
    reversal_of_entry_id      UUID,                       -- self-reference: set only
                                                          -- if this entry compensates
                                                          -- a prior entry
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
                                                          -- NOTE: no updated_at —
                                                          -- table is append-only by design

    CONSTRAINT fk_ledger_transaction FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id),
    CONSTRAINT fk_ledger_account FOREIGN KEY (account_id) REFERENCES accounts(account_id),
    CONSTRAINT fk_ledger_reversal FOREIGN KEY (reversal_of_entry_id) REFERENCES ledger_entries(ledger_entry_id)
);

-- Citus distribution: co-located with accounts (same distribution column and
-- shard count) so that "all ledger entries for account X" is always a
-- shard-local query — this is the dominant read pattern (balance
-- reconstruction, statement generation).
SELECT create_distributed_table('ledger_entries', 'account_id', colocate_with => 'accounts');

-- ENFORCE THE DATABASE-LEVEL INVARIANT: no UPDATE or DELETE, ever.
-- This is deliberately enforced at the database role/grant level, not just
-- left to application discipline (Section 6: "do not trust application
-- validation alone" for financial correctness).
REVOKE UPDATE, DELETE ON ledger_entries FROM app_write_role;

-- Deferred constraint trigger: at the end of each transaction, verify that
-- for every distinct transaction_id touched in that DB transaction,
-- sum(DEBIT amounts) = sum(CREDIT amounts). This is the literal enforcement
-- of the double-entry invariant stated in the project brief (Section 7):
--   sum(debits) = sum(credits)
CREATE OR REPLACE FUNCTION check_ledger_balance() RETURNS TRIGGER AS $$
DECLARE
    debit_total NUMERIC(18,4);
    credit_total NUMERIC(18,4);
BEGIN
    SELECT COALESCE(SUM(amount) FILTER (WHERE entry_type = 'DEBIT'), 0),
           COALESCE(SUM(amount) FILTER (WHERE entry_type = 'CREDIT'), 0)
    INTO debit_total, credit_total
    FROM ledger_entries
    WHERE transaction_id = NEW.transaction_id;

    IF debit_total <> credit_total THEN
        RAISE EXCEPTION 'Ledger imbalance for transaction %: debits=% credits=%',
            NEW.transaction_id, debit_total, credit_total;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_ledger_balance_check
    AFTER INSERT ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED   -- checked once at COMMIT, after all legs
                                     -- of the transaction have been inserted,
                                     -- not after the first row
    FOR EACH ROW EXECUTE FUNCTION check_ledger_balance();

-- Indexes
CREATE INDEX idx_ledger_transaction_id ON ledger_entries (transaction_id);
CREATE INDEX idx_ledger_account_created ON ledger_entries (account_id, created_at DESC);