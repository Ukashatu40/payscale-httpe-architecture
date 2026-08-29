# ADR-002: Use PostgreSQL + Citus over CockroachDB and TiDB

**Status:** Accepted

## Context

The current database (PostgreSQL 15, single primary) is the system's most critical bottleneck: BN-001 shows connection pool exhaustion at just 1,800 TPS, and BN-006 shows a 15% deadlock rate from row-level lock contention on the accounts table — both far below the 12,000 TPS target. The redesign requires a database layer that (1) supports horizontal write scaling to 12,000+ TPS, (2) preserves ACID guarantees and serializable isolation where required for financial correctness (A1.2, A5.4), (3) supports the OCC-based concurrency model (FR-009) rather than relying on pessimistic locking, and (4) keeps all data within India (NFR-010). Given the $45,000/month budget ceiling and the stated team expertise (Java/Kotlin + PostgreSQL, per the CTO brief in A3.3), the technology choice also carries a real operational-risk cost if it requires the team to learn an unfamiliar distributed database from scratch under a 15-day deadline.

## Decision

**Adopt PostgreSQL 15+ with the Citus extension**, sharded across multiple worker nodes with hash-based distribution on `account_id` (finalized with full math in `docs/06-sharding-strategy.md`), each worker running standard PostgreSQL streaming replication (1 primary + 2 replicas per shard, matching the RF=3 pattern used elsewhere in this architecture for consistency).

This choice is deliberately architected to change the _least_ about the team's existing operational model: Citus is a PostgreSQL extension, not a replacement engine — `pg_dump`, `pg_upgrade`, standard PostgreSQL monitoring tools, and the team's existing SQL and query-tuning knowledge all carry over directly. The distributed-systems-specific surface the team must newly learn is narrowed to Citus's shard-rebalancing and distributed-query-planning behavior, rather than an entirely new consensus-based storage engine (Raft, in both alternatives below).

OCC is implemented at the application layer via a `version` column (per the brief's reference `accounts` schema) using standard `UPDATE ... WHERE version = $expected` conditional writes — this pattern works identically whether running against vanilla PostgreSQL or a Citus-distributed table, which further reduces migration risk.

## Alternatives Considered

| Option          | Why Rejected                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CockroachDB** | Strong technical fit for global distributed ACID transactions, but its Raft-consensus-per-write model adds latency overhead that competes with the 30ms p50 budget, and its operational model (range splitting, lease transfers, gateway node routing) is a genuinely new discipline the team has no experience with. For a 15-day deadline, this is a materially higher execution-risk choice than extending a database the team already runs in production. |
| **TiDB**        | Similar rejection logic to CockroachDB — strong distributed SQL engine, but introduces a three-tier operational model (TiDB/TiKV/PD) with no overlap with the team's PostgreSQL experience, and a smaller operational community in the Indian fintech context specifically (relevant given RBI compliance support and vendor familiarity).                                                                                                                    |

Both alternatives score lower specifically on the expertise-weighted criterion in `docs/02-technology-evaluation.md` (16.0 and 15.0 vs. Citus's 24.5) — this is not a close call the way the Kafka decision was, because unlike Kafka (which the assignment itself recommends and has no less-risky equivalent for the throughput requirement), Citus directly preserves the team's existing database competency while still delivering horizontal scale.

## Consequences

**Positive:** Directly resolves BN-001 (connection exhaustion) via PgBouncer + sharded write distribution, and BN-006 (lock contention) via the OCC model replacing row-level pessimistic locks. Near-zero relearning curve for the team's core database skill set. Full PostgreSQL feature set (CHECK constraints, partial indexes, MVCC, native partitioning for time-based transaction archival) remains available per-shard.

**Trade-offs / accepted technical debt:** Cross-shard transactions (a P2P payment between accounts on different shards) do not get native distributed-transaction support the way CockroachDB/TiDB would provide — this pushes complexity into the application-level Saga orchestration layer (see ADR-007, cross-shard transaction strategy, Day 6). This is an accepted trade-off: it moves complexity to a layer the team can reason about explicitly (an orchestrator they control and can debug) rather than hiding it inside a black-box distributed consensus engine they don't yet understand.

## Compliance

Citus workers are deployed exclusively within ap-south-1 (Mumbai), satisfying RBI Data Localization Directive (2018) data-residency requirements. Standard PostgreSQL WAL-based replication and point-in-time recovery satisfy the 2-year hot-data-retention requirement (Payment Aggregator Guidelines 2020) when paired with the archival/partitioning strategy detailed in docs/05.
