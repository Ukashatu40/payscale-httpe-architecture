<!-- docs/14-architecture-review-deck.md -->

# ARB Presentation Outline (15 min presentation structure)

## Slide 1: Problem & Constraints (1.5 min)

1,200→12,000 TPS in 15 days, 85ms→30ms p50, $12K→$45K budget, India-only data residency, Java/Kotlin/PostgreSQL team. State the constraint that shapes everything downstream: **team expertise, not raw technology capability, is the binding design constraint** (ADR-001, ADR-002 both hinge on this).

## Slide 2: Architecture Overview (2 min)

The 13-component diagram (`diagrams/system-architecture.drawio`). Walk the happy-path arrow, not every box — API Gateway → Orchestrator → Payment/Fraud/Account → Kafka outbox → async consumers.

## Slide 3: The Three Hardest Decisions (3 min)

1. **Sharding** (`docs/06`) — account_id hash + consistent hashing, with the _actual executed_ distribution numbers (0.52% stdev, 97% vs 3% rebalance cost) on screen, not asserted.
2. **Concurrency** (`docs/08`) — the OCC proof, side-by-side naive-vs-OCC output showing -400 vs 200.
3. **Fraud latency** (`docs/09`, ADR-008) — the two-stage resolution, with the exact arithmetic (100 − 45 − 30 = 25ms) that answers Q4 before it's asked.

## Slide 4: Correctness Under Failure (3 min)

Walk Failure Scenario 2 from `diagrams/p2p-payment-flow.puml` live — debit commits, credit fails, compensation fires, user sees "reversed." This is the single strongest visual proof of engineering rigor in the whole deck.

## Slide 5: Cost (2 min)

$20,821/mo at target scale — 54% under ceiling, under the $12K _current_ baseline at _current_ load. Show the self-hosted-vs-managed-RDS trade-off honestly (docs/12) — this reads as more credible than an uncomplicated win.

## Slide 6: What We'd Do Differently at 10x (1.5 min)

64 shards, $41K/mo — near the ceiling. Name the next lever (managed Citus, reserved instances) before being asked.

## Slide 7: Evidence Summary (2 min)

Not claims — a table: simulation script → output → where it's used. Shard distribution, OCC proof, real AWS pricing. This is the slide that answers "how do I know any of this actually works" before the Q&A even starts.

---

# ARB Question Bank — All 10 Sample Questions, Answer Pointers

| Q                              | Best Evidence to Reference                                        |
| ------------------------------ | ----------------------------------------------------------------- |
| Q1 (hot merchant)              | `docs/06` §4 + CE-006 + FM-028                                    |
| Q2 (mid-txn shard failure)     | `diagrams/p2p-payment-flow.puml` diagram 2                        |
| Q3 (Kafka vs team experience)  | `adrs/001`, managed-MSK mitigation                                |
| Q4 (fraud latency)             | `adrs/008`, `docs/09` §3, `load-tests/performance-budget.md`      |
| Q5 (write-skew proof)          | `docs/08` §1, actually-executed proof output                      |
| Q6 (budget cut)                | `docs/12`, ranked-reduction table, honest premise-mismatch answer |
| Q7 (OCC SQL + isolation)       | `pseudocode/occ-balance-update.py`, `docs/08` §3                  |
| Q8 (CB-FRAUD exploit)          | Not yet answered — see gap below                                  |
| Q9 (stock exchange adaptation) | Not yet answered — see gap below                                  |
| Q10 (Redis RPN too low)        | `docs/13` §2, independently recalculated to 96                    |

**Two questions (Q8, Q9) remain unanswered going into Day 15** — flagged honestly rather than glossed over. Q8 (circuit breaker exploitability) needs a concrete answer about the 15s CB-FRAUD reset window being gameable by a determined attacker; Q9 (stock-exchange adaptation) needs a comparison against NSE's microsecond-latency architecture (Case Study 4). Both should be prepared explicitly before the Day 15 presentation, not improvised live.
