// load-tests/scenarios/lt-002-target-load.js
// k6 script — Scenario LT-002: Target Load (12,000 TPS sustained, 60 min)

import http from "k6/http";
import { check } from "k6";
import { Trend, Rate } from "k6/metrics";
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const p99Latency = new Trend("custom_p99_latency");
const errorRate = new Rate("custom_error_rate");

export const options = {
  scenarios: {
    target_load: {
      executor: "constant-arrival-rate",
      rate: 12000, // 12,000 iterations per timeUnit
      timeUnit: "1s",
      duration: "60m",
      preAllocatedVUs: 2000, // sized generously above expected concurrency
      maxVUs: 4000,
    },
  },
  thresholds: {
    // Pass/fail criteria directly from docs/11's LT-002 row -- not
    // invented separately from the strategy doc.
    http_req_duration: ["p(50)<30", "p(99)<100", "p(99.9)<250"],
    custom_error_rate: ["rate<0.001"], // <0.1%
  },
};

const BASE_URL = __ENV.TARGET_URL || "https://sandbox.payscale.example.com/v1";

// Pre-generated pool of valid test account IDs (provisioned before the run,
// not created inline -- account creation is out of scope for this scenario,
// which tests the PAYMENT path specifically).
const ACCOUNT_POOL = JSON.parse(open("./fixtures/test-accounts.json"));

export default function () {
  const source = ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  let destination =
    ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  while (destination === source) {
    destination = ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  }

  const payload = JSON.stringify({
    source_account_id: source,
    destination_account_id: destination,
    amount: (Math.random() * 1000 + 10).toFixed(2),
    currency: "INR",
  });

  const params = {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${__ENV.TEST_JWT}`,
      "Idempotency-Key": uuidv4(), // fresh key per iteration -- this
      // scenario tests the NOVEL-request
      // path, not idempotency-replay
      // behavior (that's a separate,
      // smaller correctness test, not a
      // load scenario)
    },
  };

  const res = http.post(`${BASE_URL}/payments`, payload, params);

  const ok = check(res, {
    "status is 200 or 202": (r) => r.status === 200 || r.status === 202,
    "response has transaction_id": (r) =>
      JSON.parse(r.body).transaction_id !== undefined,
  });

  errorRate.add(!ok);
  p99Latency.add(res.timings.duration);
}
