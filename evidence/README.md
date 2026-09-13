<!-- evidence/README.md -->

# Evidence — What's Real vs. Simulated vs. Not Yet Built

Per the source-discipline standard (never call something "measured" if it wasn't): here's an honest inventory of everything in this folder and its sibling `simulations/`, and — just as importantly — what the brief's Sandbox Mode describes that **was not** attempted in this submission.

## What was actually executed

| Artifact                                                      | What it proves                                                                                      | How it was run                                                                                                            |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `occ-write-skew-proof.py` + `occ-write-skew-proof-output.txt` | OCC prevents the A5.4 write-skew scenario; naive implementation genuinely overdrafts                | Standalone Python, executed directly — no real database involved, this is pure algorithmic logic isolated from PostgreSQL |
| `simulations/shard-distribution-simulator.py`                 | Hash-distribution uniformity (0.52% stdev), hot-merchant skew (13.4x), rebalancing cost (97% vs 3%) | Same — standalone Python with `hashlib`, no real Citus cluster involved                                                   |

**Important honesty note:** both of the above prove the _algorithm_ is correct in isolation. Neither proves the _production implementation_ (`pseudocode/occ-balance-update.py`'s actual SQL, run against a real PostgreSQL+Citus cluster under real concurrent load) behaves identically — that's a reasonable inference, not an independently verified fact.

## What the Sandbox Mode bonus describes that was NOT built

Per Part B §3.3, Sandbox Mode's example activities include several things this submission does **not** contain, and shouldn't be assumed to:

- ❌ An actual local Kafka cluster with real producer/consumer code running against it (docs/07's design was never executed)
- ❌ An actual PostgreSQL instance with the Citus extension installed and the DDL from `schemas/ddl/` applied to it
- ❌ An actual k6/Locust load test run against a live service (the 3 k6 scripts in `load-tests/scenarios/` are written and syntactically complete, but have never been executed against anything)
- ❌ An actual Grafana dashboard connected to a real Prometheus instance

If you want any of these built out before submission, they're the highest-value remaining additions — say which one and I'll build it.
