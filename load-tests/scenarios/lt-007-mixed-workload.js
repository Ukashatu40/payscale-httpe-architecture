// load-tests/scenarios/lt-007-mixed-workload.js
// k6 script — Scenario LT-007: Mixed Workload
// 60% P2P / 20% balance check / 10% merchant / 5% reversal / 5% other,
// at 12,000 TPS aggregate, per the exact mix specified in docs/00 §2.

import http from "k6/http";
import { check } from "k6";
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

export const options = {
  scenarios: {
    p2p_payments: {
      executor: "constant-arrival-rate",
      rate: 7200, // 60% of 12,000
      timeUnit: "1s",
      duration: "60m",
      preAllocatedVUs: 1200,
      maxVUs: 2400,
      exec: "submitP2P",
    },
    balance_checks: {
      executor: "constant-arrival-rate",
      rate: 2400, // 20% of 12,000
      timeUnit: "1s",
      duration: "60m",
      preAllocatedVUs: 400,
      maxVUs: 800,
      exec: "checkBalance",
    },
    merchant_payments: {
      executor: "constant-arrival-rate",
      rate: 1200, // 10% of 12,000
      timeUnit: "1s",
      duration: "60m",
      preAllocatedVUs: 200,
      maxVUs: 400,
      exec: "submitMerchantPayment",
    },
    reversals: {
      executor: "constant-arrival-rate",
      rate: 600, // 5% of 12,000
      timeUnit: "1s",
      duration: "60m",
      preAllocatedVUs: 100,
      maxVUs: 200,
      exec: "submitReversal",
    },
    // remaining 5% ("other") omitted from this script -- represents
    // settlement/fee/status-webhook traffic exercised separately by
    // LT-002's settlement-specific extension; not scripted here to keep
    // this file focused on the four dominant, distinctly-shaped request
    // types
  },
  thresholds: {
    "http_req_duration{scenario:p2p_payments}": ["p(99)<100"],
    "http_req_duration{scenario:balance_checks}": ["p(99)<50"], // reads
    // should
    // be
    // faster
    // than
    // writes
    "http_req_duration{scenario:reversals}": ["p(99)<30000"], // FR-005's
    // 30s SLA,
    // checked
    // as a
    // hard
    // threshold
    // here
  },
};

const BASE_URL = __ENV.TARGET_URL || "https://sandbox.payscale.example.com/v1";
const ACCOUNT_POOL = JSON.parse(open("./fixtures/test-accounts.json"));
const MERCHANT_POOL = JSON.parse(open("./fixtures/test-merchants.json"));
const RECENT_TXN_POOL = JSON.parse(
  open("./fixtures/recent-completed-txns.json"),
);

function authHeaders(extra) {
  return {
    headers: Object.assign(
      {
        "Content-Type": "application/json",
        Authorization: `Bearer ${__ENV.TEST_JWT}`,
      },
      extra,
    ),
  };
}

export function submitP2P() {
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
  const res = http.post(
    `${BASE_URL}/payments`,
    payload,
    authHeaders({ "Idempotency-Key": uuidv4() }),
  );
  check(res, { "P2P submitted": (r) => [200, 202].includes(r.status) });
}

export function checkBalance() {
  const account = ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  const res = http.get(`${BASE_URL}/accounts/${account}`, authHeaders({}));
  check(res, { "balance retrieved": (r) => r.status === 200 });
}

export function submitMerchantPayment() {
  const source = ACCOUNT_POOL[Math.floor(Math.random() * ACCOUNT_POOL.length)];
  const merchant =
    MERCHANT_POOL[Math.floor(Math.random() * MERCHANT_POOL.length)];
  const payload = JSON.stringify({
    source_account_id: source,
    destination_account_id: merchant,
    amount: (Math.random() * 5000 + 50).toFixed(2),
    currency: "INR",
  });
  const res = http.post(
    `${BASE_URL}/payments`,
    payload,
    authHeaders({ "Idempotency-Key": uuidv4() }),
  );
  check(res, {
    "merchant payment submitted": (r) => [200, 202].includes(r.status),
  });
}

export function submitReversal() {
  const txnId =
    RECENT_TXN_POOL[Math.floor(Math.random() * RECENT_TXN_POOL.length)];
  const payload = JSON.stringify({ reason: "CUSTOMER_REQUEST" });
  const res = http.post(
    `${BASE_URL}/transactions/${txnId}/reversal`,
    payload,
    authHeaders({ "Idempotency-Key": uuidv4() }),
  );
  check(res, {
    "reversal resolved within SLA": (r) => [200, 409].includes(r.status),
    // 409 is acceptable here (fixture pool may include already-reversed
    // transactions from a prior test run) -- what fails the check is
    // exceeding the p99<30000ms threshold, enforced separately above
  });
}
