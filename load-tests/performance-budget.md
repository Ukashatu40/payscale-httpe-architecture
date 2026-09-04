<!-- load-tests/performance-budget.md -->

# Performance Budget — Allocating the 100ms p99 Target

Two tracks, because Day 9's two-stage fraud design (docs/09) means the majority of transactions and the minority that escalate to ML inference have genuinely different latency profiles — presenting them as one blended budget would obscure exactly the trade-off Day 9 was built to resolve.

## Track A: Stage-1-Only Path (majority of transactions — fraud resolved by deterministic rules)

Debit and credit account writes are issued **in parallel** (not sequential) since they target independent shards with no dependency between them until the ledger-write step — this is an explicit optimization over the reference budget's single combined line, worth stating since it materially changes the total.

| Processing Stage                                | Budget (ms) | Justification                                                                                                |
| ----------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------ |
| API Gateway (SSL + routing)                     | 3-5         | Hardware SSL offload + in-memory routing (Envoy)                                                             |
| Auth / JWT validation                           | 2-3         | Local validation with cached public keys                                                                     |
| Idempotency check (Redis GET)                   | 1-2         | Single GET, sub-ms network hop                                                                               |
| Fraud detection — Stage 1 (rules)               | 3-5         | Deterministic rule evaluation against cached `fraud_rules` (docs/05, docs/09) — no ML inference on this path |
| Database read (account balance, pre-validation) | 3-5         | Indexed query on local shard                                                                                 |
| Business logic (validation)                     | 1-2         | In-memory computation, no I/O                                                                                |
| Database write — debit + credit (parallel)      | 8-15        | Both writes issued concurrently to independent shards; total time = max(debit, credit), not sum              |
| Ledger entries write                            | 3-5         | Small additional insert after both legs confirmed                                                            |
| Kafka produce (outbox event)                    | 2-5         | Async produce, transactional producer                                                                        |
| Response serialization                          | 2-3         | JSON serialization + transmission                                                                            |
| **TOTAL (worst case)**                          | **28-50**   | Within the 30ms p50 target at the low end; well within 100ms p99 at the high end                             |

**p50 check:** low-end sum (28ms) sits just under the 30ms p50 target — tight but achievable, consistent with the reference budget's own framing.
**p99 headroom:** high-end sum (50ms) leaves ~50ms of the 100ms p99 budget unallocated, explicitly reserved for network jitter, GC pauses, OCC retry overhead, and load-spike contention — never allocated away, per the brief's own warning against summing stages to an unrealistic total.

## Track B: Stage-2 Escalation Path (minority — uncertain transactions routed to ML inference)

| Processing Stage                                                                       | Budget (ms) | Justification                                                                                                                                                                                                                                                                                                                                                                                                     |
| -------------------------------------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| All Track A stages except fraud, held to their **lower-to-mid range** (not worst case) | ~40         | Escalated transactions are a minority; the system can afford to budget them slightly tighter since they don't dominate aggregate p99                                                                                                                                                                                                                                                                              |
| Fraud detection — Stage 1 (rules, always runs first)                                   | 3-5         | Same as Track A — Stage 2 never replaces Stage 1, it supplements it                                                                                                                                                                                                                                                                                                                                               |
| Fraud detection — Stage 2 (ML inference, bounded)                                      | **≤25**     | This is the resolution to ARB Q4: 100ms p99 target − ~45ms other stages − ~30ms reserved jitter/contention headroom = **25ms remaining**, which exactly matches the ML team's stated 25ms model requirement. This is not a coincidence — the other stage budgets in Track A were deliberately tightened to make room for this, once the two-stage design made clear that only a minority of transactions need it. |
| **TOTAL (worst case, escalated path)**                                                 | **~90-95**  | Within the 100ms p99 target, with the ML model's real 25ms cost fully accommodated rather than silently exceeded                                                                                                                                                                                                                                                                                                  |

**Bounded fallback:** if Stage 2 inference somehow exceeds its 25ms allocation even under this budget (e.g., a cold-start model-loading anomaly), CB-FRAUD's existing fallback triggers (flag for manual review, proceed) rather than blocking — the hard p99 SLA is never sacrificed to accommodate an outlier inference call, per Option C in docs/09.

## Aggregate p99 Validity

Because only a minority of transactions escalate to Track B (the design assumption from docs/09), the **aggregate** p99 across all traffic is dominated by Track A's distribution, with Track B's slightly-higher-but-still-in-budget latencies pulling the tail up without breaching it — this is directly what LT-002 and LT-007 (below) are designed to validate empirically, not just assert.
