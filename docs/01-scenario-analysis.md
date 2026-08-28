# Scenario Analysis — PayScale Financial Technologies

## The Core Problem

PayScale operates a payment platform currently handling 1,200 TPS at 85ms p50 / 450ms p99 latency, built on a single-primary PostgreSQL instance and single-node RabbitMQ. In 15 days, a Diwali cashback campaign is projected to drive a 10x load increase to 12,000 sustained TPS (18,000 burst), while latency targets simultaneously tighten to 30ms p50 / 100ms p99 — a 65% latency reduction under 10x load. This is not a capacity problem alone; it is a **simultaneous throughput, latency, and correctness** problem, since the existing bottleneck report (BN-001 through BN-008) shows the current system fails catastrophically well below even 2x its rated load (connection pool exhaustion at 1,800 TPS, 15% deadlock rate on the accounts table).

## Why This Is Architecturally Hard

Three forces are in tension:

1. **Throughput vs. correctness.** Financial correctness (ACID, double-entry ledger invariants, no double-spend) traditionally favors pessimistic locking and strong consistency — both of which cap throughput. The redesign must achieve 12,000+ TPS while keeping optimistic concurrency control provably correct under write-skew and lost-update scenarios (BN-006's 15% deadlock rate on the accounts table is the direct symptom of the current locking model failing at scale).

2. **Availability vs. RPO=0.** A 99.99% availability target paired with zero data loss for committed transactions is, in CAP-theorem terms, a CP-leaning requirement — but a system that is CP everywhere sacrifices availability during network partitions (BN-007 already shows 18ms cross-AZ latency spikes during failover). The redesign needs to be explicit about where the system is CP (ledger writes) versus AP (balance display reads), rather than claiming both properties everywhere.

3. **Cost vs. capability.** All of the above must fit inside a $45,000/month budget (up from $12,000/month) — a 3.75x cost increase for a 10x throughput increase, meaning the architecture must get meaningfully more cost-efficient per transaction, not just bigger.

## Top 5 Bottlenecks (from Load Test Report) and Preliminary Direction

| ID     | Bottleneck                                          | Preliminary Solution Direction                                                                              |
| ------ | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| BN-001 | PostgreSQL connection exhaustion at 1,800 TPS       | PgBouncer connection pooling + horizontal sharding via Citus to distribute write load                       |
| BN-002 | RabbitMQ consumer lag at 2,000 TPS                  | Replace with Kafka; partition-based parallelism scales consumer throughput independently of broker count    |
| BN-006 | 15% deadlock rate on accounts table (CRITICAL)      | Replace row-level pessimistic locking with OCC (version-column based), eliminating lock contention entirely |
| BN-003 | Thread pool saturation, 40% timeout rate            | Bulkhead isolation per downstream dependency + circuit breakers to prevent cascade thread exhaustion        |
| BN-004 | Redis cache hit ratio collapse under load (92%→61%) | Redis Cluster (vs. single node) with capacity sized for peak working set, not average                       |

## What Success Looks Like

A system where every major throughput/latency/availability claim is backed by a calculation (not "Kafka can handle it"), every financial-correctness mechanism has a stated proof or timeline walkthrough, and every cost figure traces to the same central assumptions table — defensible against a hostile 20-minute technical cross-examination on Day 15.
