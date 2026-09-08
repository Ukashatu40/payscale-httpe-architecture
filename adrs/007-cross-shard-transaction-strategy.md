<!-- adrs/007-cross-shard-transaction-strategy.md -->

# ADR-007: Saga Pattern for Cross-Shard P2P Transactions (2PC/Saga/TCC Evaluation)

**Status:** Accepted

## Context

`adrs/003` (sharding on `account_id`) establishes that cross-shard transactions are the norm, not the exception, for P2P payments. This ADR formalizes the protocol evaluation that decision depends on — previously documented inline in `docs/06` §3, extracted here into its own ADR both because the brief treats this as bonus-ADR-worthy material and because a decision this consequential deserves its own decision record rather than living as a subsection of the sharding document.

## Decision

**Saga pattern, orchestrator-managed**, per the full evaluation table in `docs/06` §3 (reproduced in summary: 2PC rejected on latency grounds — coordinator lock duration threatens the 30ms p50 budget; TCC rejected because it requires a "reserved" balance state the schema doesn't model, with no correctness benefit over Saga for this transaction shape). Compensating transactions are new, auditable ledger operations, never silent rollbacks (`docs/04`, Failure Scenario 2).

## Alternatives Considered

See `docs/06` §3's full comparison table (latency, locking, availability, rollback semantics, operational complexity) — not reproduced in full here to avoid the exact duplication Section 22 warns against; this ADR is the formal record of the decision, `docs/06` is where the supporting analysis lives.

## Consequences

**Positive:** No cross-shard locks held at any point; orchestrator failure recovery is fully designed (`pseudocode/saga-orchestrator.py`'s `recover_incomplete_sagas`).

**Trade-offs:** Compensation logic is real implementation surface the team owns and must get right — accepted because it's debuggable application code, not a black-box distributed-transaction engine (same reasoning as ADR-002).

## Compliance

No independent compliance dimension beyond what ADR-003 and docs/05's audit-trail design already cover — compensating transactions are themselves fully auditable ledger entries, satisfying FR-004 identically to forward transactions.
