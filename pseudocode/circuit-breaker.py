# pseudocode/circuit-breaker.py
"""
Generic circuit breaker implementation, parameterized per-instance from the
reference table in docs/09-fault-tolerance.md. One instance of this class
per protected dependency (CB-FRAUD, CB-NOTIFY, CB-DB-PRIMARY, etc.) — never
a single shared breaker across dependencies, which is exactly what bulkhead
isolation (also in this file) exists to prevent.
"""

import time
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    name: str
    failure_threshold: int      # e.g. 3 failures
    rolling_window_seconds: float  # e.g. 10s
    reset_timeout_seconds: float   # e.g. 15s
    half_open_probe_count: int = 1


class CircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig, fallback_fn):
        self.config = config
        self.fallback_fn = fallback_fn
        self.state = CircuitState.CLOSED
        self.failure_times = deque()  # timestamps within rolling window
        self.opened_at = None
        self.half_open_probes_in_flight = 0
        self._lock = threading.Lock()

    def call(self, target_fn, *args, **kwargs):
        with self._lock:
            self._maybe_transition_from_open()

            if self.state == CircuitState.OPEN:
                emit_metric("circuit_breaker_state", self.config.name, value=1)  # OPEN=1, per A5.6 gauge spec
                return self.fallback_fn(*args, **kwargs)

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_probes_in_flight >= self.config.half_open_probe_count:
                    # Don't flood the recovering dependency — only a bounded
                    # number of probes in flight at once.
                    return self.fallback_fn(*args, **kwargs)
                self.half_open_probes_in_flight += 1

        # Actual call happens OUTSIDE the lock — never hold a lock across a
        # network call, or the breaker itself becomes a bottleneck.
        try:
            result = target_fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            if self.state == CircuitState.OPEN:
                return self.fallback_fn(*args, **kwargs)
            raise

    def _maybe_transition_from_open(self):
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self.opened_at >= self.config.reset_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                self.half_open_probes_in_flight = 0
                emit_metric("circuit_breaker_state", self.config.name, value=2)  # HALF_OPEN=2

    def _on_success(self):
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_times.clear()
                emit_metric("circuit_breaker_state", self.config.name, value=0)  # CLOSED=0
            self.half_open_probes_in_flight = max(0, self.half_open_probes_in_flight - 1)

    def _on_failure(self):
        with self._lock:
            now = time.monotonic()
            self.failure_times.append(now)
            # Evict failures outside the rolling window
            while self.failure_times and now - self.failure_times[0] > self.config.rolling_window_seconds:
                self.failure_times.popleft()

            if self.state == CircuitState.HALF_OPEN:
                # Probe failed — back to OPEN, reset timer restarts
                self.state = CircuitState.OPEN
                self.opened_at = now
                self.half_open_probes_in_flight = 0
                emit_metric("circuit_breaker_state", self.config.name, value=1)
            elif len(self.failure_times) >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = now
                emit_metric("circuit_breaker_state", self.config.name, value=1)
                # Alert threshold per A5.6: OPEN state > 2 minutes triggers a page


# --- Bulkhead isolation: one breaker instance + one bounded resource pool
# PER dependency, never shared. This is what stops CB-FRAUD tripping from
# ever being able to exhaust the thread pool that CB-DB-PRIMARY calls use,
# and vice versa. ---

CIRCUIT_BREAKERS = {
    "CB-FRAUD": CircuitBreaker(
        CircuitBreakerConfig("CB-FRAUD", failure_threshold=3, rolling_window_seconds=10,
                              reset_timeout_seconds=15),
        fallback_fn=lambda txn: flag_for_manual_review(txn),  # per reference table
    ),
    "CB-NOTIFY": CircuitBreaker(
        CircuitBreakerConfig("CB-NOTIFY", failure_threshold=5, rolling_window_seconds=30,
                              reset_timeout_seconds=60),
        fallback_fn=lambda notif: queue_notification_for_retry(notif),
    ),
    "CB-DB-PRIMARY": CircuitBreaker(
        CircuitBreakerConfig("CB-DB-PRIMARY", failure_threshold=2, rolling_window_seconds=5,
                              reset_timeout_seconds=10),
        fallback_fn=lambda op: route_read_to_replica_queue_write(op),
    ),
    "CB-DB-REPLICA": CircuitBreaker(
        CircuitBreakerConfig("CB-DB-REPLICA", failure_threshold=5, rolling_window_seconds=10,
                              reset_timeout_seconds=30),
        fallback_fn=lambda op: route_read_to_primary_rate_limited(op),
    ),
    "CB-CACHE": CircuitBreaker(
        CircuitBreakerConfig("CB-CACHE", failure_threshold=3, rolling_window_seconds=5,
                              reset_timeout_seconds=20),
        fallback_fn=lambda key: query_db_directly(key),  # safe: cache is never authoritative (adrs/005)
    ),
    "CB-EXCHANGE": CircuitBreaker(
        CircuitBreakerConfig("CB-EXCHANGE", failure_threshold=3, rolling_window_seconds=10,
                              reset_timeout_seconds=30),
        fallback_fn=lambda pair: use_last_known_rate_with_staleness_warning(pair),
    ),
    "CB-SETTLEMENT": CircuitBreaker(
        CircuitBreakerConfig("CB-SETTLEMENT", failure_threshold=2, rolling_window_seconds=5,
                              reset_timeout_seconds=60),
        fallback_fn=lambda batch: queue_settlement_for_next_batch_cycle(batch),
    ),
}


# --- Retry policy (applies to any call NOT already routed through a circuit
# breaker fallback — e.g. the OCC retries in occ-balance-update.py, and Kafka
# producer retries) ---

def retryable_operation(fn, *args, max_retries=3, base_backoff_ms=20,
                          jitter_pct=0.2, idempotent_required=True, **kwargs):
    """
    CRITICAL PRECONDITION: idempotent_required=True by default and must not
    be overridden for any financial write. Retrying a non-idempotent
    operation (e.g., a raw debit call without an idempotency key) risks a
    double-charge on transient network failures where the FIRST attempt
    actually succeeded server-side but the response was lost — exactly the
    Failure Scenario 3 case handled by the idempotency layer, not by this
    retry wrapper. This function assumes the caller has already ensured
    idempotency (via idempotency-handler.py) BEFORE reaching for retries.
    """
    if idempotent_required:
        assert has_idempotency_guard(fn), (
            f"Refusing to retry {fn.__name__}: not wrapped with an "
            f"idempotency guard. Financial operations must be idempotent "
            f"before retrying (Section 15 principle)."
        )

    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except TransientError as e:
            last_exception = e
            backoff_ms = base_backoff_ms * (2 ** (attempt - 1))
            jitter = backoff_ms * jitter_pct * (2 * random.random() - 1)
            time.sleep(max(0, backoff_ms + jitter) / 1000)
        except PermanentError:
            raise  # never retry a permanent error (e.g., validation failure)

    raise RetriesExhaustedError(f"{fn.__name__} failed after {max_retries} attempts") from last_exception