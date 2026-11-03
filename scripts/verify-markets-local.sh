#!/usr/bin/env bash
# Live check of the Polymarket US and Kalshi integrations, ON YOUR OWN COMPUTER ONLY.
#   cd model-room/modeling && ../scripts/verify-markets-local.sh [nfl|nba]
# Exchange data stays in modeling/data/markets (gitignored); the console shows counts and pass/fail.
set -euo pipefail
league="${1:-nfl}"
if [ -n "${GITHUB_ACTIONS:-}" ] || [ -n "${CI:-}" ]; then echo "Local-only: refusing to run on a hosted runner." >&2; exit 1; fi
export MODELROOM_ENV="" MODELROOM_MARKETS_KALSHI_PUBLISH=""
export MODELROOM_LEDGER_DIR="${TMPDIR:-/tmp}/modelroom-verify-ledger"
code=0
MODELROOM_MARKETS_POLYMARKET_US=on MODELROOM_MARKETS_KALSHI=on python -m modelroom.markets.verify "$league" || code=$?
python -m modelroom "$league" props > /dev/null   # leave the local board without exchange prices
exit $code
