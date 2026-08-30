<!-- docs/05-database-schema.md -->

# Database Schema Design

Full DDL: `schemas/ddl/001` through `008`. ERD: `schemas/erd/erd-diagram.dbml`.

## Where Financial Correctness Is Actually Enforced

Per Section 6's principle ("do not trust application validation alone"), correctness is layered — each layer catches what the layer above it could miss:

| Layer                 | Mechanism                                                                  | What it catches                                                                                                                                          |
| --------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API layer             | Request schema validation, amount > 0 check                                | Malformed client requests                                                                                                                                |
| Application layer     | Saga orchestration, OCC retry logic                                        | Concurrent-update races, cross-shard coordination                                                                                                        |
| Database constraints  | `CHECK (available_balance >= 0)`, `CHECK (amount > 0)`                     | Bugs in application logic that would otherwise write invalid state                                                                                       |
| Transaction isolation | OCC version column + conditional UPDATE                                    | Lost updates, write skew (A5.4)                                                                                                                          |
| Ledger invariants     | `check_ledger_balance()` deferred constraint trigger                       | Any code path (including future bugs) that inserts unbalanced debit/credit legs — this is the layer that survives even if the application layer is wrong |
| Reconciliation        | Async cross-account balance verification (docs/03, Reconciliation Service) | Systemic drift over time, not caught by any single-transaction check                                                                                     |
| Grants                | `REVOKE UPDATE, DELETE` on `ledger_entries` and `transaction_events`       | Any code (or operator) attempting to mutate audit history, even accidentally                                                                             |

The `check_ledger_balance()` trigger is the most important of these: it is a **database-enforced proof** that `sum(debits) = sum(credits)` per transaction, independent of whether the application code that inserted the rows was correct. A bug in the Payment Processing Service that inserted a debit without its matching credit would fail at COMMIT time, not silently corrupt the ledger.

## Indexing Strategy

| Table              | Index                                          | Query Pattern                                     | Benefit                                                                                                                | Downside / Write Amplification                                                                                                                         | Every Shard?                                           |
| ------------------ | ---------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------ |
| accounts           | `idx_accounts_status_active` (partial)         | "Find active accounts for X"                      | Smaller index than full-table; most accounts are ACTIVE so this mainly helps exclude FROZEN/CLOSED from hot-path scans | Minimal — partial indexes only update when status changes, which is rare                                                                               | Yes (per-shard)                                        |
| transactions       | `idx_transactions_idempotency_key`             | Idempotency check                                 | O(log n) lookup on every request                                                                                       | One extra index write per transaction insert — acceptable given this is the single most important lookup on the hot path                               | Yes                                                    |
| transactions       | `idx_transactions_status_processing` (partial) | Orchestrator's periodic sweep for in-flight sagas | Tiny index — most transactions are COMPLETED/FAILED, only the transient INITIATED/PROCESSING rows are indexed          | Rows enter/leave this index on every transaction, but the index itself stays small since transactions move through PROCESSING quickly                  | Yes                                                    |
| ledger_entries     | `idx_ledger_account_created`                   | "Statement for account X, most recent first"      | Directly serves the most common read (balance history)                                                                 | Composite index, moderate write cost per insert (2 writes per transaction — debit leg + credit leg)                                                    | Yes                                                    |
| transaction_events | `idx_events_saga_id_created`                   | Saga replay for crash recovery                    | Critical for RTO — this index is what makes the orchestrator's sweep fast enough to matter for the 30s target          | One insert per saga step — this table has the highest write:read ratio of any table in the schema, so keeping this to a single essential index matters | Yes                                                    |
| fraud_rules        | `idx_fraud_rules_active_priority` (partial)    | "Get active rules in priority order"              | Whole index typically fits in memory (dozens of rows)                                                                  | Negligible — rule set changes infrequently                                                                                                             | Reference table — replicated everywhere, not "sharded" |
| notification_log   | `idx_notification_status_failed` (partial)     | Retry worker's failed-notification sweep          | Keeps the retry query fast without scanning millions of DELIVERED rows                                                 | Small — FAILED is a minority status                                                                                                                    | Yes                                                    |

## Time-Based Partitioning: `transactions` and `ledger_entries`

Both tables are partitioned monthly using PostgreSQL native range partitioning (on `created_at`), applied _underneath_ the Citus distribution (each Citus shard is itself partitioned by month on the worker node):

```sql
-- Applied per-shard, illustrative for the transactions table:
CREATE TABLE transactions_y2026m10 PARTITION OF transactions
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
```

**Rationale:**

- Matches the **2-year hot data retention** requirement (Payment Aggregator Guidelines 2020) — partitions older than 24 months are moved to cold storage (archival, not deletion, since audit trails must remain retrievable) via a scheduled `DETACH PARTITION` + export job.
- Query performance: the overwhelming majority of reads target recent data (current-month balance checks, recent transaction history) — partition pruning means these queries never scan old partitions.
- Bounded index size per partition keeps the B-tree indexes above shallow and fast even as total historical data grows into the billions of rows implied by 85M daily transactions × 730 days.

## Hot-Row and Hot-Partition Risk

- **Hot row risk:** the `accounts` row for a high-volume merchant (Q1's 40%-of-traffic scenario) is updated on every single transaction touching that merchant — this is a genuine OCC contention point (frequent version-conflict retries), not just a sharding problem. Mitigated by the dedicated settlement-pool account pattern (transactions net against a pooled account rather than every merchant transaction updating the same row) — detailed further in `docs/06-sharding-strategy.md`.
- **Hot partition risk:** the current month's partition of `transactions` and `ledger_entries` receives effectively all write traffic — this is expected and acceptable (it's still spread across all Citus shards), but the current-month index maintenance cost is the dominant DB CPU cost, which is accounted for directly in the capacity plan (docs/12).

## Query Patterns and Expected Cardinality

| Query                        | Frequency                                  | Cardinality                                             |
| ---------------------------- | ------------------------------------------ | ------------------------------------------------------- |
| Idempotency check by key     | Once per transaction request (~12,000/sec) | 1 row                                                   |
| Account balance read (OCC)   | Twice per P2P transaction (debit + credit) | 1 row                                                   |
| Ledger statement for account | Low frequency (user-initiated)             | Tens to hundreds of rows, served by the composite index |
| Saga replay by saga_id       | Rare (only on crash recovery)              | Single-digit to low-double-digit rows per saga          |
| Settlement chunk processing  | Batch job, off-peak                        | Up to 1,000 rows per chunk query                        |
