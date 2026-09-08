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

## 8. Contradictions Flagged and Resolved

Tracked here through resolution so the audit trail is visible, not deleted once closed:

1. **Fraud latency budget (15ms allocated vs 25ms ML model cost).** ✅ **RESOLVED Day 9.** Two-stage design (`docs/09` §3): Stage 1 deterministic rules (3-5ms) handle the majority of volume; Stage 2 ML inference is reserved for the uncertain minority and given a genuine ≤25ms allocation, made possible by tightening other stages' budgets (`load-tests/performance-budget.md`). Bounded fallback via CB-FRAUD's existing semantics if Stage 2 still overruns.
2. **Zero RPO vs 99.99% availability under network partition.** ✅ **RESOLVED Day 3.** Explicit CP/AP split by subsystem (`docs/03`, Cross-Cutting section): ledger writes are CP, balance-display reads and reconciliation are AP. The two properties apply to different subsystems, not the whole system uniformly.
3. **"Exactly-once" terminology precision.** ✅ **RESOLVED Day 7.** `docs/07` §4 distinguishes exactly-once _producer_ semantics (Kafka native) from end-to-end exactly-once _business effects_ (requires idempotent consumers, implemented separately) — not conflated.

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
