#!/usr/bin/env bash
# Resolve a reachable connection to the TEST Supabase database from the SUPABASE_DB_URL secret and export it as
# MODELROOM_ODDS_DB_URL for later steps (masked in logs; never printed). Direct db.<ref>.supabase.co addresses are
# IPv6-only on GitHub's runners, so the Session pooler for the same project is tried, as the health check does.
# Exit 0 with ODDS_STORE=off in $GITHUB_ENV if nothing is reachable, so a refresh can carry on without it.
set -u
off() { echo "ODDS_STORE=off" >> "$GITHUB_ENV"; echo "odds store: not reachable ($1)"; exit 0; }
[ -n "${SUPABASE_DB_URL:-}" ] || off "SUPABASE_DB_URL is not set"
echo "::add-mask::$SUPABASE_DB_URL"
command -v psql >/dev/null || sudo apt-get install -y -qq postgresql-client >/dev/null 2>&1 || true
url=""
case "$SUPABASE_DB_URL" in
  *db.*.supabase.co*)
    for host in aws-0-us-east-1 aws-1-us-east-1 aws-0-us-east-2 aws-1-us-east-2 aws-0-us-west-1 aws-1-us-west-1 aws-0-us-west-2 aws-1-us-west-2 aws-0-ca-central-1 aws-1-ca-central-1 aws-0-eu-west-1 aws-1-eu-west-1 aws-0-eu-west-2 aws-1-eu-west-2 aws-0-eu-central-1 aws-1-eu-central-1; do
      cands=$(HOST="$host.pooler.supabase.com" python3 scripts/pooler-url.py 2>/dev/null) || continue
      while IFS= read -r c; do
        echo "::add-mask::$c"
        PGCONNECT_TIMEOUT=8 psql "$c" -qtAc "select 1" >/dev/null 2>&1 && { url="$c"; break; }
      done <<< "$cands"
      [ -n "$url" ] && break
    done;;
  *) PGCONNECT_TIMEOUT=8 psql "$SUPABASE_DB_URL" -qtAc "select 1" >/dev/null 2>&1 && url="$SUPABASE_DB_URL";;
esac
[ -n "$url" ] || off "no connection"
PGCONNECT_TIMEOUT=8 psql "$url" -qtAc "select 1 from odds.snapshots limit 1" >/dev/null 2>&1 || off "odds.snapshots table missing"
echo "::add-mask::$url"
{ echo "MODELROOM_ODDS_DB_URL=$url"; echo "ODDS_STORE=on"; } >> "$GITHUB_ENV"
echo "odds store: connected"
