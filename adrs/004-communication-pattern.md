<!-- adrs/004-communication-pattern.md -->

# ADR-004: Hybrid Synchronous/Asynchronous Communication Pattern

**Status:** Accepted

## Context

The system has two structurally different classes of work: (1) the payment authorization path, which must return a definitive success/failure result to the client within the 100ms p99 budget (NFR-003) — the client cannot be told "we'll let you know eventually" for a financial debit/credit decision; and (2) everything downstream of a committed transaction (notifications, audit logging, reconciliation) — none of which the client needs an immediate answer about, and none of which should be allowed to slow down or block the financial decision itself. The architecture needs an explicit, consistent rule for which calls are synchronous and which are asynchronous, rather than an ad hoc per-service decision that risks inconsistency across the 13 components.

## Decision

**Hybrid pattern, split by whether the client-facing response depends on the outcome:**

- **Synchronous (blocking, in the critical path):** API Gateway → Transaction Orchestrator → Payment Processing Service → Account Service, and → Fraud Detection Service. Every call in this chain directly determines what the orchestrator tells the client, so none of it can be deferred.
- **Asynchronous (via Kafka outbox, off the critical path):** Transaction Orchestrator → Kafka → Notification Service, Audit & Compliance Service, Reconciliation Service. None of these three services' outcomes change what the client is told about their transaction — the transaction is already COMPLETED (or FAILED/REVERSED) by the time these consumers even see the event.

This is not a new decision invented here — it is the formalization of the pattern already used consistently in `docs/03` (HLD) and `docs/04` (data flow diagrams), specifically so that the ADR and the diagrams tell the same story rather than the ADR retroactively describing something different (the exact cross-document contradiction Section 22 warns against).

## Alternatives Considered

| Option                                                                                                           | Why Rejected                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **All-synchronous** (notification, audit, reconciliation all called inline, blocking the response)               | Directly violates the explicit design principle stated in docs/03 ("notification failure never blocks the financial transaction"). Would also make the p99 100ms budget effectively impossible — even a well-behaved notification call adds tens of milliseconds that the reference performance budget (docs/03 / load-tests, Day 11) doesn't allocate for downstream, non-critical work.                                                                                                                                                          |
| **All-asynchronous** (even the debit/credit decision itself returned via webhook, not the initial HTTP response) | Fails a real UX and compliance need — a payment API must tell the caller definitively whether their funds moved, within the request/response cycle, not "processing, check back later" for something the brief's own FR-008 (real-time status) and the fundamental nature of a payment authorization require to be synchronous. This would also complicate client integration significantly (every caller would need webhook infrastructure just to know if a payment succeeded) — a real developer-experience cost with no corresponding benefit. |

## Consequences

**Positive:** The synchronous path stays lean and independently optimizable against the 100ms p99 budget without competing for that budget against non-critical work. The asynchronous path can retry, fall behind under load, and even briefly go down (per the CB-NOTIFY fallback in docs/03) without affecting financial correctness or the client-visible transaction outcome.

**Trade-offs / accepted technical debt:** Notification delivery is not guaranteed to be instantaneous relative to the transaction completing — there is an inherent (typically sub-second) lag between "transaction completed" and "user notified," which is an accepted trade-off given FR-008's own wording ("sub-second propagation," not "synchronous").

## Compliance

The audit trail (FR-004) is written asynchronously but is still guaranteed complete via the outbox pattern's durability properties (docs/07 §4) — asynchronous delivery does not mean the audit record is optional or best-effort; it means only that its _timing_ relative to the client response is decoupled, not its _durability_.
