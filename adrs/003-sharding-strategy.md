<!-- adrs/003-sharding-strategy.md -->

# ADR-003: Hash-Based Sharding on account_id with Consistent-Hashing Rebalancing

**Status:** Accepted

## Context

The current single-primary PostgreSQL instance is the system's dominant bottleneck (BN-001: connection exhaustion at 1,800 TPS; BN-006: 15% deadlock rate). Scaling to 12,000 TPS sustained (18,000 burst) requires horizontal write distribution. The sharding strategy must additionally survive the specific hot-partition scenario raised in ARB Q1 (a single merchant at 40% of transaction volume) and must not require a full data migration every time capacity needs to grow, given the 15-day delivery window doesn't allow for repeated expensive rebalancing operations during early operation.

## Decision

**Shard on `hash(account_id)`, using consistent hashing with virtual nodes (100/shard) as the routing mechanism**, initial deployment at **32 shards**, replication factor 3 per shard.

Full quantitative justification — including the executed shard-distribution simulation (`simulations/shard-distribution-simulator.py`) proving 0.52% distribution variance across 1M synthetic accounts, and the measured 97% vs. 3% rebalancing-cost gap between modulo and consistent hashing — is in `docs/06-sharding-strategy.md`.

Cross-shard P2P transactions (the norm, not the exception, under this key choice) are handled via application-level Saga orchestration rather than a database-native distributed transaction protocol — see ADR-007 for the full 2PC/Saga/TCC evaluation.

## Alternatives Considered

| Option                                            | Why Rejected                                                                                                                                                                                                                         |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| user_id sharding                                  | No advantage over account_id for the dominant P2P query pattern (transfers between different users remain cross-shard regardless); adds indirection since a user can hold multiple accounts                                          |
| Geographic sharding                               | PayScale's data residency requirement (India-only) collapses to a single region already — there is no geographic axis left to shard on that provides locality benefit, while introducing real population-distribution imbalance risk |
| Plain modulo hashing (no consistent-hashing ring) | Measured rebalancing cost of 97% data movement on a single shard addition (Test 3) is operationally unworkable at scale — rejected specifically on quantitative evidence, not just theoretical concern                               |

## Consequences

**Positive:** Near-perfect account-distribution uniformity (measured, not assumed). Rebalancing cost bounded to ~1/N of the dataset via consistent hashing, enabling safe future growth (validated against the 24,000 TPS / 2x-scale scenario in docs/06).

**Trade-offs / accepted technical debt:** Cross-shard transactions are the common case, not an edge case, which pushes real complexity into the Saga orchestration layer. The hot-merchant scenario (ARB Q1) is **not** solved by the sharding strategy itself — it requires a separate application-layer mitigation (dedicated settlement-pool pattern, docs/06 §4), which is an explicit limitation of hash-based sharding acknowledged here rather than glossed over.

## Compliance

All 32 shards and their replicas are provisioned within ap-south-1 exclusively, satisfying RBI Data Localization Directive (2018) NFR-010 requirements independent of the sharding scheme chosen.
