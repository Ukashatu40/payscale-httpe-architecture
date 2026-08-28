# Requirements Traceability Matrix

**Purpose:** Every requirement in the HTTPE brief, traced to its deliverable, evidence, and failure mode. Built Day 1, updated as documents are produced. No requirement in this file is invented — each row cites its source section/page.

Legend: **M** = Mandatory (MUST), **S** = Should, **B** = Bonus

---

## Functional Requirements

| ID     | Requirement                                           | Source     | Pri | Deliverable                                                         | Evidence Required                                                  | Validation Method                                                              | Failure Mode if Missed                                  |
| ------ | ----------------------------------------------------- | ---------- | --- | ------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------- |
| FR-001 | Atomic P2P payments (debit/credit/ledger)             | A4.1, p.10 | M   | docs/03, docs/08, pseudocode/saga-orchestrator.py                   | Sequence diagram + saga pseudocode showing atomicity across shards | Trace happy path + 3 failure scenarios                                         | ARB Q2 exposes gap if compensation logic isn't concrete |
| FR-002 | Idempotent submission (24hr TTL client keys)          | A4.1, p.10 | M   | pseudocode/idempotency-handler.py, docs/05 (idempotency_key column) | Redis-backed TTL demo                                              | Unit-level trace                                                               | Duplicate charge on retry                               |
| FR-003 | Exactly-once delivery semantics                       | A4.1, p.10 | M   | docs/07 (outbox pattern lifecycle)                                  | Full failure-window enumeration                                    | Consumer dedup logic reviewed                                                  | Duplicate business effects (double credit/debit)        |
| FR-004 | Immutable audit trail, RBI compliant                  | A4.1, p.10 | M   | docs/05 (transaction_events, append-only)                           | Schema + retention policy                                          | Verify no UPDATE/DELETE paths on audit tables                                  | Regulatory non-compliance                               |
| FR-005 | Auto reversal within 30s                              | A4.1, p.10 | M   | docs/04 (failover flow), docs/08                                    | Saga compensation timing budget                                    | Timing math in perf budget                                                     | RTO breach                                              |
| FR-006 | Batch merchant settlement, up to 100K txns            | A4.1, p.10 | S   | docs/05 (merchant_settlements), separate flow doc                   | Chunked/resumable processing design                                | Distinct from per-txn saga model (see Contradiction #4 in docs/00-assumptions) | Batch treated as giant atomic saga — unrealistic        |
| FR-007 | Fraud detection within 15ms                           | A4.1, p.10 | S   | docs/09, load-tests/performance-budget.md                           | Performance budget breakdown                                       | Resolves ARB Q4 trap explicitly                                                | Silent latency budget overrun                           |
| FR-008 | Real-time status via webhooks, sub-second             | A4.1, p.10 | M   | api/openapi.yaml (webhook endpoints)                                | OpenAPI spec section                                               | Swagger validation                                                             | —                                                       |
| FR-009 | OCC for balance updates, version vectors              | A4.1, p.10 | M   | pseudocode/occ-balance-update.py, docs/08                           | Formal correctness proof (version timeline)                        | Prove write-skew prevention                                                    | Double-spend / lost update                              |
| FR-010 | Separate available/ledger balance, <500ms consistency | A4.1, p.10 | M   | docs/05 (accounts schema)                                           | Column definitions + reconciliation cadence                        | —                                                                              | —                                                       |

## Non-Functional Requirements

| ID      | Requirement                   | Source     | Pri | Deliverable                               | Evidence Required                     | Validation Method                 | Failure Mode if Missed                            |
| ------- | ----------------------------- | ---------- | --- | ----------------------------------------- | ------------------------------------- | --------------------------------- | ------------------------------------------------- |
| NFR-001 | 12K sustained / 18K burst TPS | A4.2, p.10 | M   | docs/12 (capacity plan)                   | Instance count math per service       | Traced to docs/00 constants       | Capacity plan doesn't reconcile with sharding doc |
| NFR-002 | p50 ≤30ms                     | A4.2, p.11 | M   | load-tests/performance-budget.md          | Stage-by-stage budget summing ≤30ms   | —                                 | Budget totals exceed target silently              |
| NFR-003 | p99 ≤100ms                    | A4.2, p.11 | M   | same                                      | same                                  | —                                 | —                                                 |
| NFR-004 | p99.9 ≤250ms                  | A4.2, p.11 | M   | same                                      | same                                  | —                                 | —                                                 |
| NFR-005 | 99.99% availability           | A4.2, p.11 | M   | docs/03 (CP/AP split per subsystem)       | CAP-theorem-aware design statement    | —                                 | Contradicts RPO=0 claim without explanation       |
| NFR-006 | RTO 30s/5min                  | A4.2, p.11 | M   | docs/09 (fault tolerance)                 | Failover timing per component         | Chaos experiment CE-001 validates | —                                                 |
| NFR-007 | RPO = 0                       | A4.2, p.11 | M   | docs/03, ADR on consistency model         | Sync replication trade-off discussion | —                                 | Unaddressed availability cost                     |
| NFR-008 | 11 nines durability           | A4.2, p.11 | M   | docs/05 (WAL, replication config)         | —                                     | —                                 | —                                                 |
| NFR-009 | TLS 1.3 / AES-256 / mTLS      | A4.2, p.11 | M   | docs/03 (security controls per component) | —                                     | —                                 | —                                                 |
| NFR-010 | Data residency (India)        | A4.2, p.11 | M   | docs/00 (ap-south-1 assumption), docs/06  | —                                     | —                                 | —                                                 |
| NFR-011 | 50,000 concurrent WebSocket   | A4.2, p.11 | M   | docs/03 (Notification Service scaling)    | Connection capacity math              | —                                 | —                                                 |
| NFR-012 | Cold start ≤90s               | A4.2, p.11 | M   | docs/03 (auto-scaling group config)       | —                                     | —                                 | —                                                 |

## Required Architecture Components (13)

| Component                  | Source     | Deliverable                              | Evidence Required                               |
| -------------------------- | ---------- | ---------------------------------------- | ----------------------------------------------- |
| API Gateway                | A4.3, p.11 | docs/03                                  | Tech choice + rate-limit + canary justification |
| Load Balancer              | A4.3, p.11 | docs/03                                  | L7 balancing, health checks, session affinity   |
| Transaction Orchestrator   | A4.3, p.11 | docs/03, pseudocode/saga-orchestrator.py | Saga state machine design                       |
| Payment Processing Service | A4.3, p.11 | docs/03                                  | Balance validation, fee calc                    |
| Account Service            | A4.3, p.12 | docs/03, docs/05                         | Dedicated DB partition                          |
| Notification Service       | A4.3, p.12 | docs/03                                  | WebSocket + push + SMS design                   |
| Fraud Detection Service    | A4.3, p.12 | docs/03, docs/09                         | 15ms SLA design                                 |
| Reconciliation Service     | A4.3, p.12 | docs/03                                  | Double-entry verification                       |
| Audit & Compliance Service | A4.3, p.12 | docs/03                                  | PII masking, append-only                        |
| Kafka / Event Bus          | A4.3, p.12 | docs/07                                  | Full topology                                   |
| Database Layer             | A4.3, p.12 | docs/05, docs/06                         | ACID + sharding                                 |
| Cache Layer                | A4.3, p.12 | docs/03, adrs/005                        | Redis Cluster design                            |
| Observability Stack        | A4.3, p.12 | docs/03                                  | Prometheus/Grafana/Jaeger                       |

**Note (Section 4 of strategy):** every component doc must show interaction with at least 2 others — isolated component descriptions are explicitly penalized.

## Database Schema Entities (8)

| Entity               | Source                                | Detail Level Required                     | Status                              |
| -------------------- | ------------------------------------- | ----------------------------------------- | ----------------------------------- |
| accounts             | A4.4, p.12 (fully specified in brief) | Reference-level                           | To replicate exactly per brief spec |
| transactions         | A4.4, p.13 (fully specified in brief) | Reference-level                           | To replicate exactly per brief spec |
| ledger_entries       | A4.4, p.14                            | Equivalent rigor — not specified in brief | Must design from scratch            |
| users                | A4.4, p.14                            | Equivalent rigor                          | Must design from scratch            |
| transaction_events   | A4.4, p.14                            | Equivalent rigor                          | Must design from scratch            |
| fraud_rules          | A4.4, p.14                            | Equivalent rigor                          | Must design from scratch            |
| merchant_settlements | A4.4, p.14                            | Equivalent rigor                          | Must design from scratch            |
| notification_log     | A4.4, p.14                            | Equivalent rigor                          | Must design from scratch            |

## ADRs — Mandatory (5) + Bonus (up to 3)

| ADR     | Topic                                                            | Source          | Bonus?   |
| ------- | ---------------------------------------------------------------- | --------------- | -------- |
| ADR-001 | Message queue: Kafka vs RabbitMQ vs SQS                          | A5.5, p.17      | No       |
| ADR-002 | Database sharding strategy: hash vs range vs geo                 | A5.5, p.17      | No       |
| ADR-003 | Concurrency control: optimistic vs pessimistic                   | A5.5, p.17      | No       |
| ADR-004 | Service comms: sync REST vs async vs hybrid                      | A5.5, p.17      | No       |
| ADR-005 | Cache invalidation: write-through vs write-behind vs cache-aside | A5.5, p.17      | No       |
| ADR-006 | Consistency model                                                | Suggested, p.17 | Yes (+5) |
| ADR-007 | Cross-shard transaction strategy                                 | Suggested, p.17 | Yes (+5) |
| ADR-008 | Fraud detection placement/latency strategy                       | Suggested, p.17 | Yes (+5) |

**Note:** Day 2/6/7/8 deliverables map ADR-001/002 → Day 2, ADR-003 (sharding — _numbered differently in Day 6 as "ADR-003 Sharding"_) → Day 6, ADR-004 (comms) → Day 7, ADR-005 (cache) → Day 8. **Flagging inconsistency:** A5.5's mandatory topic list numbers concurrency control as ADR-003 and sharding isn't in the 5 mandatory topics as worded — but Day 6 explicitly calls sharding "ADR-003." Resolution: follow the **Day-by-day (Part D) numbering** since it's the operational schedule — sharding = ADR-003, concurrency gets folded into ADR-004/005 discussion or added as bonus ADR. Documenting this explicitly rather than silently picking one, per Section 24 guidance.

## Bonus / Badge Opportunities (Section B5)

| Badge            | Requirement                               | Bonus | Planned?                                           |
| ---------------- | ----------------------------------------- | ----- | -------------------------------------------------- |
| ADR Master       | 5+ ADRs w/ quantitative analysis          | +15   | Yes — targeting 8                                  |
| Shard Wizard     | Distribution simulation w/ math proof     | +20   | Yes — simulations/shard-distribution-simulator.py  |
| Lock-Free Legend | OCC formal correctness argument           | +20   | Yes — evidence/occ-proof/                          |
| Kafka Conqueror  | Partition calc w/ throughput proof        | +10   | Yes — docs/07                                      |
| Chaos Champion   | 5+ chaos experiments, full structure      | +15   | Yes — docs/13                                      |
| Budget Hawk      | <$35K/month plan                          | +15   | Yes — docs/12                                      |
| API Artisan      | OpenAPI validates w/ zero errors          | +10   | Yes — validate in Swagger Editor before submission |
| FMEA Fanatic     | 25+ failure modes w/ RPN                  | +15   | Yes — docs/13                                      |
| Sprint Machine   | 15 daily milestones, Conventional Commits | +20   | Requires daily discipline                          |
| Perfectionist    | Self-assessment within 5% of reviewer     | +10   | Depends on calibration                             |
| Board Breaker    | 90%+ ARB score                            | +25   | Depends on Day 15 prep                             |

---

_This matrix will be revisited Day 14 as part of the master consistency audit._
