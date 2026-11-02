#!/usr/bin/env bash
# Runs the Model Room migrations and security tests against a scratch
# database on any local Postgres 15+ server. Never point this at Supabase.
#
#   PGHOST=localhost PGPORT=5432 PGUSER=postgres npm run db:test
#
# Needs a superuser connection (it creates the anon/authenticated/service_role
# roles if they are missing and creates/drops the model_room_test database).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="${TEST_DB:-model_room_test}"
PSQL=(psql -X -q -v ON_ERROR_STOP=1)

echo "Checking entitlements are in sync with the database..."
node "$ROOT/scripts/check-entitlements-sync.mjs"

echo "Creating scratch database $DB..."
"${PSQL[@]}" -d postgres -c "drop database if exists $DB" >/dev/null
"${PSQL[@]}" -d postgres -c "create database $DB" >/dev/null

# Roles are cluster-wide; create them only if this server doesn't have them.
if [ "$("${PSQL[@]}" -d "$DB" -tAc "select count(*) from pg_roles where rolname in ('anon','authenticated','service_role')")" = "3" ]; then
  sed '/^create role /d' "$ROOT/supabase/tests/supabase_shim.sql" | "${PSQL[@]}" -d "$DB" >/dev/null
else
  "${PSQL[@]}" -d "$DB" -f "$ROOT/supabase/tests/supabase_shim.sql" >/dev/null
fi

echo "Applying migrations..."
for f in "$ROOT"/supabase/migrations/*.sql; do
  echo "  $(basename "$f")"
  "${PSQL[@]}" -d "$DB" -f "$f" >/dev/null
done

echo "Running security tests..."
"${PSQL[@]}" -d "$DB" -f "$ROOT/supabase/tests/rls_test.sql"

if [ "${KEEP_TEST_DB:-}" != "1" ]; then
  "${PSQL[@]}" -d postgres -c "drop database $DB" >/dev/null
fi
