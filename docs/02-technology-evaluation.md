# Technology Evaluation — Comparison Matrices

Scoring criteria (1-5 each): **Performance**, **Operational Complexity** (5 = simplest to operate), **Cost**, **Team Expertise Fit**, **Community/Ecosystem Support**. Weighted total assumes Team Expertise Fit is weighted 1.5x given the 15-day deadline constraint (Section 7 of docs/00-assumptions-and-constants.md).

## Database Layer: PostgreSQL+Citus vs. CockroachDB vs. TiDB

| Criterion                 | PostgreSQL + Citus                                                                                                      | CockroachDB                                                                 | TiDB                                                   |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| Performance at 12K TPS    | 4 — proven at this scale w/ proper sharding; single-shard perf = vanilla Postgres                                       | 4 — good, but consensus (Raft) overhead per write adds latency              | 4 — similar Raft-based overhead                        |
| Operational complexity    | 4 — team already knows PostgreSQL operations; Citus adds shard-management surface but reuses pg_dump/pg_upgrade tooling | 2 — new operational model entirely (distributed consensus, range splitting) | 2 — new operational model, TiKV/PD/TiDB three-tier ops |
| Cost                      | 4 — standard PostgreSQL instance pricing, no license                                                                    | 3 — similar OSS pricing but higher instance counts for consensus quorums    | 3 — similar to CockroachDB                             |
| Team expertise fit (×1.5) | 5 → 7.5 — direct match to stated Java/Kotlin/PostgreSQL team                                                            | 2 → 3.0 — no distributed SQL experience assumed                             | 2 → 3.0 — no distributed SQL experience assumed        |
| Community/ecosystem       | 5 — PostgreSQL ecosystem is the largest in this comparison                                                              | 4 — strong, smaller                                                         | 3 — smaller in India/enterprise fintech context        |
| **Weighted total**        | **24.5**                                                                                                                | **16.0**                                                                    | **15.0**                                               |

**Selection: PostgreSQL + Citus.** Full reasoning in ADR-002.

## Message Queue: Kafka vs. RabbitMQ vs. Amazon SQS

| Criterion                                           | Apache Kafka                                                                           | RabbitMQ (clustered)                                                                                                                                | Amazon SQS                                                                                  |
| --------------------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Performance at 12K TPS                              | 5 — designed for this throughput class, partition-based horizontal scaling             | 2 — current single-node RabbitMQ is BN-002's root cause; even clustered, per-queue throughput ceiling is far lower than Kafka's per-partition model | 3 — scales well but adds ~10-20ms network latency per call, eating into the 30ms p50 budget |
| Operational complexity                              | 3 — brokers + ZooKeeper/KRaft is real operational surface, but well-documented         | 4 — simpler mental model than Kafka                                                                                                                 | 5 — fully managed, zero ops                                                                 |
| Cost                                                | 3 — self-hosted broker costs                                                           | 3 — similar                                                                                                                                         | 4 — pay-per-request, but at 12K TPS sustained volume this becomes expensive fast            |
| Team expertise fit (×1.5)                           | 1 → 1.5 — **zero stated Kafka experience** (this is the exact trade-off ARB Q3 probes) | 4 → 6.0 — already running RabbitMQ in production                                                                                                    | 3 → 4.5 — AWS-native, lower learning curve than Kafka                                       |
| Community/ecosystem                                 | 5 — dominant in fintech event-streaming; assignment explicitly recommends it           | 4 — strong but smaller streaming ecosystem                                                                                                          | 3 — good AWS integration, weaker for event-sourcing patterns                                |
| Exactly-once support                                | 5 — native idempotent + transactional producers                                        | 2 — no native EOS, requires manual dedup everywhere                                                                                                 | 2 — at-least-once only (FIFO SQS gives ordering, not EOS)                                   |
| **Weighted total (6 criteria, expertise weighted)** | **22.5**                                                                               | **21.0**                                                                                                                                            | **21.5**                                                                                    |

**Selection: Apache Kafka**, despite the zero-experience penalty — see ADR-001 for how the trade-off is resolved (this is a close score specifically _because_ the team-expertise gap is real and shouldn't be hidden).

## Cache Layer: Redis Cluster vs. Memcached vs. Hazelcast

| Criterion                                                        | Redis Cluster                                                 | Memcached                                                    | Hazelcast                                            |
| ---------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------- |
| Performance                                                      | 5                                                             | 5                                                            | 4                                                    |
| Operational complexity                                           | 4 — well-documented clustering                                | 5 — simplest of the three                                    | 3 — JVM-based, more tuning surface                   |
| Cost                                                             | 4                                                             | 5 — lowest memory overhead                                   | 3 — commercial features gated                        |
| Team expertise fit (×1.5)                                        | 4 → 6.0 — brief's own reference config already uses Redis     | 3 → 4.5                                                      | 2 → 3.0 — Java-ecosystem tool but unfamiliar to team |
| Feature fit (data structures, pub/sub, WATCH/MULTI/EXEC for CAS) | 5 — needed for idempotency keys, rate limiting, feature store | 2 — key-value only, no CAS primitives needed for OCC support | 4 — has distributed data structures but overkill     |
| **Weighted total**                                               | **24.0**                                                      | **21.5**                                                     | **17.0**                                             |

**Selection: Redis Cluster.** Not contested — matches brief's reference architecture and has the CAS primitives (WATCH/MULTI/EXEC) needed for idempotency-key handling. Formalized in ADR-005 (Day 8).

---

_All three selections feed docs/00-assumptions-and-constants.md and are formalized in adrs/001 and adrs/002 below._
