# Architecture Assumptions & Constants — Single Source of Truth

**Purpose:** Every number used in any other document in this repository must trace back to this file. Section 22 of the project brief explicitly penalizes cross-document contradictions (e.g., "sharding doc says 12 shards, capacity doc says 16"). If you change a number, change it here first, then update the consistency table at the bottom of this file.

**Status:** Living document — Day 1 draft, refined through Day 12.

---

## 1. Core Performance Targets (from NFR-001 to NFR-012, verbatim from brief)

| Constant                  | Value                           | Source  |
| ------------------------- | ------------------------------- | ------- |
| Sustained throughput      | 12,000 TPS                      | NFR-001 |
| Burst throughput          | 18,000 TPS for 15 min           | NFR-001 |
| Latency p50               | ≤30ms end-to-end                | NFR-002 |
| Latency p99               | ≤100ms end-to-end               | NFR-003 |
| Latency p99.9             | ≤250ms                          | NFR-004 |
| Availability              | 99.99% (52.6 min/yr downtime)   | NFR-005 |
| RTO — single component    | 30 seconds                      | NFR-006 |
| RTO — cascade             | 5 minutes                       | NFR-006 |
| RPO                       | Zero for committed transactions | NFR-007 |
| Durability                | 99.999999999% (11 nines)        | NFR-008 |
| WebSocket concurrency     | 50,000 connections              | NFR-011 |
| Cold start                | Full capacity within 90s        | NFR-012 |
| Fraud detection SLA       | 15ms (SHOULD, FR-007)           | FR-007  |
| Reversal time             | 30 seconds                      | FR-005  |
| Idempotency key TTL       | 24 hours                        | FR-002  |
| Merchant settlement batch | up to 100,000 txns              | FR-006  |

## 2. Scale Assumptions

| Constant                                   | Value                                                           | Confidence     | Note                                                                                                                                                                                                                  |
| ------------------------------------------ | --------------------------------------------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Monthly active users (target)              | 35,000,000                                                      | Given          | Projected                                                                                                                                                                                                             |
| Daily transaction volume (target)          | 85,000,000                                                      | Given          | Projected                                                                                                                                                                                                             |
| Current TPS                                | 1,200                                                           | Given          | Baseline                                                                                                                                                                                                              |
| **What counts toward "12,000 TPS"**        | **Committed financial write transactions only**                 | **ASSUMPTION** | Read traffic (balance checks, status polling) is treated as additive load, not part of the headline TPS figure. This assumption materially changes every downstream sizing calculation and must be stated in the HLD. |
| Peak-to-average ratio                      | 1.5x (burst/sustained = 18000/12000)                            | Given          | Matches NFR-001 directly                                                                                                                                                                                              |
| Transaction mix (assumed for load testing) | 60% P2P, 20% balance check, 10% merchant, 5% reversal, 5% other | Given          | Matches LT-007 scenario definition                                                                                                                                                                                    |

## 3. Budget Constants

| Constant                           | Value          |
| ---------------------------------- | -------------- |
| Budget ceiling                     | $45,000/month  |
| Budget optimization target (bonus) | <$35,000/month |
| Budget cut scenario (ARB Q6)       | $25,000/month  |
| Current budget                     | $12,000/month  |

## 4. Sharding Constants (finalized Day 6 — placeholder until then)

| Constant                     | Value                                   | Status                                         |
| ---------------------------- | --------------------------------------- | ---------------------------------------------- |
| Shard key                    | TBD — account_id (leading candidate)    | PENDING Day 6                                  |
| Shard count                  | TBD                                     | PENDING — must reconcile with §6 capacity math |
| Replication factor per shard | TBD (likely 3, matching Kafka RF below) | PENDING                                        |
| Hot-merchant mitigation      | TBD — dedicated shard/pool candidate    | PENDING                                        |

## 5. Kafka Constants (finalized Day 7 — placeholder until then)

| Constant                         | Value                                                                     | Status                             |
| -------------------------------- | ------------------------------------------------------------------------- | ---------------------------------- |
| Replication factor               | 3 (assumption, matches industry standard + FM-002 mitigation reference)   | ASSUMPTION                         |
| min.insync.replicas              | 2                                                                         | ASSUMPTION (standard RF=3 pairing) |
| Partition count (main txn topic) | TBD — calculated from required throughput / safe per-partition throughput | PENDING Day 7                      |

## 6. Regulatory Constraints (fixed, non-negotiable)

- All data resides within India (RBI Data Localization Directive 2018) → cloud region: **ap-south-1 (Mumbai)** assumed
- 2-year minimum hot data retention (Payment Aggregator Guidelines 2020)
- TLS 1.3 in transit, AES-256 at rest, mTLS between services (NFR-009, PCI-DSS v4.0)
- KYC compliance for all transacting parties

## 7. Team & Delivery Constraints (from CTO mission brief, A3.3)

- Team expertise: **Java/Kotlin + PostgreSQL** — this is a first-class architectural constraint, not a footnote. Any technology choice that ignores this needs strong justification (see ADR-001 for the Kafka-vs-team-experience trade-off explicitly raised in ARB Q3).
- Deadline: 15 days, non-negotiable
- Full technology autonomy, but every decision needs quantitative + trade-off justification

## 8. Open Contradictions Flagged for ARB Defense

These are **not yet resolved** — tracked here so every document references the same open question rather than silently picking different answers:

1. **Fraud latency budget (15ms allocated vs 25ms ML model cost)** — see `docs/09-fault-tolerance.md` for resolution options. Referenced directly in ARB Q4.
2. **Zero RPO vs 99.99% availability under network partition** — CP/AP split needs to be stated per-subsystem (ledger writes = CP, balance display reads = AP). See `docs/03-high-level-design.md`.
3. **"Exactly-once" terminology precision** — Kafka producer EOS ≠ end-to-end business-effect exactly-once. Corrected explicitly in `docs/07-message-queue-topology.md`.

---

## Consistency Tracking Table

_Update this row whenever a number below is used in another document, so a search for the constant's name finds every reference point._

| Constant              | Appears In                                      |
| --------------------- | ----------------------------------------------- |
| 12,000 / 18,000 TPS   | docs/03, docs/06, docs/07, docs/12, load-tests/ |
| $45,000 ceiling       | docs/12, adrs/002                               |
| Shard count           | docs/06, docs/12, adrs/003                      |
| Kafka partition count | docs/07, docs/12                                |
| RF=3, min.insync=2    | docs/07, docs/13 (FM-002)                       |
