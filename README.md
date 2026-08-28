**Zetheta Algorithms Private Limited — Software Engineer HTTPE Assessment**

> Strictly Private and Confidential — Not for Circulation. This repository is submitted for individual assessment purposes as part of Zetheta's HTTPE project. All content is original work produced under the 15-day project methodology (Part D of the project brief).

## What This Is

A complete system-design submission for scaling PayScale Financial Technologies' payment infrastructure from 1,200 TPS to 12,000+ TPS (18,000 burst) ahead of a Diwali campaign, while meeting sub-100ms p99 latency, 99.99% availability, zero-RPO durability, and a $45,000/month budget ceiling.

## Repository Map

| Path                                   | Contents                                                                                                                                                         |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/00-assumptions-and-constants.md` | **Start here.** Single source of truth for every number used elsewhere in this repo.                                                                             |
| `docs/00-requirements-matrix.md`       | Full requirements traceability from the project brief to deliverables.                                                                                           |
| `docs/01` – `docs/14`                  | Day-by-day deliverables per Part D of the project brief.                                                                                                         |
| `adrs/`                                | Architecture Decision Records (5 mandatory + 3 bonus).                                                                                                           |
| `diagrams/`                            | System architecture and sequence diagrams (Draw.io source + PlantUML).                                                                                           |
| `schemas/`                             | DDL for all 8 required entities + ERD.                                                                                                                           |
| `pseudocode/`                          | OCC, saga orchestrator, circuit breaker, idempotency handler.                                                                                                    |
| `api/openapi.yaml`                     | Full OpenAPI 3.0 specification.                                                                                                                                  |
| `load-tests/`                          | 8 load test scenarios + performance budget.                                                                                                                      |
| `simulations/`                         | Shard distribution simulator (mathematical proof of key distribution).                                                                                           |
| `evidence/`                            | Working prototype components — each explicitly labeled simulated/estimated/measured per the source-discipline standard; none presented as production benchmarks. |

## Status

Day 1 of 15 — scenario analysis and repository scaffolding complete. See `SELF-ASSESSMENT.md` (populated Day 14) for scoring against the 1000-point rubric.

## Note on AI Assistance

This project was developed with AI-assisted research and drafting support, substantially reviewed and modified throughout, per the project brief's AI-usage guidance (Part E, Section E3). All architectural decisions, trade-off judgments, and final content are owned and defensible by the submitting individual.
