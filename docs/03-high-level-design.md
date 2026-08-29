<!-- docs/03-high-level-design.md -->

# High-Level Design — PayScale HTTPE

Covers all 13 required architecture components (A4.3). Each component specifies responsibility, interfaces (sync/async), technology choice with justification, scaling model, capacity assumption, latency budget, failure modes, recovery behavior, security controls, observability, and — per Section 4 of the project strategy — explicit interaction with at least two other components, so no component is described as an isolated box.

All numeric claims below trace to `docs/00-assumptions-and-constants.md`. Diagram: `diagrams/system-architecture.mermaid`.

---

## 1. API Gateway Layer

**Responsibility:** Request routing, JWT authentication, rate limiting per account tier (BASIC 50 TPS / PREMIUM 200 / MERCHANT 1000, per the accounts schema), SSL termination, canary deployment routing.

**Interfaces:** Synchronous HTTPS from clients (inbound). Synchronous gRPC/HTTP to Transaction Orchestrator (outbound). Synchronous Redis GET for rate-limit counters.

**Technology:** Envoy Proxy — chosen over Kong for lower p99 tail latency under high concurrency (Envoy's C++ core vs. Kong's Lua/OpenResty layer) and native gRPC support, which the internal service mesh uses.

**Scaling model:** Horizontally auto-scaled, stateless, 4-64 instances (matches the brief's auto-scaling range for app servers).

**Capacity assumption:** At 12,000 TPS with ~3 hops of gateway-level work per transaction (auth, rate-limit, route), each instance handles ~750 req/s comfortably within Envoy's documented per-core throughput; 4 instances at 12K TPS provides headroom, scaling to cover the 18K burst.

**Latency budget:** 3-5ms (matches reference budget — SSL offload + in-memory routing).

**Failure modes:** Instance crash → ALB health check removes from rotation within 10s, no data loss (stateless). Rate-limiter Redis unavailable → circuit breaker CB-CACHE fails open with a conservative default rate limit rather than blocking all traffic (fail-safe, not fail-closed, since blocking all traffic on a cache miss would itself violate the 99.99% availability target).

**Recovery:** New instances join the ALB target group automatically; no state to restore.

**Security controls:** TLS 1.3 termination, mTLS to internal orchestrator, JWT signature validation with cached public keys (2-3ms budget line).

**Observability:** `txn_requests_total` by status/type/source (per A5.6 metric spec).

**Interacts with:** Load Balancer (upstream), Transaction Orchestrator (downstream), Redis (rate-limit counters).

---

## 2. Load Balancer

**Responsibility:** L7 balancing across API Gateway instances, health checks, connection draining during deploys.

**Technology:** AWS ALB — native integration with auto-scaling groups and health checks; NLB rejected since L7 routing (path-based, header-based) is needed for canary deployments, which NLB (L4) cannot do.

**Scaling model:** AWS-managed, scales automatically.

**Failure modes:** AZ failure → ALB is inherently multi-AZ; traffic reroutes to healthy AZ within seconds, well inside the 30s single-component RTO.

**Interacts with:** API Gateway (downstream), external DNS/clients (upstream).

---

## 3. Transaction Orchestrator

**Responsibility:** Saga orchestration for P2P payments, idempotency key checking, compensation logic on failure, saga state persistence for crash recovery.

**Interfaces:** Synchronous from API Gateway (inbound). Synchronous to Payment Processing Service and Fraud Detection Service. Asynchronous outbox write to Kafka for saga state transitions.

**Technology:** Custom state machine (Java/Kotlin), not Temporal.io. **Rationale (directly tied to ADR-004):** Temporal adds a new operational dependency (Temporal server cluster) and a new programming model (workflow-as-code with replay semantics) that the team has zero experience with, under the same 15-day constraint logic applied to the Kafka decision. A custom state machine, backed by the `transaction_events` table for state persistence, is slower to build initially but fully owned and debuggable by a team that already knows Java/Kotlin and PostgreSQL — directly mirroring the reasoning in ADR-002.

**Scaling model:** Stateless compute (state lives in PostgreSQL, not in-process), horizontally scaled 8-64 instances.

**Capacity assumption:** 12,000 TPS ÷ 8 instances (baseline) = 1,500 orchestration ops/sec/instance — well within a JVM state-machine's capability given each op is CPU-bound coordination logic, not blocking I/O (all downstream calls are within budgeted latency windows).

**Latency budget:** Coordination overhead ~1-2ms (business logic line in reference budget); actual wall-clock time dominated by downstream calls it awaits.

**Failure modes:** Orchestrator crashes mid-saga → in-flight saga state was already persisted to `transaction_events` before each step; a new orchestrator instance picks up incomplete sagas via a periodic sweep and either resumes or compensates, based on the last recorded state. This directly answers ARB Q2's mid-transaction failure scenario (full sequence walkthrough in `docs/04-data-flow-design.md`).

**Recovery:** RTO 30s — sweep interval configured at 10s, so worst-case detection + resume is within budget.

**Security controls:** mTLS to all downstream services.

**Observability:** `saga_state_transitions_total` (from_state, to_state), alert on compensation rate >2%/5min (per A5.6).

**Interacts with:** API Gateway, Payment Processing Service, Fraud Detection Service, Kafka (outbox), PostgreSQL (saga state).

---

## 4. Payment Processing Service

**Responsibility:** Balance validation, debit/credit execution, currency handling, fee calculation.

**Interfaces:** Synchronous from Orchestrator. Synchronous to Account Service (balance read/write) and Fraud Detection Service.

**Technology:** Custom Java/Kotlin microservice — direct match to team expertise, no justification needed beyond that.

**Scaling model:** 12 instances baseline (per reference capacity table), stateless, horizontally scaled.

**Latency budget:** Business logic 1-2ms + DB read 3-5ms + DB write 8-15ms (largest single chunk of the budget — transactional write with fsync for durability, NFR-008).

**Failure modes:** Downstream Account Service unavailable → CB triggers, saga compensates (debit not applied), user sees "transaction failed, no funds moved" rather than an ambiguous state.

**Interacts with:** Transaction Orchestrator, Account Service, Fraud Detection Service.

---

## 5. Account Service

**Responsibility:** Account CRUD, balance management (available vs. ledger, FR-010), account freezing, tier management, per-tier rate limits.

**Technology:** Custom service with dedicated Citus shard routing logic — every account operation carries the `shard_key` column (hash(account_id) mod N) to route directly to the correct Citus worker, avoiding a cross-shard query on the hot path.

**Scaling model:** 6 instances baseline; scaling tracks Payment Processing Service since it's the primary caller.

**Latency budget:** Shares the DB read (3-5ms) / DB write (8-15ms) lines with Payment Processing Service — these are the same physical operations, attributed once in the end-to-end budget, not double-counted.

**Failure modes:** OCC version conflict on concurrent balance update → automatic retry with exponential backoff + jitter (max 3 retries per `pseudocode/occ-balance-update.py`, built Day 8); this is the direct fix for BN-006's 15% deadlock rate, since OCC retries don't hold locks the way pessimistic locking did.

**Interacts with:** Payment Processing Service, PostgreSQL+Citus, Redis (balance cache — read-through only, never authoritative).

---

## 6. Notification Service

**Responsibility:** Real-time transaction status via WebSocket (NFR-011, 50K concurrent connections), push, SMS, email.

**Technology:** Custom WebSocket gateway + Firebase/AWS SNS for push/SMS.

**Scaling model:** 3 instances baseline; WebSocket connections are sticky per-instance (session affinity at the LB), so scaling this service specifically tracks concurrent-connection count, not TPS.

**Capacity assumption:** 50,000 connections ÷ 3 instances ≈ 16,700 connections/instance — within typical event-loop WebSocket server capacity (Node.js/Netty-style servers handle 50K+ connections/instance at idle; the constraint here is memory per connection, not CPU).

**Failure modes:** CB-NOTIFY (per the brief's reference table): 5 failures/30s trips, notification queued for retry, transaction proceeds regardless — **notification failure never blocks the financial transaction**, an explicit architectural decision.

**Interacts with:** Kafka (consumes transaction-status events), Account Service indirectly (via events).

---

## 7. Fraud Detection Service

**Responsibility:** Rule engine + ML inference + velocity checks within the 15ms SLA (FR-007).

**Technology:** Custom rules engine + Redis feature store + ONNX runtime for local model inference (avoids a network hop to a separate inference service, which would consume latency budget).

**Scaling model:** 4 instances, 8 vCPU/32GB each (per reference capacity table — memory-heavy for feature caching).

**Latency budget:** 10-15ms allocated (feature lookup + inference). **This is the flagged contradiction (see docs/00-assumptions §8, item 1) — resolved fully in `docs/09-fault-tolerance.md` with the three-option latency-overrun response, directly answering ARB Q4.**

**Failure modes:** CB-FRAUD (3 failures/10s → 15s reset): allows transaction through with a manual-review flag rather than blocking all transactions — a deliberate choice that trades a small fraud-risk window for availability, justified because blocking all payments on fraud-service downtime would itself be a worse business outcome, and the manual-review queue provides after-the-fact recovery.

**Interacts with:** Payment Processing Service, Redis (feature store), Kafka (flags routed to Audit service for compliance).

---

## 8. Reconciliation Service

**Responsibility:** Double-entry verification (`sum(debits) = sum(credits)` invariant), cross-service balance reconciliation.

**Technology:** Custom service + dedicated analytics-read-replica of PostgreSQL (never queries the primary write path, to avoid competing with transactional load).

**Scaling model:** Runs as a scheduled/streaming consumer off Kafka, not synchronous — reconciliation is inherently an eventually-consistent, after-the-fact process (this is explicitly AP, not CP, per the CAP-split noted in docs/00).

**Failure modes:** Reconciliation lag during high load is acceptable (bounded staleness, tracked via a lag metric) — this is _not_ on the critical path and must never be treated as such.

**Interacts with:** Kafka (consumes ledger events), PostgreSQL read replica.

---

## 9. Audit & Compliance Service

**Responsibility:** Immutable logging (FR-004), regulatory reports, PII masking.

**Technology:** Custom service + append-only storage (a dedicated, INSERT-only PostgreSQL table set with no UPDATE/DELETE grants at the DB-role level — enforced at the database, not just the application, since Section 6 of the project strategy explicitly warns against trusting application validation alone for financial correctness).

**Failure modes:** Write failure here must never roll back the underlying financial transaction — audit writes are asynchronous (via Kafka), decoupled from the synchronous payment path, with their own DLQ for failed audit writes requiring manual reprocessing.

**Interacts with:** Kafka (consumes all transaction events), PostgreSQL (append-only audit tables).

---

## 10. Message Queue / Event Bus (Kafka)

**Responsibility:** Async inter-service communication, event sourcing backbone, DLQ management. Full topology in `docs/07-message-queue-topology.md` (Day 7) — this section covers only its role in the HLD.

**Technology:** Apache Kafka — per ADR-001.

**Interacts with:** Transaction Orchestrator (outbox producer), Notification/Reconciliation/Audit services (consumers).

---

## 11. Database Layer

**Responsibility:** ACID storage, read replicas, connection pooling, backups. Full schema in `docs/05`, sharding in `docs/06`.

**Technology:** PostgreSQL + Citus — per ADR-002. PgBouncer for connection pooling (addresses BN-001 directly: 200 max_connections → 2,000+ pooled connections).

**Interacts with:** Account Service, Payment Processing Service, Reconciliation Service, Audit Service.

---

## 12. Cache Layer

**Responsibility:** Hot data caching (never authoritative for balances), rate-limit counters, idempotency keys, fraud feature store, feature flags.

**Technology:** Redis Cluster, 6 nodes / 96GB total (per reference config) — per the Day 2 evaluation.

**Failure modes:** CB-CACHE (3 failures/5s → 20s reset): bypasses cache, queries DB directly. This is safe specifically _because_ Redis is never the source of truth for balances (Section 13 of the strategy: "Do not cache critical financial state in a way that can create incorrect balances") — a cache miss or outage degrades latency, never correctness.

**Interacts with:** API Gateway (rate limits), Fraud Detection (features), Transaction Orchestrator (idempotency keys), Account Service (balance cache, read-through only).

---

## 13. Observability Stack

**Responsibility:** Metrics, distributed tracing, logging, alerting, dashboards — per the full metric table in A5.6.

**Technology:** Prometheus + Grafana (metrics/dashboards), Jaeger (distributed tracing via OpenTelemetry, W3C Trace Context for HTTP + Kafka header injection for async spans), ELK/Loki (logs).

**Interacts with:** Every service above (scrapes metrics endpoints, receives trace spans).

---

## Cross-Cutting: CP vs. AP Split (resolving the RPO=0 / 99.99% availability tension)

Per the contradiction flagged in `docs/00-assumptions-and-constants.md` (§8, item 2):

- **CP (consistency over availability):** Ledger writes (Account Service → PostgreSQL primary), Saga state transitions. These paths use synchronous replication acknowledgment (min.insync.replicas semantics) and will reject a write rather than risk data loss during a partition.
- **AP (availability over consistency):** Balance display reads (via Redis cache or read replicas), Reconciliation Service, Notification delivery. These paths tolerate brief staleness in exchange for never blocking the user experience.

This split is what makes the 99.99% availability target compatible with RPO=0 — the two properties apply to _different subsystems_, not the whole system uniformly, matching the guidance in A1.4.
