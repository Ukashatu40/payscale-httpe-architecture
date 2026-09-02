<!-- docs/08-concurrency-control.md -->

# Concurrency Control & Distributed Locking

## 1. Formal Correctness Argument — OCC Prevents Write-Skew and Double-Spend

**Claim:** the version-guarded conditional UPDATE pattern in `pseudocode/occ-balance-update.py` prevents both the write-skew anomaly described in A5.4 and double-spend generally, for any interleaving of concurrent transactions on the same account row.

**Proof, by construction and executed demonstration:**

Consider two concurrent transactions T1, T2 operating on account A (balance=1000, version=1), where T1 debits 800 and T2 debits 600 — the exact scenario from A5.4. Under an interleaving where both T1 and T2 read the balance/version _before either writes_ (the race condition that produces write-skew), the following was actually executed and observed (not merely asserted):

[T1 and T2 both read version=1, balance=1000 'concurrently']
T1: UPDATE ... WHERE version=1 -> 1 row affected, COMMITTED, balance now=200, version now=2
T2: UPDATE ... WHERE version=1 -> 0 rows affected (version is now 2, not 1)

T2 must now RETRY with a fresh read (the application-level retry loop):
T2-retry attempt 1: read v=2 bal=200 -> REJECTED (insufficient funds on fresh read: 200 - 600 < 0)

FINAL BALANCE: 200

Compare against the naive (non-OCC) implementation under the identical interleaving, also actually executed:

T1: read=1000, debit=800 -> debited, balance now=-400
T2: read=1000, debit=600 -> debited, balance now=-400
FINAL BALANCE: -400 <-- OVERDRAFT

**Why this generalizes beyond this one interleaving:** the correctness property does not depend on _which_ transaction's write happens to execute "first" in wall-clock time — it depends only on the invariant that **a conditional UPDATE with `WHERE version = $expected_version` can affect at most one transaction's write per version value**, because the UPDATE that succeeds atomically increments the version (PostgreSQL's row-level locking during the UPDATE itself guarantees this — two concurrent UPDATEs against the same row cannot both read-modify-write between each other's lock acquisition). Whichever transaction's UPDATE statement physically executes second against a given version value will affect 0 rows, by definition, regardless of which transaction "started" first or which had a larger or smaller debit amount. The full case analysis:

| Interleaving order                                                             | Outcome                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1's UPDATE executes before T2's UPDATE (shown above)                          | T1 succeeds (v1→v2), T2 gets 0 rows, retries against v2/balance=200, correctly rejected (insufficient funds)                                                                                                                                      |
| T2's UPDATE executes before T1's UPDATE (symmetric case)                       | T2 succeeds (v1→v2, balance=1000-600=400), T1 gets 0 rows, retries against v2/balance=400, correctly rejected (400-800<0)                                                                                                                         |
| Both amounts are individually satisfiable against the post-first-write balance | The retrying transaction's fresh read reflects the true current balance, so its insufficient-funds check (if any) is evaluated correctly — this is the property that specifically prevents write-skew: the check is never made against stale data |

In every case, **at most one debit can commit per version transition**, and every retry re-evaluates against currently-true state rather than the stale state that caused the original conflict. This is what makes the argument a proof rather than a single favorable example: the mechanism (conditional UPDATE + row-level lock during the UPDATE + mandatory fresh-read-on-retry) holds independent of interleaving order, transaction count, or amounts involved.

**Double-spend as a special case:** double-spend is precisely write-skew where the "conflicting reads" represent the same funds being committed to two different destinations — the identical mechanism applies, since both attempts to spend the same balance are, structurally, two conditional UPDATEs racing on the same account row's version.

Full simulation source: `simulations/shard-distribution-simulator.py`'s sibling script (embedded above); can be re-run to reproduce identical results (same algorithm, deterministic interleaving — no randomness in the race itself, only in retry backoff jitter which doesn't affect correctness).

## 2. Distributed Locking Strategy — Fencing Tokens

OCC is the primary concurrency mechanism and requires no distributed lock for the common case (single-account-row updates). Distributed locking (via a monotonic fencing token, not a bare mutex) is reserved for **one specific case**: shard-primary failover (docs/04, System Failover flow), where a stale/recovering old primary must be prevented from accepting writes after a new primary has been promoted.

Fencing token scheme:

1. Each shard-primary promotion event (via Patroni) increments a monotonic
   epoch number, stored in a small coordination table replicated via the
   HA manager (not via application-level Redis locking, since this must
   survive the very database failure it's protecting against).
2. Every write transaction includes its believed-current epoch as part of
   the connection/session context.
3. If a write arrives with an epoch LOWER than the coordinator's current
   epoch, it is rejected outright — this is what prevents a "zombie" old
   primary (one that hasn't yet realized it was demoted, e.g. due to a
   network partition rather than a true crash) from accepting writes that
   would silently diverge from the new primary's state.
4. This directly implements the FM-004 mitigation ("fencing tokens; quorum
   writes") named in the reference FMEA table (Case Study/Reference section
   of the project brief) for network-partition-induced split-brain.

This is intentionally a narrow-scope mechanism — it is not used for ordinary account-balance concurrency (OCC handles that, with no distributed lock needed at all), only for the much rarer case of coordinating which physical database node is authoritative during a failover event.

## 3. Isolation Level Selection Per Query Type

| Query type                                           | Isolation level                                                            | Rationale                                                                                                                                                                                                                                                                     |
| ---------------------------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Balance debit/credit (OCC-guarded UPDATE)            | READ COMMITTED                                                             | Correctness comes from the explicit version check, not the isolation level (per the code comment in `occ-balance-update.py`) — requesting SERIALIZABLE here adds redundant serialization-failure retries on top of OCC retries, a throughput cost with no correctness benefit |
| Settlement batch chunk processing                    | SERIALIZABLE                                                               | Per A5.4's own guidance table — settlement batches involve multi-row aggregate correctness (chunk totals must reconcile exactly) where the stronger guarantee is worth the throughput cost, since this runs off-peak/async, not on the 30ms critical path                     |
| Dashboard queries, notification checks               | READ COMMITTED                                                             | Per A5.4 — these are non-critical reads where staleness is fully acceptable                                                                                                                                                                                                   |
| Balance reads (for display, not for debit decisions) | REPEATABLE READ                                                            | Per A5.4 — protects against a single dashboard render seeing inconsistent values mid-query, without needing full serializability for a read-only operation                                                                                                                    |
| Reconciliation, audit queries                        | SNAPSHOT ISOLATION (PostgreSQL's REPEATABLE READ, which is snapshot-based) | Per A5.4 — reconciliation needs a consistent point-in-time view across many rows, but is inherently AP/eventually-consistent (docs/03), so does not need serializability                                                                                                      |

## 4. Cache Invalidation Strategy — see ADR-005

Full reasoning in `adrs/005-cache-invalidation.md`. Summary: **cache-aside with short TTL** for balance display data (never authoritative — docs/03's Cache Layer section), **write-through** for idempotency keys (must be immediately consistent, since a cache-aside miss on an idempotency check could allow a duplicate to slip through in the gap between write and cache population).
