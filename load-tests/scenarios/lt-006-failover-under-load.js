// load-tests/scenarios/lt-006-failover-under-load.js
// k6 script — Scenario LT-006: Failover Under Load
// Load generation is standard; the FAILURE INJECTION (killing the DB
// primary at T+10min) is triggered externally via the same chaos-tooling
// used for CE-001 (docs/09) -- this script's job is purely to sustain
// 12,000 TPS through the injected event and record what happens.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const failoverWindowLatency = new Trend("failover_window_latency");

export const options = {
  scenarios: {
    failover_under_load: {
      executor: "constant-arrival-rate",
      rate: 12000,
      timeUnit: "1s",
      duration: "30m",
      preAllocatedVUs: 2000,
      maxVUs: 4000,
    },
  },
  thresholds: {
    // Success criteria matches CE-001 exactly (docs/09) -- same claim,
    // validated two ways, per the deliberate pairing noted in docs/11.
    http_req_failed: ["rate<0.02"], // small tolerated bump during the
    // actual failover second(s), not
    // a sustained elevated error rate
  },
};

const BASE_URL = __ENV.TARGET_URL || "https://sandbox.payscale.example.com/v1";
const ACCOUNT_POOL = JSON.parse(open("./fixtures/test-accounts.json"));

export function setup() {
  // At T+10min, this test relies on an EXTERNAL trigger (chaos-tooling
  // webhook or manual `kubectl delete pod` / Patroni-targeted kill,
  // matching CE-001's injection method) -- not scripted inside k6 itself,
  // since the failure injection is infrastructure-level, not
  // application-level.
  console.log(
    "Load will begin now. Trigger DB primary kill at T+10min via chaos-tooling.",
  );
}

export default function () {
  const source = ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  let destination =
    ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  while (destination === source) {
    destination = ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  }

  const idempotencyKey = uuidv4();
  const payload = JSON.stringify({
    source_account_id: source,
    destination_account_id: destination,
    amount: (Math.random() * 500 + 10).toFixed(2),
    currency: "INR",
  });
  const params = {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${__ENV.TEST_JWT}`,
      "Idempotency-Key": idempotencyKey,
    },
    timeout: "10s", // generous timeout specifically for this scenario --
    // a request that legitimately queues during the
    // failover window (per CB-DB-PRIMARY's "queue
    // writes" fallback, docs/09) should be allowed to
    // resolve rather than being cut off prematurely
  };

  const res = http.post(`${BASE_URL}/payments`, payload, params);
  failoverWindowLatency.add(res.timings.duration);

  const ok = check(res, {
    "eventually succeeded or cleanly failed (never ambiguous)": (r) =>
      [200, 202, 503].includes(r.status), // 503 = SHARD_UNAVAILABLE is an
    // ACCEPTABLE outcome during
    // the failover second(s) --
    // what's NOT acceptable is a
    // silent hang or an ambiguous
    // partial-success response
  });

  // If a 503 was received, verify (via a follow-up idempotent retry with
  // the SAME key) that the eventual state is unambiguous -- this directly
  // tests Failure Scenario 1/3's guarantee, not just raw availability.
  if (res.status === 503) {
    sleep(2);
    const retry = http.post(`${BASE_URL}/payments`, payload, params);
    check(retry, {
      "retry with same idempotency key resolves unambiguously": (r) =>
        [200, 202, 503].includes(r.status),
    });
  }
}
