<!-- adrs/006-consistency-model.md -->

# ADR-006: Per-Subsystem CP/AP Consistency Split

**Status:** Accepted

## Context

NFR-005 (99.99% availability) and NFR-007 (zero RPO) are, taken as a single uniform requirement across the whole system, in genuine tension under CAP theorem (A1.4) — a system that is CP everywhere sacrifices availability during partitions; a system that is AP everywhere cannot guarantee zero data loss. This tension was flagged as an open contradiction from Day 1 (`docs/00` §8, item 2) and needed a real architectural answer, not a rhetorical one.

## Decision

**Split consistency guarantees by subsystem, not applied uniformly:**

- **CP:** Ledger writes (Account Service → PostgreSQL primary via OCC), Saga state transitions (`transaction_events`). These reject a write rather than risk data loss during a partition — synchronous replication acknowledgment (min.insync-equivalent), matching NFR-007 exactly where it matters (committed transactions).
- **AP:** Balance-display reads (Redis cache-aside or read replicas), Reconciliation Service, Notification delivery. These tolerate brief staleness to stay available — matching NFR-005 where correctness-at-every-instant isn't actually required.

## Alternatives Considered

| Option                                             | Why Rejected                                                                                                                                                                     |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Uniform CP (SERIALIZABLE + synchronous everything) | Would make the 99.99% availability target genuinely unachievable during any network partition — directly contradicts NFR-005                                                     |
| Uniform AP (eventual consistency everywhere)       | Unacceptable for ledger writes — a financial system cannot treat "the debit might not have really happened" as an acceptable steady state, directly contradicts NFR-007 and A1.2 |

## Consequences

**Positive:** Both NFR-005 and NFR-007 are genuinely satisfiable, because they're never claimed of the same subsystem simultaneously.

**Trade-offs:** Requires every new component added to this architecture to be explicitly classified CP or AP at design time — an ongoing discipline requirement, not a one-time decision.

## Compliance

RBI's zero-data-loss expectation for committed transactions (implicit in the Payment Aggregator Guidelines' audit-trail requirements) is satisfied specifically by the CP classification of ledger writes — this ADR is the explicit record of where that guarantee does and does not apply.
