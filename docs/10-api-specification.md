<!-- docs/10-api-specification.md -->

# API Specification

Full spec: `api/openapi.yaml`. Validate at editor.swagger.io before submission (per E5 workflow tip — validation errors cost 15 points).

## Error Code Table

| HTTP Status | `error.code`                  | Meaning                                                             |
| ----------- | ----------------------------- | ------------------------------------------------------------------- |
| 400         | `MALFORMED_REQUEST`           | Request body fails schema validation                                |
| 401         | `UNAUTHORIZED`                | Missing/invalid JWT                                                 |
| 404         | `NOT_FOUND`                   | Resource does not exist                                             |
| 409         | `IDEMPOTENCY_KEY_IN_PROGRESS` | Duplicate concurrent request (idempotency-handler.py's `409` path)  |
| 409         | `REVERSAL_NOT_ELIGIBLE`       | Transaction already reversed or in a non-reversible state           |
| 422         | `INSUFFICIENT_FUNDS`          | Maps to `transactions.failure_reason` in schemas/ddl/002            |
| 422         | `FRAUD_DETECTED`              | Blocked by Stage 1 fraud rules (docs/09)                            |
| 422         | `ACCOUNT_FROZEN`              | Source or destination account not ACTIVE                            |
| 429         | `RATE_LIMIT_EXCEEDED`         | Tier-based rate limit hit (see table below)                         |
| 500         | `INTERNAL_ERROR`              | Unexpected server error, correlation_id included for support lookup |
| 503         | `SHARD_UNAVAILABLE`           | Maps directly to Failure Scenario 1 (docs/04)                       |

## Rate Limiting Per Endpoint and Account Tier

Directly implements the `accounts.tier` enum's stated limits (schemas/ddl/001): BASIC 50 TPS, PREMIUM 200 TPS, MERCHANT 1000 TPS — enforced at the API Gateway (docs/03) via the Redis-backed rate-limit counter, checked before the request reaches the Orchestrator.

| Endpoint                                 | Basis                          | Notes                                                                                                                                            |
| ---------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POST /payments`                         | Per-account tier limit (above) | The only endpoint where the tier limits directly apply — this is the financial write path                                                        |
| `GET /transactions/*`, `GET /accounts/*` | Flat 500 req/min per API key   | Read endpoints get a generous flat limit, independent of account tier, since read volume doesn't carry the same fraud/abuse risk as write volume |
| `POST /transactions/{id}/reversal`       | 10 req/min per account         | Deliberately tight — reversal is a sensitive operation; this limit is about abuse prevention, not capacity                                       |
| `POST /merchants/{id}/settlements`       | 5 req/hour per merchant        | Settlement batches are inherently infrequent (scheduled), so this limit exists purely to catch misconfigured retry loops, not real usage         |

`429` responses include a `Retry-After` header (seconds), computed from the caller's specific rate-limit window reset time — not a fixed constant.

## Cursor Pagination Design

`GET /accounts/{accountId}/transactions` uses opaque cursor pagination (not offset-based), because offset pagination degrades badly at this data volume — an `OFFSET 500000` query on a Citus-sharded, time-partitioned table (docs/05, docs/06) would force a full scan-and-discard across shards, while a cursor (internally, a base64-encoded `(created_at, transaction_id)` tuple) lets the query resume directly from an indexed position using the existing `idx_transactions_source_account` composite index (docs/05) — no re-scanning of already-seen rows regardless of how deep the pagination goes.

## Why Amounts Are Strings, Not Numbers

`amount`, `available_balance`, etc. are typed as `string` in the OpenAPI schema, not `number`. JSON's `number` type has no guaranteed decimal precision across different client-language JSON parsers (JavaScript's `Number` is a float64, which cannot exactly represent many decimal currency values) — this would risk a client silently rounding a value that must match `NUMERIC(18,4)` exactly at the database layer. Every financial-amount field is a decimal string for this reason, consistently across the entire spec.
