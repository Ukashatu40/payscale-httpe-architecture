<!-- adrs/008-fraud-detection-placement-latency.md -->

# ADR-008: Two-Stage Fraud Detection (Synchronous Rules + Bounded ML Escalation)

**Status:** Accepted

## Context

FR-007's 15ms fraud SLA, evaluated against a real ML model's stated 25ms requirement, is the single most-tested contradiction in this submission (flagged Day 1, `docs/00` §8 item 1; directly probed by ARB Q4). This ADR formalizes the resolution designed in `docs/09` §3, giving it a durable decision record rather than leaving the reasoning only inline in the fault-tolerance document.

## Decision

**Two-stage placement:** Stage 1 (deterministic rules against the `fraud_rules` table) runs synchronously in the critical path for every transaction, budgeted 3-5ms. Stage 2 (ML inference) runs only for the residual uncertain minority, with a genuine ≤25ms budget — freed up by tightening Track A's other stages (`load-tests/performance-budget.md`). If Stage 2 exceeds its bound, CB-FRAUD's existing fallback (allow with manual-review flag) applies — fraud detection is never skipped, only the ML stage's worst case is time-boxed.

## Alternatives Considered

Full three-option evaluation (feature caching, two-stage, bounded fallback) is in `docs/09` §3 — Option B (two-stage) was adopted as primary, combined with Option C (bounded fallback) as the safety net, rather than either alone.

## Consequences

**Positive:** Every transaction gets real fraud evaluation; the hard p99 SLA is never sacrificed to a slow model call.

**Trade-offs:** A small window of risk exposure exists between commit and async secondary review completing for the minority of transactions that hit the bounded-fallback path — explicitly accepted, not hidden, and mitigated by Stage 1 already having caught the highest-confidence fraud cases before this path is ever reached.

## Compliance

Satisfies FR-007's SHOULD-priority fraud requirement without compromising NFR-002/003 (latency) — both a functional and non-functional requirement are honored simultaneously, which is the entire point of this ADR existing.
