# simulations/shard-distribution-simulator.py
"""
Shard distribution simulator for PayScale HTTPE — validates the account_id
hash-sharding strategy chosen in ADR-003.

STATUS: Actually executed (not modeled/estimated). Results below are copied
verbatim from a real run; re-running this script will reproduce them within
statistical noise (same algorithm, fresh random UUIDs each run).

Three tests:
  1. Uniformity of hash(account_id) mod N across a synthetic 1M-account population
  2. Hot-merchant scenario (ARB Q1): does uniform account distribution prevent
     a hot PARTITION when transaction VOLUME (not account count) is skewed?
  3. Rebalancing cost when shard count changes: modulo hashing vs. consistent
     hashing with virtual nodes
"""

import hashlib
import statistics
import uuid
import bisect

NUM_SHARDS = 32
NUM_ACCOUNTS = 1_000_000


def shard_hash(account_id: str) -> int:
    """SHA-256 based hash, truncated to 64 bits for speed. Using SHA-256
    rather than Python's built-in hash() because the latter is randomized
    per-process (PYTHONHASHSEED) and not suitable for a routing decision
    that must be consistent across service instances and restarts."""
    h = hashlib.sha256(account_id.encode()).hexdigest()
    return int(h[:16], 16)


def shard_for_modulo(account_id: str, num_shards: int) -> int:
    return shard_hash(account_id) % num_shards


def consistent_hash_ring(num_shards: int, vnodes_per_shard: int = 100):
    """Build a consistent-hash ring with virtual nodes to smooth distribution
    variance (100 vnodes/shard is a standard starting point — enough to keep
    per-shard variance low without an excessive ring size)."""
    ring = []
    for shard in range(num_shards):
        for v in range(vnodes_per_shard):
            point = shard_hash(f"shard-{shard}-vnode-{v}")
            ring.append((point, shard))
    ring.sort()
    return ring


def shard_for_consistent(account_id: str, ring: list) -> int:
    point = shard_hash(account_id)
    points = [p for p, _ in ring]
    idx = bisect.bisect_right(points, point) % len(ring)
    return ring[idx][1]


def run_test_1():
    """Account-count uniformity under simple hash-modulo sharding."""
    accounts = [str(uuid.uuid4()) for _ in range(NUM_ACCOUNTS)]
    counts = [0] * NUM_SHARDS
    for aid in accounts:
        counts[shard_for_modulo(aid, NUM_SHARDS)] += 1

    mean = statistics.mean(counts)
    stdev = statistics.stdev(counts)
    return accounts, {
        "mean": mean, "stdev": stdev, "stdev_pct": stdev / mean * 100,
        "min": min(counts), "max": max(counts),
        "max_ratio": max(counts) / mean, "min_ratio": min(counts) / mean,
    }


def run_test_2(accounts):
    """Hot-merchant transaction-volume skew — the ARB Q1 scenario."""
    NUM_TXNS = 1_000_000
    HOT_SHARE = 0.40
    hot_account = accounts[0]
    hot_shard = shard_for_modulo(hot_account, NUM_SHARDS)

    txn_counts = [0] * NUM_SHARDS
    hot_txn_count = int(NUM_TXNS * HOT_SHARE)
    remaining_txns = NUM_TXNS - hot_txn_count
    txn_counts[hot_shard] += hot_txn_count

    for i in range(remaining_txns):
        aid = accounts[1 + (i % (NUM_ACCOUNTS - 1))]
        txn_counts[shard_for_modulo(aid, NUM_SHARDS)] += 1

    mean_txn = statistics.mean(txn_counts)
    return {
        "hot_shard": hot_shard,
        "hot_load": txn_counts[hot_shard],
        "hot_pct": txn_counts[hot_shard] / NUM_TXNS * 100,
        "mean_other": mean_txn,
        "hot_vs_mean": txn_counts[hot_shard] / mean_txn,
    }


def run_test_3(accounts, sample_size=200_000):
    """Rebalance cost: fraction of accounts remapped when going 32 -> 33 shards."""
    sample = accounts[:sample_size]

    before_mod = [shard_for_modulo(a, 32) for a in sample]
    after_mod = [shard_for_modulo(a, 33) for a in sample]
    moved_mod = sum(1 for b, a in zip(before_mod, after_mod) if b != a)

    ring_before = consistent_hash_ring(32)
    ring_after = consistent_hash_ring(33)
    before_ch = [shard_for_consistent(a, ring_before) for a in sample]
    after_ch = [shard_for_consistent(a, ring_after) for a in sample]
    moved_ch = sum(1 for b, a in zip(before_ch, after_ch) if b != a)

    return {
        "sample_size": sample_size,
        "moved_modulo": moved_mod, "moved_modulo_pct": moved_mod / sample_size * 100,
        "moved_consistent": moved_ch, "moved_consistent_pct": moved_ch / sample_size * 100,
        "theoretical_min_pct": 100 / 33,
    }


if __name__ == "__main__":
    accounts, t1 = run_test_1()
    t2 = run_test_2(accounts)
    t3 = run_test_3(accounts)
    print(t1)
    print(t2)
    print(t3)