# pseudocode/saga-orchestrator.py
"""
Saga orchestrator for cross-shard P2P payments (per adrs/003, adrs/007).
Implements the state machine walked through narratively in
diagrams/p2p-payment-flow.puml and docs/04-data-flow-design.md.
"""

from dataclasses import dataclass, field
from enum import Enum
import uuid


class SagaState(Enum):
    STARTED = "STARTED"
    DEBIT_PENDING = "DEBIT_PENDING"
    DEBITED = "DEBITED"
    CREDIT_PENDING = "CREDIT_PENDING"
    CREDITED = "CREDITED"
    LEDGER_WRITTEN = "LEDGER_WRITTEN"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"


@dataclass
class SagaContext:
    saga_id: str
    transaction_id: str
    source_account_id: str
    destination_account_id: str
    amount: float
    state: SagaState = SagaState.STARTED
    debit_new_version: int | None = None  # needed for compensation reference


def emit_event(db_conn, ctx: SagaContext, from_state, to_state, actor, payload=None):
    """Every state transition is durably logged BEFORE the next step runs —
    this is what makes crash recovery (the periodic sweep below) possible.
    Maps directly to schemas/ddl/005-transaction-events.sql."""
    db_conn.execute(
        "INSERT INTO transaction_events "
        "(transaction_id, saga_id, from_state, to_state, actor, payload) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (ctx.transaction_id, ctx.saga_id, from_state, to_state.value, actor, payload or {}),
    )
    ctx.state = to_state


def run_p2p_saga(db_conn, account_svc, idempotency_key: str,
                   source_account_id: str, destination_account_id: str,
                   amount: float) -> dict:
    """
    Orchestrates the happy path exactly as diagrammed in
    diagrams/p2p-payment-flow.puml, diagram 1. On any step failure, routes
    to the appropriate failure-scenario handling (diagrams 2 or 3 of the
    same file), selected automatically by WHICH step failed -- this mirrors
    the real distinction: pre-debit-commit failures need no compensation,
    post-debit-commit failures do.
    """

    # --- Idempotency check FIRST, before any state mutation (Failure
    # Scenario 3) ---
    cached = check_idempotency_cache(idempotency_key)
    if cached is not None:
        return cached  # no reprocessing -- returns the original result verbatim

    ctx = SagaContext(
        saga_id=str(uuid.uuid4()),
        transaction_id=str(uuid.uuid4()),
        source_account_id=source_account_id,
        destination_account_id=destination_account_id,
        amount=amount,
    )

    db_conn.execute(
        "INSERT INTO transactions (transaction_id, idempotency_key, transaction_type, "
        "source_account_id, destination_account_id, amount, status, saga_id) "
        "VALUES (%s, %s, 'P2P', %s, %s, %s, 'INITIATED', %s)",
        (ctx.transaction_id, idempotency_key, source_account_id,
         destination_account_id, amount, ctx.saga_id),
    )
    emit_event(db_conn, ctx, None, SagaState.STARTED, "orchestrator")
    set_idempotency_cache(idempotency_key, status="IN_PROGRESS")

    # --- Step 1: Debit sender ---
    emit_event(db_conn, ctx, ctx.state, SagaState.DEBIT_PENDING, "orchestrator")
    debit_outcome = account_svc.debit_account(db_conn, source_account_id, amount)

    if debit_outcome.result != "success":
        # FAILURE SCENARIO 1 (docs/04, diagram 2): pre-commit failure.
        # No compensation needed -- nothing was ever committed.
        return handle_pre_debit_failure(db_conn, ctx, debit_outcome, idempotency_key)

    ctx.debit_new_version = debit_outcome.new_version
    emit_event(db_conn, ctx, ctx.state, SagaState.DEBITED, "orchestrator",
               payload={"new_version": debit_outcome.new_version})

    # --- Step 2: Credit receiver ---
    emit_event(db_conn, ctx, ctx.state, SagaState.CREDIT_PENDING, "orchestrator")
    credit_outcome = account_svc.credit_account(db_conn, destination_account_id, amount)

    if credit_outcome.result != "success":
        # FAILURE SCENARIO 2 (docs/04, diagram 3): post-commit failure.
        # Compensation IS required -- the debit already committed.
        return handle_post_debit_failure(db_conn, ctx, idempotency_key)

    emit_event(db_conn, ctx, ctx.state, SagaState.CREDITED, "orchestrator")

    # --- Step 3: Ledger entries (double-entry pair) ---
    write_ledger_entries(db_conn, ctx)
    emit_event(db_conn, ctx, ctx.state, SagaState.LEDGER_WRITTEN, "orchestrator")

    # --- Step 4: Mark complete, publish outbox event ---
    db_conn.execute(
        "UPDATE transactions SET status = 'COMPLETED', completed_at = now() "
        "WHERE transaction_id = %s", (ctx.transaction_id,))
    emit_event(db_conn, ctx, ctx.state, SagaState.COMPLETED, "orchestrator")
    publish_outbox_event(db_conn, ctx.transaction_id, "txn.completed")

    result = {"transaction_id": ctx.transaction_id, "status": "COMPLETED"}
    set_idempotency_cache(idempotency_key, status="COMPLETED", result=result)
    return result


def handle_pre_debit_failure(db_conn, ctx, debit_outcome, idempotency_key):
    """Failure Scenario 1: no funds ever moved."""
    db_conn.execute(
        "UPDATE transactions SET status = 'FAILED', failure_reason = %s "
        "WHERE transaction_id = %s",
        (debit_outcome.result, ctx.transaction_id))
    emit_event(db_conn, ctx, ctx.state, SagaState.FAILED, "orchestrator",
               payload={"reason": debit_outcome.result})
    publish_outbox_event(db_conn, ctx.transaction_id, "txn.failed")
    result = {"transaction_id": ctx.transaction_id, "status": "FAILED",
              "reason": debit_outcome.result}
    set_idempotency_cache(idempotency_key, status="FAILED", result=result)
    return result


def handle_post_debit_failure(db_conn, ctx, idempotency_key):
    """Failure Scenario 2: debit committed, credit failed. Must compensate
    within the 30-second FR-005 reversal SLA."""
    emit_event(db_conn, ctx, ctx.state, SagaState.COMPENSATING, "orchestrator")

    # Compensating credit is itself a new, auditable ledger operation --
    # never a silent rollback of the original debit row.
    compensation_outcome = credit_account_compensating(
        db_conn, ctx.source_account_id, ctx.amount, reason="SAGA_COMPENSATION",
        original_saga_id=ctx.saga_id)

    write_ledger_entries(db_conn, ctx, is_reversal=True)

    db_conn.execute(
        "UPDATE transactions SET status = 'REVERSED', "
        "failure_reason = 'DESTINATION_SHARD_UNAVAILABLE', completed_at = now() "
        "WHERE transaction_id = %s", (ctx.transaction_id,))
    emit_event(db_conn, ctx, ctx.state, SagaState.COMPENSATED, "orchestrator")
    publish_outbox_event(db_conn, ctx.transaction_id, "txn.reversed")

    result = {"transaction_id": ctx.transaction_id, "status": "REVERSED",
              "message": "Transaction failed and was automatically reversed."}
    set_idempotency_cache(idempotency_key, status="REVERSED", result=result)
    return result


def recover_incomplete_sagas(db_conn, sweep_interval_seconds=10):
    """
    Crash recovery sweep (docs/03, Transaction Orchestrator failure modes;
    docs/04, System Failover flow). Runs on every orchestrator instance on a
    periodic timer, looking for sagas stuck in a non-terminal state longer
    than the sweep interval -- these are candidates for either resume or
    compensation, decided by which state they were last durably recorded in.
    """
    stuck_sagas = db_conn.execute(
        "SELECT DISTINCT saga_id, transaction_id FROM transaction_events "
        "WHERE saga_id NOT IN ("
        "  SELECT saga_id FROM transaction_events "
        "  WHERE to_state IN ('COMPLETED', 'FAILED', 'COMPENSATED')"
        ") AND created_at < now() - interval '%s seconds'",
        (sweep_interval_seconds,),
    ).fetchall()

    for saga in stuck_sagas:
        last_event = get_last_event(db_conn, saga["saga_id"])
        if last_event["to_state"] in ("STARTED", "DEBIT_PENDING"):
            # Debit never confirmed committed -- safe to retry the whole saga
            # from scratch (idempotency key still guards against double-run).
            resume_from_start(db_conn, saga)
        elif last_event["to_state"] in ("DEBITED", "CREDIT_PENDING"):
            # Debit committed, credit outcome unknown -- must compensate,
            # never blindly retry (retrying could double-credit if the
            # original credit actually succeeded but the confirmation was lost).
            trigger_compensation(db_conn, saga)
        elif last_event["to_state"] == "CREDITED":
            # Both legs committed, only ledger-write/completion step missing
            # -- safe to resume from ledger-write, not compensate.
            resume_from_ledger_write(db_conn, saga)