#!/usr/bin/env bash
# scripts/apply-ddl.sh
# Applies all schema DDL files in the correct dependency order against a
# target PostgreSQL+Citus database. Never run in this project (per
# evidence/README.md's honesty note) -- provided so it's ready to run
# the first time a real database instance exists.

set -euo pipefail

DB_URL="${1:?Usage: apply-ddl.sh <postgresql-connection-string>}"

DDL_DIR="$(dirname "$0")/../schemas/ddl"

echo "Applying DDL to: $DB_URL"

# Order matters: 000 sets up extensions/roles/helper functions that every
# subsequent file depends on (Citus extension, uuid_generate_v7(),
# app_write_role, set_updated_at()). 001/002 (accounts/transactions) must
# precede everything that foreign-keys into them (003-008).
for file in 000-extensions-and-helpers 001-accounts 002-transactions \
            003-ledger-entries 004-users 005-transaction-events \
            006-fraud-rules 007-merchant-settlements 008-notification-log; do
  echo "--- Applying ${file}.sql ---"
  psql "$DB_URL" -v ON_ERROR_STOP=1 -f "${DDL_DIR}/${file}.sql"
done

echo "All DDL applied successfully."
echo "NOTE: users (004) and fraud_rules (006) reference accounts/transactions"
echo "via FK in some designs -- if you see a dependency error, check"
echo "schemas/ddl comments for the specific FK direction before reordering."