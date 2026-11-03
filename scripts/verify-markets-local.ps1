# Live check of the Polymarket US and Kalshi integrations, ON YOUR OWN COMPUTER ONLY.
#
#   cd model-room\modeling
#   ..\scripts\verify-markets-local.ps1            (or: ..\scripts\verify-markets-local.ps1 nba)
#
# Exchange data is fetched into modeling\data\markets (gitignored, never committed or published) and
# checked. The console shows counts and pass/fail. Nothing is sent anywhere. Run `python -m modelroom
# nfl ingest` / `nba ingest` first if your local data is old.
param([string]$League = "nfl")
if ($env:GITHUB_ACTIONS -or $env:CI) { Write-Error "Local-only: refusing to run on a hosted runner."; exit 1 }
$env:MODELROOM_ENV = ""
$env:MODELROOM_MARKETS_POLYMARKET_US = "on"
$env:MODELROOM_MARKETS_KALSHI = "on"
$env:MODELROOM_MARKETS_KALSHI_PUBLISH = ""
$env:MODELROOM_LEDGER_DIR = Join-Path $env:TEMP "modelroom-verify-ledger"   # keeps the real ledger untouched
python -m modelroom.markets.verify $League
$code = $LASTEXITCODE
# Rebuild the props board without exchange prices so no price is left in your local published files.
Remove-Item Env:MODELROOM_MARKETS_POLYMARKET_US, Env:MODELROOM_MARKETS_KALSHI
python -m modelroom $League props | Out-Null
exit $code
