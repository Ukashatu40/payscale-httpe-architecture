<!-- adrs/005-cache-invalidation.md -->

# ADR-005: Cache-Aside for Balance Data, Write-Through for Idempotency Keys

**Status:** Accepted

## Context

Redis Cluster (per `docs/02-technology-evaluation.md`) serves three distinct purposes in this architecture, each with different consistency requirements: (1) balance/account data caching, purely for read-latency optimization — never the source of truth (docs/03 §12 explicitly states this); (2) idempotency key storage (FR-002), where a cache miss on an already-processed key could allow a duplicate transaction to be reprocessed — a correctness-critical, not merely performance-critical, use; (3) fraud feature store, where slightly-stale features are an accepted trade-off for the 15ms latency budget (docs/09, Day 9). A single invalidation strategy applied uniformly across all three would either over-engineer the low-stakes case or under-protect the high-stakes one.

## Decision

**Split by use case, not a single uniform policy:**

- **Balance/account display data: cache-aside, short TTL (5 seconds).** The cache is populated lazily on read-miss, and simply expires rather than being actively invalidated on every write — because the database (not the cache) is always the authoritative source for any decision that matters (debit/credit checks go through OCC against PostgreSQL directly, never through the cache), a brief window of cache staleness on a _display_ value is fully acceptable and matches the AP-leaning classification given to balance-display reads in docs/03's CP/AP split.

- **Idempotency keys: write-through.** The key is written to Redis synchronously as part of the same orchestrator step that inserts the `transactions` row (docs/07 §1 of the outbox lifecycle) — there is no lazy-population window during which a duplicate request could miss the cache and proceed as if it were novel. TTL is set to 24 hours per FR-002's own specification, not shorter.

- **Fraud feature store: write-behind (async population from the batch feature pipeline) with a bounded staleness tolerance**, since fraud evaluation already operates under an accepted trade-off (docs/09) between exact real-time accuracy and the 15ms latency budget — features that are seconds-to-minutes stale are an explicit, documented risk acceptance, not an oversight.

## Alternatives Considered

| Option                                                  | Why Rejected (as a uniform, single policy)                                                                                                                                                                                                                                                                |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Write-through everywhere**                            | Correct for idempotency keys, but unnecessarily adds write latency to every balance update for data that's only ever used for non-authoritative display — this would tax the hot path (debit/credit) for a benefit (display freshness) nothing in the requirements actually needs at write-time precision |
| **Cache-aside everywhere (including idempotency keys)** | The lazy-population gap is exactly the correctness gap FR-002 cannot tolerate — a request arriving during the gap between the DB insert and the cache being populated could read a cache miss and proceed as if novel, defeating the purpose of the idempotency check entirely                            |
| **Write-behind everywhere**                             | Would introduce unacceptable staleness risk for idempotency keys (the entire mechanism depends on the check being current at request time, not eventually current)                                                                                                                                        |

## Consequences

**Positive:** Each use case gets the consistency guarantee it actually needs, without over-paying latency cost on the two-thirds of use cases (balance display, fraud features) that don't require write-time consistency.

**Trade-offs / accepted technical debt:** Three different cache-management code paths instead of one uniform pattern — a small increase in implementation complexity, accepted because the alternative (one policy for all three) would either be unsafe (idempotency) or unnecessarily slow (balance display) for at least one of the three use cases.

## Compliance

No regulatory dimension specific to caching strategy beyond what's already covered by encryption-at-rest requirements (NFR-009), which apply to the Redis Cluster identically to the primary database.
