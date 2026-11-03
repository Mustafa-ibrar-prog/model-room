# Market data: Polymarket US, Kalshi, manual CSV

Exchange prices are compared with the prop model **after** it has produced its own probabilities. They are never an input to the model.

## Providers

| | Polymarket US | Kalshi | Manual CSV |
|---|---|---|---|
| Module | `modelroom/markets/polymarket_us.py` | `modelroom/markets/kalshi.py` | `modelroom/markets/manual.py` |
| Access | `https://gateway.polymarket.us`, public, no key | `https://api.elections.kalshi.com/trade-api/v2`, public reads, no key | `modeling/data/manual/nfl_props.csv` |
| Contract | "Player N+ stat" yes/no, `line` = N | One series per stat (`KXNFLRECYDS`), `floor_strike` 49.5 + `strike_type` greater = 50+ | Your rows: `>=` N or `>` line |
| Prices | best bid / ask (Yes side); no sizes in the listing | yes/no bid and ask with sizes | as entered (American odds converted) |
| Fee | `feeCoefficient` per market (≈ 0.07 × p × (1−p)) | ≈ 0.07 × p × (1−p) per contract, rounded up per order | 0 |
| Player match | name + team | Sportradar ID → nflverse rosters, then name + team | name + team |
| Rate limit | not published; client waits 2 s, honours Retry-After | Basic tier ≈ 20 reads/s; client stays at 4/s | n/a |
| If the player doesn't play | settles at last fair price | settles at fair price before kickoff; **fantasy: scores 0** | as stated |
| Fantasy scoring | ESPN PPR (INT −2) | Sleeper full PPR (INT −1) | as stated |
| Skipped | first-TD, team and game markets | "Protected" series (different settlement) | invalid rows, listed |

The two exchanges' contracts are **not** assumed to be the same: thresholds, operators, fantasy scoring and inactive-player rules are kept per quote, and the model prices each one on its own terms (it simulates both fantasy scorings).

## Switching providers on

Everything is off by default.

```powershell
$env:MODELROOM_MARKETS_POLYMARKET_US = "on"
$env:MODELROOM_MARKETS_KALSHI = "on"          # local use only; see terms below
python -m modelroom markets status
python -m modelroom markets fetch nfl          # one snapshot from each enabled provider
python -m modelroom nfl props                  # re-run props to compare against the latest snapshot
```

The whole loop in one command (fetch → props → order-book depth for flagged Polymarket contracts → props again):

```powershell
python -m modelroom markets refresh nfl
python -m modelroom markets refresh nba
```

Run `markets fetch` (or `refresh`) as often as you like (e.g. every hour on game days); each run appends a timestamped snapshot to `modeling/data/markets/snapshots/<provider>/nfl/<date>.jsonl`. These files are the history for price movement, exchange-vs-exchange comparison and closing-line value. `data/` is never committed.

Kalshi credentials (`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`) are not needed to read prices and are not used by this code. If trading is ever added, it goes in a separate module with its own key handling.

## Measuring results: ROI and closing-line value

Every props run with prices appends what the model said about each contract to `data/markets/evaluations/<league>.jsonl`, along with the price it saw. After the games:

```powershell
python -m modelroom markets report nfl     # writes data\markets\reports\nfl.json
```

The report covers settled contracts only. Players who didn't play are void. It breaks results down by provider, market, edge grade, confidence and model version:

- **Accuracy:** the model's log loss and Brier score next to the market mid's, on the same contracts. This is the honest test of whether the model knows something the market doesn't.
- **ROI:** one contract on every lean and strong edge, bought at the ask the model saw, after fees.
- **CLV:** the price you got vs the last price before kickoff. Positive CLV means the market moved toward the model after it flagged the edge.
- **Market moved toward the model:** the share of contracts where the close moved in the model's direction from the price it saw.

**Backfilling Kalshi history** (local only, no key):

```powershell
python -m modelroom markets backfill nfl --days 30   # hourly prices of settled Kalshi contracts
python -m modelroom markets replay nfl               # walk-forward model prices them as of 3 h before each game
python -m modelroom markets report nfl
```

Replayed rows carry the model version plus `+replay`, so they're reported separately from live runs.

The backfill makes one request per contract, which is roughly 10,000 per NFL week across all stat series. `--days` and the built-in 3,000-contract cap keep it bounded, and responses are cached, so re-running costs nothing. Polymarket US has no working public history query, so its history starts from your own snapshots.

## When an edge is shown

Model probability `p` against the price you could actually pay (the ask), after the exchange fee:

- **EV of buying Yes** = p − ask − fee. **EV of buying No** = (1 − p) − No ask − fee.
- A quote isn't used if it's **stale** (captured over 20 minutes before the model run), **one-sided**, **wider than 6¢**, **thin** (under 50 contracts at the ask, where sizes are published), closed, unmatched to a player, or a **different contract** (e.g. "scores 0 if inactive").
- **Lean**: EV ≥ 2¢ per $1 on a usable quote.
- **Strong**: EV ≥ 4¢ **and** the player has enough history ("ok" support), **and** that market type was well calibrated (expected calibration error ≤ 3%) and beat the baseline in the held-out backtest, **and** the size at that price is published and at least 50 contracts. A lean shows which of these it failed.

Polymarket's listing has no sizes, so its prices can produce a lean but not a strong edge until order-book depth is fetched for that contract.

## Terms and production

Checked 2026-11-02. Re-check before launch.

- **Polymarket US** participant agreement §I.22: data is proprietary to PMUS and "may not be redistributed except as PMUS expressly permits".
- **Kalshi** Developer Agreement §3, §3.1, §3.5: use is limited to facilitating your own trading; collecting, storing or sharing data with third parties needs prior written authorization; no benchmarking or competitive use.

So:

- With `MODELROOM_ENV=production`, every provider is off until `MODELROOM_MARKETS_REDISTRIBUTION_OK=true` is set after written permission.
- Kalshi prices are kept out of the published board even when Kalshi is on. They go to a local file (`data/output/nfl/props_compare_local.json`) unless `MODELROOM_MARKETS_KALSHI_PUBLISH=on`.
- The hosted preview doesn't fetch exchange prices, because the GitHub repository is public and the published board is committed there.

## Settlement grading (official exchange settlement)

`python -m modelroom markets settle nfl|nba` asks each enabled exchange which priced markets have officially settled, records what it says, and grades the model's predictions. `markets refresh` runs it at the end of every loop, so it's automatic wherever the market loop is scheduled.

- **What counts as a prediction:** the last one the model made before the game started, with the price seen then. Records live in `data/markets/evaluations/<league>.jsonl` and are never rewritten. The engines never see a price or a settlement.
- **What counts as settled:**
  - **Kalshi:** `status` is `finalized` with `result` yes/no; `settlement_ts` is recorded as the settlement time. `determined`, `amended` and `disputed` mean a result exists but the settlement window is still open, so the market stays **Pending**. A settlement value between 0 and 1 counts as **Void**.
  - **Polymarket US:** `status` is `MARKET_STATUS_RESOLVED`, and the long side settled at 1 or 0. A settlement in between means the market settled at its last fair price (for example, the player never took a snap), which counts as **Void**. A missing or contradictory value stays **Pending**; outcomes are never guessed. Polymarket publishes no settlement time, so its `updatedAt` at resolution is recorded instead.
  - **Manual CSV prices** have no settlement feed, so they are never graded.
- **Grades:** each market is graded on its own.
  - **Correct (green):** the side the model put above 50% is the side that settled.
  - **Incorrect (red):** the other side settled.
  - **Void / refunded (gray).**
  - **Pending settlement (yellow).**
  - The game ending, or a box score, never grades anything; the actual stat or final score is shown only as context.
- **Corrections:** observations are append-only (`data/markets/settlements/<league>.jsonl`). A changed result is written as a correction, and the earlier observation is kept.
- **Game markets:** winner, spread and total, from the Kalshi series `KX{NFL,NBA}{GAME,SPREAD,TOTAL}` and the Polymarket US moneyline / spreads / totals markets. The model's probability is:
  - **Winner:** the engine's own win probability.
  - **Spread and total:** a normal approximation from its projected margin or total and the published 80% range. These aren't separately calibrated, so they can only ever be "lean", never "strong".
- **What the site shows:** `data/published/market_results_<league>.json` holds only providers whose data may be published (see markets.config). Kalshi stays local unless `MODELROOM_MARKETS_KALSHI_PUBLISH=on`. The test site's CI never fetches exchange data, because the repo is public and the providers' terms don't allow republishing it, so its record stays empty and says why.
- **Accuracy, not profit:** no trades are placed, so no ROI is claimed. The older `markets report` is a local research tool that settles against box scores and reports hypothetical ROI; it doesn't feed the site.

## Live integration check

**Kalshi: local only.** Kalshi is checked only on your own computer, until Kalshi confirms in writing that fetch-and-discard testing on hosted runners is allowed. The check refuses to contact Kalshi when it detects a CI runner. To check it, from the `modeling` folder:

```
..\scripts\verify-markets-local.ps1 nfl        (Windows PowerShell)
../scripts/verify-markets-local.sh nfl          (macOS / Linux)
```

Exchange data stays in `modeling/data/markets`, which is never committed. Afterwards the script rebuilds your local props board without prices, so no price is left in your local published files.

**Polymarket US: GitHub or local.** From GitHub, use Actions → **Verify market integrations** → Run workflow. It runs in a throwaway runner and goes through these steps:
1. Fetches the exchange and checks every field (bid ≤ ask, sizes, fee, quote age).
2. Checks each threshold against the contract's own title.
3. Runs the props model with the prices, audits how each quote was matched to a player, and re-derives implied probability, fee and edge.
4. Runs the model again without prices and confirms the probabilities are identical.
5. Parses recently settled markets.

The log shows counts and pass/fail only. Nothing is committed, uploaded or published.

Normalization worth knowing: on whole-number stats, Kalshi's "more than 49.5" is stored as "50+", the same contract as Polymarket's "50+". Fantasy points keep "more than 14.5", because scores have decimals. A listing with its bid above its ask is flagged "crossed book" and never priced.
