# pseudocode/idempotency-handler.py
"""
Redis-backed idempotency key handler (FR-002). Referenced by
saga-orchestrator.py's check_idempotency_cache / set_idempotency_cache calls.
"""

import json
from dataclasses import dataclass
from enum import Enum


class IdempotencyStatus(Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


IDEMPOTENCY_KEY_TTL_SECONDS = 24 * 60 * 60  # 24hr, per FR-002 exactly


def check_idempotency_cache(redis_conn, idempotency_key: str) -> dict | None:
    """
    Returns the cached result if this key has been seen before, else None.
    This is a plain GET, not a WATCH/MULTI/EXEC transaction — read-only,
    no race risk on the read side itself. The race that matters is on the
    WRITE side (two near-simultaneous first-time requests with the SAME key)
    and is handled by set_idempotency_cache_atomic below, using Redis's
    SET ... NX (set-if-not-exists) as the actual compare-and-swap primitive
    (A5.3's CAS reference — "Used in distributed state management, e.g.
    Redis WATCH/MULTI/EXEC" — SET NX is the simpler, sufficient CAS form
    for this specific "claim this key or fail" use case).
    """
    raw = redis_conn.get(f"idempotency:{idempotency_key}")
    if raw is None:
        return None
    return json.loads(raw)


def claim_idempotency_key(redis_conn, idempotency_key: str) -> bool:
    """
    Atomically claims the key for processing. Returns True if this caller
    is the first to claim it (should proceed with processing), False if
    another request already claimed it (should NOT proceed — caller should
    poll or return a "processing, try again shortly" response).

    This is the durable backstop referenced in schemas/ddl/002-transactions.sql's
    UNIQUE constraint comment: even if two near-simultaneous requests both
    miss/race past this Redis check somehow, the database UNIQUE constraint
    on transactions.idempotency_key is the final, unconditional guarantee —
    Redis is the fast path, PostgreSQL is the correctness backstop.
    """
    claimed = redis_conn.set(
        f"idempotency:{idempotency_key}",
        json.dumps({"status": IdempotencyStatus.IN_PROGRESS.value}),
        nx=True,  # NX = only set if key does not already exist (atomic CAS)
        ex=IDEMPOTENCY_KEY_TTL_SECONDS,
    )
    return bool(claimed)


def set_idempotency_result(redis_conn, idempotency_key: str, status: IdempotencyStatus, result: dict):
    """
    Overwrites the IN_PROGRESS placeholder with the final result. Uses a
    plain SET (not NX) since this caller already legitimately owns the key
    (it either claimed it via claim_idempotency_key, or is the orchestrator
    completing its own saga). TTL is refreshed to the full 24hr window from
    completion time, not decremented from the original claim time — a
    completed transaction's result should be queryable for the FULL 24hr
    window from when it finished, not from when it started.
    """
    redis_conn.set(
        f"idempotency:{idempotency_key}",
        json.dumps({"status": status.value, "result": result}),
        ex=IDEMPOTENCY_KEY_TTL_SECONDS,
    )


def handle_incoming_request(redis_conn, db_conn, idempotency_key: str, request_payload: dict):
    """Top-level entry point — the actual FR-002 handler called from the
    API Gateway → Orchestrator boundary."""

    cached = check_idempotency_cache(redis_conn, idempotency_key)
    if cached is not None:
        if cached["status"] == IdempotencyStatus.IN_PROGRESS.value:
            # Another request with the same key is CURRENTLY being processed
            # (a true concurrent duplicate, not a sequential retry). Per the
            # brief's error-handling expectations, return a distinct status
            # rather than silently blocking or double-processing.
            return {"status": 409, "message": "Request with this idempotency key is already processing"}
        # COMPLETED / FAILED / REVERSED — return the cached terminal result
        # verbatim, no reprocessing (this is Failure Scenario 3 exactly).
        return {"status": 200, "body": cached.get("result", {})}

    claimed = claim_idempotency_key(redis_conn, idempotency_key)
    if not claimed:
        # Lost the race between our GET (miss) and our SET NX (someone else
        # claimed it in between) — treat identically to the IN_PROGRESS case.
        return {"status": 409, "message": "Request with this idempotency key is already processing"}

    # We own this key — proceed to actual saga processing.
    result = run_p2p_saga(db_conn, idempotency_key=idempotency_key, **request_payload)
    return {"status": 200, "body": result}