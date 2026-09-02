# pseudocode/occ-balance-update.py
"""
Production OCC balance-update logic for the Account Service (FR-009).

This is the pattern proven correct by simulation in docs/08 (write-skew
scenario from A5.4). The proof used the exact same conditional-UPDATE
semantics implemented here.
"""

import random
import time
from dataclasses import dataclass
from enum import Enum


class DebitResult(Enum):
    SUCCESS = "success"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    RETRIES_EXHAUSTED = "retries_exhausted"


@dataclass
class DebitOutcome:
    result: DebitResult
    new_balance: float | None = None
    new_version: int | None = None
    attempts_used: int = 0


MAX_RETRIES = 3
BASE_BACKOFF_MS = 20   # kept small deliberately -- OCC conflicts under normal
                        # (low-contention) load should resolve in microseconds
                        # of real DB round-trip time, not seconds; this budget
                        # must stay inside the 8-15ms DB-write line of the
                        # performance budget even after 1-2 retries
JITTER_PCT = 0.2


def debit_account(db_conn, account_id: str, amount: float) -> DebitOutcome:
    """
    Isolation level: READ COMMITTED is sufficient here — NOT SERIALIZABLE.
    This is a deliberate choice (see docs/08 §3, isolation-level table):
    correctness is enforced by the explicit version check in the WHERE
    clause, not by the transaction isolation level. Requesting SERIALIZABLE
    here would only add unnecessary serialization-failure retries on top of
    the OCC retries already handled explicitly below — redundant, not
    incorrect, but a real throughput cost with zero correctness benefit
    given the version check already provides the guarantee.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        # Step 1: fresh read EVERY attempt (including retries) — this is the
        # single most important correctness property. A retry that reused
        # the stale read/version from a prior attempt would just fail again
        # identically; each attempt must re-observe current reality.
        row = db_conn.execute(
            "SELECT available_balance, version FROM accounts "
            "WHERE account_id = %s",
            (account_id,),
        ).fetchone()
        current_balance, current_version = row["available_balance"], row["version"]

        if current_balance - amount < 0:
            # Reject on a FRESH read, not a stale one — this is what makes
            # the rejection in the T2-retry step of the proof correct rather
            # than a false negative against outdated data.
            return DebitOutcome(result=DebitResult.INSUFFICIENT_FUNDS,
                                 attempts_used=attempt)

        # Step 2: conditional write. WHERE version = current_version is the
        # entire correctness mechanism — a concurrent writer that committed
        # between our read and this write will have advanced the version,
        # causing this UPDATE to affect 0 rows.
        result = db_conn.execute(
            "UPDATE accounts "
            "SET available_balance = available_balance - %s, "
            "    version = version + 1 "
            "WHERE account_id = %s AND version = %s",
            (amount, account_id, current_version),
        )

        if result.rowcount == 1:
            # Committed. new_version is current_version + 1 by construction.
            return DebitOutcome(
                result=DebitResult.SUCCESS,
                new_balance=current_balance - amount,
                new_version=current_version + 1,
                attempts_used=attempt,
            )

        # rowcount == 0: a concurrent writer won the race. This is NOT an
        # error condition — it is the expected, correct OCC-conflict path.
        # Retry with exponential backoff + jitter to avoid synchronized
        # retry storms if many transactions are contending on the same row
        # (e.g., the hot-merchant scenario from docs/06).
        backoff_ms = BASE_BACKOFF_MS * (2 ** (attempt - 1))
        jitter = backoff_ms * JITTER_PCT * (2 * random.random() - 1)
        time.sleep(max(0, (backoff_ms + jitter)) / 1000)

    return DebitOutcome(result=DebitResult.RETRIES_EXHAUSTED, attempts_used=MAX_RETRIES)


def credit_account(db_conn, account_id: str, amount: float) -> DebitOutcome:
    """Mirror of debit_account — no insufficient-funds check (credits always
    succeed against the balance CHECK constraint), same version-guard pattern."""
    for attempt in range(1, MAX_RETRIES + 1):
        row = db_conn.execute(
            "SELECT available_balance, version FROM accounts WHERE account_id = %s",
            (account_id,),
        ).fetchone()
        current_balance, current_version = row["available_balance"], row["version"]

        result = db_conn.execute(
            "UPDATE accounts "
            "SET available_balance = available_balance + %s, "
            "    version = version + 1 "
            "WHERE account_id = %s AND version = %s",
            (amount, account_id, current_version),
        )
        if result.rowcount == 1:
            return DebitOutcome(
                result=DebitResult.SUCCESS,
                new_balance=current_balance + amount,
                new_version=current_version + 1,
                attempts_used=attempt,
            )

        backoff_ms = BASE_BACKOFF_MS * (2 ** (attempt - 1))
        jitter = backoff_ms * JITTER_PCT * (2 * random.random() - 1)
        time.sleep(max(0, (backoff_ms + jitter)) / 1000)

    return DebitOutcome(result=DebitResult.RETRIES_EXHAUSTED, attempts_used=MAX_RETRIES)