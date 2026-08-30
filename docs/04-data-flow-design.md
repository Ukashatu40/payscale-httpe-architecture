<!-- docs/04-data-flow-design.md -->

# Data Flow Design — Critical Sequences

Covers the three required critical flows (Day 4): P2P Payment (happy path + 3 failure scenarios), Batch Merchant Settlement, and System Failover. Diagrams: `diagrams/p2p-payment-flow.puml`, `diagrams/batch-settlement-flow.puml`, `diagrams/failover-flow.puml`.

## P2P Payment Transaction

### Synchronous vs. asynchronous boundary

Everything up to and including the orchestrator's response to the client is **synchronous** — this is the part that must fit inside the 100ms p99 budget. Notification, audit logging, and reconciliation are **asynchronous**, fired via the Kafka outbox after the transaction is already durably committed. This split is deliberate: a slow or failed notification must never delay or fail a financial transaction (Section 6's principle — "do not trust application validation alone" extends here to "do not let non-financial side effects gate financial correctness").

### Happy path — key correctness properties

1. **Idempotency check happens before any state mutation.** The Redis `GET` for the idempotency key is the very first orchestrator action after receiving the request, so a duplicate request is caught before any debit/credit logic runs at all.
2. **OCC version checks on every write.** Both the debit (shard A) and credit (shard B) writes are conditional (`WHERE version = $expected`), directly implementing FR-009 and preventing the write-skew scenario described in A5.4.
3. **Ledger entries are created in the same orchestrator step that marks the transaction COMPLETED** — this keeps the audit trail (FR-004) and the transaction status consistent by construction, not by a follow-up reconciliation step.

### Failure Scenario 1 — Sender shard down (pre-commit failure)

**Directly answers ARB Q2.** The key correctness property here is that **no compensation is needed** — the failure occurs before the debit UPDATE commits, so there's no partial state to unwind. The detecting component is the `CB-DB-PRIMARY` circuit breaker on the Account Service's connection pool (2 failures/5s threshold, per the reference circuit breaker table), and its fallback is to route reads to the replica while queueing writes rather than failing immediately — this absorbs brief primary blips without user-visible failure, only escalating to a hard failure response once the queue/timeout is exhausted. The user sees an unambiguous message: no funds moved, safe to retry.

### Failure Scenario 2 — Destination shard down (post-commit failure, compensation required)

This is the harder case: the debit has already committed when the credit fails. The saga's compensating transaction (credit the sender back) is itself a new, auditable ledger-entry pair — never a silent rollback or row deletion, preserving FR-004's immutability requirement even during failure handling. This path must complete within the 30-second reversal SLA (FR-005), which is why the compensation step is triggered immediately by the orchestrator rather than deferred to a background job.

### Failure Scenario 3 — Client retry / duplicate idempotency key

This demonstrates FR-002 and FR-003 together: a client that never received its original response (e.g., its own network timeout) retries with the same idempotency key. Because the original transaction already completed and its result was cached in Redis under that key, the orchestrator returns the cached result directly without re-executing any debit/credit logic — this is what makes "exactly-once business effects" true in practice, not just in the glossary definition.

## Batch Merchant Settlement

Deliberately **not** modeled as a single all-or-nothing saga across up to 100,000 transactions (see the flagged design decision in `docs/00-assumptions-and-constants.md` — a monolithic saga at this scale would let one bad row block the entire batch, with no real correctness benefit). Instead: chunked processing (1,000 txns/chunk), where each chunk is independently committed, retried (bounded, exponential backoff + jitter), or marked failed for manual reconciliation — the batch as a whole tracks `COMPLETED` vs. `PARTIALLY_COMPLETED` status rather than treating any single-chunk failure as a full-batch failure.

## System Failover

Modeled directly against Chaos Experiment CE-001 (kill primary database node) so the design and the chaos-test success criteria are the same document, not two independently-invented numbers (avoiding the exact contradiction Section 22 warns about). Three points worth calling out:

1. **Fencing tokens prevent split-brain** if the old primary recovers mid-failover — this is the direct mitigation for FM-004 (network partition between AZs, RPN 108 in the reference FMEA table).
2. **The circuit breaker's fallback (queue writes, route reads to replica) is what makes the failover graceful** rather than a hard outage — writes aren't immediately rejected, they're queued for a bounded window while the new primary comes online.
3. **The Transaction Orchestrator's periodic sweep is what recovers in-flight sagas** — this is the same mechanism described in the HLD's Transaction Orchestrator failure-mode section (docs/03), applied here to the specific case of a shard-level primary failure rather than an orchestrator-instance crash.
