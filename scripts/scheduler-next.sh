#!/usr/bin/env bash
# Tell the scheduler when to ask again (supabase/migrations/20261113000100_scheduler_wake.sql).
#
# The planner decides the time; this only carries it to Supabase, so no slot logic lives in SQL. It never fails the
# refresh: if the database can't be reached, the scheduler's own safety nets (a 15-minute lease on each dispatch and
# a dispatch anyway after 6 hours with no report) keep refreshes running, just less cheaply.
set -u
say() { echo "scheduler: $1"; }

url="${MODELROOM_ODDS_DB_URL:-${SUPABASE_DB_URL:-}}"
[ -n "$url" ] || { say "no database URL; leaving the wake time alone"; exit 0; }
echo "::add-mask::$url"
command -v psql >/dev/null || { say "psql not available; leaving the wake time alone"; exit 0; }

plan=$(cd modeling && python3 modelroom/refresh_plan.py next 2>&1) || { say "could not work out the next check: $plan"; exit 0; }
at=$(printf '%s' "$plan" | python3 -c 'import json,sys; print(json.load(sys.stdin)["at"])' 2>/dev/null) || { say "unreadable plan: $plan"; exit 0; }
why=$(printf '%s' "$plan" | python3 -c 'import json,sys; print(json.load(sys.stdin)["reason"])' 2>/dev/null)

# :'var' is quoted by psql itself, so a slot id can never be read as SQL. The statement comes in on stdin, not
# through -c, because psql does not interpolate variables into a -c string.
if out=$(PGCONNECT_TIMEOUT=10 psql "$url" -v ON_ERROR_STOP=1 -v at="$at" -v why="${why:-}" -v run="${GITHUB_RUN_ID:-local}" \
         -qtA 2>&1 <<'SQL'
select scheduler.set_next_check(:'at'::timestamptz, :'why', :'run');
SQL
      ); then
  say "next check $out (${why:-no reason given})"
else
  say "could not record the next check (${out}); the safety nets apply"
fi
exit 0
