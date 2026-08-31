<!-- docs/07-message-queue-topology.md -->

# Message Queue Topology — Apache Kafka

Per `adrs/001-message-queue-selection.md`. All throughput figures trace to `docs/00-assumptions-and-constants.md`. This document also corrects one terminology precision issue flagged early in the project strategy (docs/00 §8, item 3): "exactly-once" is broken into its constituent guarantees explicitly in §4, not used loosely.

## 1. Topic Design

Kept deliberately consistent with the flows already established in `docs/03` and `diagrams/p2p-payment-flow.puml` — the Orchestrator emits **one combined outbox event per transaction** (not one event per saga step, not one event per ledger leg), so partition math below is driven directly by transaction count, not by an inflated per-leg or per-step multiplier.

| Topic                             | Purpose                                                                                                                                                                | Key                     | Partitions | Replication Factor | min.insync.replicas | Retention |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ---------- | ------------------ | ------------------- | --------- |
| `payments.transaction-events`     | Outbox events for txn.completed / txn.failed / txn.reversed (event_type field distinguishes them — one topic, not three, since consumers largely want the full stream) | `source_account_id`     | 16         | 3                  | 2                   | 7 days    |
| `settlement.batch-events`         | Batch settlement lifecycle (settlement.completed, settlement.partial)                                                                                                  | `merchant_account_id`   | 6          | 3                  | 2                   | 30 days   |
| `fraud.flags`                     | Transactions flagged for manual review by the fraud service                                                                                                            | `account_id`            | 4          | 3                  | 2                   | 90 days   |
| `payments.transaction-events.dlq` | Poison messages from the main topic after retry exhaustion                                                                                                             | (inherits original key) | 4          | 3                  | 2                   | 30 days   |
| `settlement.batch-events.dlq`     | Same, for settlement topic                                                                                                                                             | (inherits)              | 2          | 3                  | 2                   | 30 days   |
| `fraud.flags.dlq`                 | Same, for fraud topic                                                                                                                                                  | (inherits)              | 2          | 3                  | 2                   | 30 days   |

**On retention — a precision correction:** Kafka's 7-day retention on the main topic is _not_ PayScale's regulatory 2-year hot-retention mechanism. That requirement (Payment Aggregator Guidelines 2020) is satisfied by PostgreSQL's monthly partitioning strategy (`docs/05`), which is the actual system of record. Kafka here is a transport and short-term replay log for consumers — sizing its retention for the regulatory window would be both unnecessary (consumers don't need 2-year replay) and expensive (2 years of retained topic data at 12,000+ events/sec is a very large, pointless storage cost). This distinction matters and is stated explicitly rather than left ambiguous.

## 2. Partition Count — Calculated, Not Guessed

**Formula:** `partitions = ceil(required_throughput / safe_throughput_per_partition) × headroom_multiplier`

**Safe throughput per partition (assumption, documented):** 2,000 messages/sec. This reflects small JSON payloads (~500B–1KB per transaction event), `acks=all` with `min.insync.replicas=2` (durability-first configuration, consistent with the RPO=0 target), and leaves margin below Kafka's typically-cited per-partition ceiling (which varies widely by message size and disk — 2,000/sec is a conservative planning figure appropriate for a financial system that will not tune away durability guarantees for extra throughput).

### `payments.transaction-events`

Peak transaction volume (burst) = 18,000 TPS
One outbox event per transaction (established in docs/03/04 — not per leg, not per saga step)

Minimum partitions = ceil(18,000 / 2,000) = 9

Headroom multiplier: 1.33 (same convention applied consistently to the shard-count
calculation in docs/06, for the same reason — hash-key distribution variance +
uneven producer batching in practice)

9 × 1.33 = 11.97 → round to 16 (power of 2, consistent with the shard-count
rounding convention and gives clean consumer-group divisibility, see §3)

**Result: 16 partitions.** Utilization check: 18,000 events/sec ÷ 16 partitions = 1,125 events/sec/partition = **56% of the 2,000 safe-throughput assumption** — comfortable headroom, not running at the ceiling.

### `settlement.batch-events`

Not throughput-driven (settlement runs as scheduled batch jobs, not continuous real-time load) — sized instead for consumer parallelism during a batch run: **6 partitions**, matching the expectation that at most a handful of settlement-worker instances process a batch window in parallel.

### `fraud.flags`

Assumption: ~2% of transactions get flagged for manual review (typical order of magnitude for rule-based fraud systems, not every transaction). At burst: 18,000 × 0.02 = 360 flags/sec → well under a single partition's safe throughput, but **4 partitions** chosen anyway for consumer parallelism on the manual-review-queue side (Audit & Compliance Service), not because throughput demands it.

## 3. Consumer Group Topology

`payments.transaction-events` (16 partitions) is consumed independently by three separate consumer groups — this is normal Kafka fan-out: each consumer group maintains its own offset and reads the full topic independently, they do not share or compete for partitions with each other (only consumers _within_ the same group divide partitions among themselves, per A5.2).

| Consumer Group                 | Instances | Partitions/Instance | Notes                                                                                                                                                       |
| ------------------------------ | --------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `notification-service-group`   | 4         | 4                   | Clean divisor of 16 — even load, matches docs/03's Notification Service scaling note                                                                        |
| `audit-service-group`          | 4         | 4                   | Even split                                                                                                                                                  |
| `reconciliation-service-group` | 2         | 8                   | Reconciliation is explicitly AP/eventually-consistent (docs/03) — fewer instances, larger per-instance batch is acceptable since it's off the critical path |

**Worked example of the alignment rule (A5.2: "adding more consumers than partitions provides no benefit"):** if `notification-service-group` were scaled to 5 instances against 16 partitions, the assignment would be uneven (16/5 = 3.2 → some instances get 4 partitions, one gets fewer, and a 6th instance added beyond 16 would receive **zero** partitions and sit idle). Consumer counts for this topic are therefore kept at divisors of 16 (1, 2, 4, 8, 16) specifically to avoid this — 4 instances per group is the chosen baseline because it balances parallelism against per-instance idle capacity.

## 4. Exactly-Once Semantics — Precisely Defined

Per the terminology correction flagged in docs/00: Kafka's `enable.idempotence=true` and transactional producers give **exactly-once producer semantics** — this deduplicates a producer's own retried publish attempts at the broker level. It does **not**, by itself, guarantee **end-to-end exactly-once business effects** (e.g., "the user receives exactly one notification"), which additionally requires idempotent consumers. Both layers are implemented here; neither is sufficient alone.

### Outbox Pattern lifecycle

1. DB transaction: Orchestrator INSERTs the outbox row (event_type, payload,
   published=false) in the SAME PostgreSQL transaction as the ledger_entries
   INSERT and the transactions.status UPDATE (docs/03, docs/05) — this is
   what solves the dual-write problem: the outbox row's existence is atomic
   with the domain state change, by construction, not by best-effort
   coordination between two separate systems.
2. Domain state change: transaction COMMITTED in PostgreSQL, outbox row
   durable alongside it.
3. Outbox publisher: a separate polling process (or CDC via logical
   replication — polling chosen here for simplicity given the team's
   PostgreSQL familiarity, per the same expertise-fit reasoning as ADR-002)
   reads unpublished outbox rows in created_at order.
4. Publish to Kafka: producer configured with enable.idempotence=true and a
   transactional.id scoped to the outbox publisher process, publishing the
   event keyed by source_account_id.
5. Consumer processing: each of the three consumer groups processes the
   event idempotently (see failure-window table below).
6. Downstream state: e.g. Notification Service writes to notification_log
   (docs/05), Audit Service writes to its append-only store, Reconciliation
   Service updates its verification state.

### Failure windows — enumerated explicitly

| Failure point                                                                                             | What happens                                                                                                                                                                                                                                                                            | Why it's still safe                                                                                                                                                                                                                                                                                                                                                                         |
| --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DB commit succeeds, process crashes before publisher runs                                                 | Outbox row is durable in PostgreSQL (already committed) — publisher picks it up on next poll after restart                                                                                                                                                                              | No loss — row exists regardless of process crash, this is the entire point of the outbox pattern                                                                                                                                                                                                                                                                                            |
| Outbox publisher reads a row, publishes to Kafka, crashes **before** marking the row `published=true`     | On restart, publisher re-reads the same row (still `published=false`) and republishes                                                                                                                                                                                                   | This is a genuine duplicate _publish call_, not just a producer-level retry — Kafka's idempotent-producer dedup (which keys off producer ID + sequence number for retries of the _same_ send) does not by itself catch this, since it's a fresh publish, not a retry. **Backstop: the outbox row's own ID is included in the message headers**, and consumers dedupe against it (see below) |
| Consumer processes an event (e.g., sends notification) but crashes **before** committing its Kafka offset | On restart, the consumer group re-delivers the same message (at-least-once redelivery is Kafka's baseline guarantee without extra work)                                                                                                                                                 | Consumer-side idempotency: Notification Service checks `notification_log` for an existing row keyed on `(transaction_id, channel)` before sending — a redelivered event that already resulted in a sent notification is a no-op, not a duplicate send                                                                                                                                       |
| Consumer receives a genuine duplicate (from either of the two cases above)                                | Same idempotent-write pattern applies uniformly                                                                                                                                                                                                                                         | The dedup mechanism doesn't care _why_ the duplicate arrived — it only cares whether the effect has already happened                                                                                                                                                                                                                                                                        |
| Kafka broker-level transient failure, producer retries                                                    | Idempotent producer (`enable.idempotence=true`) deduplicates automatically via producer ID + sequence number                                                                                                                                                                            | This is the one case Kafka's built-in EOS producer feature fully solves without any application-level work                                                                                                                                                                                                                                                                                  |
| Downstream service partially commits (e.g., Reconciliation updates 2 of 3 related rows then crashes)      | Reconciliation's own writes are wrapped in a single local DB transaction per event — a partial-commit crash means the whole local transaction rolls back, and the Kafka offset for that event was never committed either, so redelivery retries the full local transaction from scratch | Standard "process, then commit offset" ordering — offset commit is the last step, ensuring redelivery on any earlier failure                                                                                                                                                                                                                                                                |

**Net result:** duplicate _business effects_ (double notification, double audit entry, double reconciliation count) cannot occur, because every consumer's write path is idempotent against a durable, checkable key — not because duplicates never arrive (they can, and the design assumes they will).

## 5. Dead Letter Queue Handling

Each consumer group retries a failed message processing attempt up to **3 times**, with exponential backoff + jitter (base 200ms, doubling, ±20% jitter — same retry-policy shape used in `pseudocode/circuit-breaker.py`, Day 9, for consistency across the codebase). After retry exhaustion, the message is published to the corresponding `.dlq` topic with added metadata: original topic, partition, offset, consumer group, exception summary, and retry count.

DLQ topics are monitored (`kafka_consumer_lag` metric, per A5.6, applied to DLQ topics specifically with a lower alert threshold — even a small DLQ depth warrants investigation, unlike the main topic's 10,000-message lag threshold) and are consumed by an operations tooling process for manual inspection and reprocessing — never auto-retried indefinitely, which would risk masking a genuine, persistent bug behind infinite retries.
