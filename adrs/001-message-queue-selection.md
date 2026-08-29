# ADR-001: Use Apache Kafka over RabbitMQ and Amazon SQS

**Status:** Accepted

## Context

PayScale's current message queue is single-node RabbitMQ, identified in the load test bottleneck report as BN-002 (CRITICAL): message ack backlog causing consumer lag exceeding 30 seconds at just 2,000 TPS — 6x below the 12,000 TPS target. The redesign requires a message queue capable of sustaining 12,000 TPS (bursting to 18,000) while supporting exactly-once delivery semantics for financial transactions (FR-003), the outbox pattern for the dual-write problem, and event sourcing for the immutable audit trail (FR-004). The queue also sits inside the critical path's Kafka-produce stage, budgeted at 2-5ms in the reference performance budget, so raw producer latency at scale is a hard constraint, not just steady-state throughput.

A material constraint not present in a typical greenfield decision: the existing engineering team has zero stated Kafka production experience, while they have RabbitMQ experience today. This is a genuine trade-off, explicitly raised in the ARB question bank ("If the team has zero Kafka experience and the Diwali deadline is non-negotiable, would you change your decision?") and is addressed directly below rather than glossed over.

## Decision

**Adopt Apache Kafka**, multi-broker cluster (minimum 3 brokers), replication factor 3, min.insync.replicas=2, deployed via a managed offering (e.g., MSK-equivalent in ap-south-1) to offset the operational-experience gap with vendor-managed broker administration, patching, and scaling.

Configuration baseline (finalized with partition math in Day 7 / docs/07):

- Idempotent producers enabled (`enable.idempotence=true`) on all producers writing financial events
- Transactional producer IDs used for the outbox publisher specifically, to support exactly-once semantics into the event bus
- Consumer groups sized to partition count per topic (over-provisioning consumers beyond partition count is explicitly avoided, per A5.2 guidance)
- Dead letter queues configured per consumer group for poison-message isolation

The team-experience gap is mitigated, not ignored: (1) a managed Kafka service removes broker-ops burden, leaving the team to learn only producer/consumer client code, which is a much smaller surface; (2) the 15-day timeline includes explicit ramp-up via the Day 2-4 window before Kafka-specific work begins Day 7; (3) RabbitMQ remains a documented fallback path in the Consequences section below if velocity risk materializes — this is a decision made with eyes open to its own reversal condition, not a permanent commitment regardless of evidence.

## Alternatives Considered

| Option                   | Why Rejected                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **RabbitMQ (clustered)** | Directly caused BN-002 in the current architecture. Clustering improves availability but each queue is still bound to a single-node throughput ceiling meaningfully below Kafka's per-partition parallelism model. No native exactly-once semantics — would require significant custom dedup logic to match what Kafka provides via idempotent + transactional producers. Retained as the _lowest-risk fallback_ given team familiarity, not the primary choice.                                                                                                              |
| **Amazon SQS (FIFO)**    | Fully managed, zero operational burden — genuinely attractive given the team's Kafka inexperience. Rejected primarily on two grounds: (1) at-least-once delivery only, requiring the same manual dedup burden as RabbitMQ without Kafka's native tooling; (2) FIFO SQS caps at 3,000 messages/sec per message group without batching, requiring careful message-group-key design to avoid becoming a new bottleneck at 12,000 TPS, and per-request network latency (typically 10-20ms) consumes a disproportionate share of the 30ms p50 budget when in the synchronous path. |

Scoring detail is in `docs/02-technology-evaluation.md`; Kafka's weighted score (22.5) is close to SQS (21.5) specifically because the expertise penalty is real — this was not a runaway win, and that closeness is itself the honest answer to "why not something simpler."

## Consequences

**Positive:** Kafka's partition model scales consumer throughput independently of broker count, directly resolving BN-002. Native EOS support materially simplifies the outbox pattern implementation for FR-003. Kafka's retention model doubles as a natural event-sourcing log for the audit trail (FR-004).

**Trade-offs / accepted technical debt:** The team will need dedicated ramp-up time (Days 2-6, before Kafka work begins Day 7) — this is time not spent hardening other components, and is an accepted cost. Managed Kafka has a cost premium over self-hosted RabbitMQ, reflected in the capacity plan (docs/12).

**Risk / fallback condition:** If integration testing in the Day 7-9 window reveals the team cannot reach basic producer/consumer competency, RabbitMQ with a manually-implemented outbox+dedup layer is the documented fallback, accepting the throughput ceiling as a known limitation to be revisited post-Diwali.

## Compliance

Kafka's replicated, persistent log satisfies the RBI data-residency requirement (NFR-010) when deployed entirely within ap-south-1, with no cross-region replication. Kafka's durable retention supports the 2-year hot-data-retention requirement from the Payment Aggregator Guidelines (2020) for transaction event history, subject to appropriate topic retention configuration (detailed in docs/07).
