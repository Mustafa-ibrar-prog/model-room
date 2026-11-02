# Model Room

NFL and NBA projections from real data: the model's line, total, projected score and win probability next to the market line, with every model tested on seasons it never saw.

## Status

| Part | State |
| --- | --- |
| NBA engine | **Live**, version 1.1.0, provisional. hoopR data from 2015-16 to now. |
| NFL engine | **Live**, version 1.0.1, provisional. nflverse play-by-play, 2018 to now. |
| Website | Reads the engines' published boards. No demo or fictional data anywhere. |
| NFL player props | **Live**, version 0.1.0, provisional. Own simulation per player; 13 markets; calibrated per market. |
| Prop market data | Optional, off by default: Polymarket US, Kalshi, manual CSV. Compared after the model, never an input. |
| Prediction ledger | Every pre-game projection stored, hash-chained, never edited (games and props). |
| Market lines | NFL: nflverse's published line. NBA: optional (Odds API key or manual CSV). |
| Not built | NBA player props, NBA injury feed, Shopify login and billing (design in `docs/auth-architecture.md`). |

Backtests (held-out seasons, never used for tuning):

| | Games | Margin error | Total error | Market margin error |
| --- | --- | --- | --- | --- |
| NBA 1.1.0 (2022-23 to 2025-26) | 5,282 | 10.97 | 14.66 | not available |
| NFL 1.0.1 (2023 to 2025) | 855 | 10.21 | 10.35 | 9.79 |

The NFL model is less accurate than the market line, and no claim is made that either model beats the market. Reports: `docs/models/results/`.

NFL props 0.1.0 (2023 to 2025, 502,813 thresholds across 13 markets): log loss 0.418 vs 0.446 for each player's recent hit rate, calibration error 1.1%. That measures probability accuracy only; there's no historical prop-price data, so no ROI or closing-line value yet. Details: `docs/models/nfl-props.md`.

## Run it locally on Windows

You need **Node.js 22 LTS** (nodejs.org), **Python 3.12** (python.org, tick "Add python.exe to PATH") and **Git**. No database, domain, Shopify or paid API is needed.

Open **PowerShell**:

```powershell
# 1. Get the code
git clone https://github.com/Mustafa-ibrar-prog/model-room.git
cd model-room

# 2. Website dependencies and settings
npm install
Copy-Item .env.example .env.local

# 3. Python engines
cd modeling
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e .[dev]

# 4. Download and check the data (about 220 MB, a few minutes)
python -m modelroom nba ingest
python -m modelroom nfl ingest
python -m modelroom sources validate

# 5. Generate projections (writes modeling\data\published\*.json and the ledger)
python -m modelroom nba project
python -m modelroom nfl project
python -m modelroom nfl props

# 6. Start the site
cd ..
npm run dev
```

Open http://localhost:3000. The bar under the header shows each league's data status (Current, Delayed or Unavailable) and the last model run.

**Daily refresh** (from `model-room\modeling` with the venv active):

```powershell
python -m modelroom nba ingest; python -m modelroom nfl ingest
python -m modelroom nba project; python -m modelroom nfl project; python -m modelroom nfl props
```

**Prop prices from Polymarket US / Kalshi** (optional, your machine only; read `docs/markets.md` for the terms first):

```powershell
$env:MODELROOM_MARKETS_POLYMARKET_US = "on"; $env:MODELROOM_MARKETS_KALSHI = "on"
python -m modelroom markets fetch nfl      # stores a timestamped snapshot
python -m modelroom nfl props              # compares the model with the latest snapshot
```

The site reads the new files on the next page load; no restart is needed.

**Seeing paid-plan fields:** `.env.local` sets `ENABLE_TIER_PREVIEW=true`. Use the Free / Plus / Pro switcher at the bottom of any page. Free sees model lines and totals; Plus adds projected scores, win probabilities and every edge; Pro adds rating breakdowns and pre-game projections for finished games.

**Optional sportsbook lines:**

```powershell
$env:ODDS_API_KEY = "your-key"            # free tier: 500 credits a month
python -m modelroom nba odds              # or: python -m modelroom nba lines  (manual CSV)
python -m modelroom nba project
```

Manual CSV template: `modeling\templates\lines_template.csv` → copy to `modeling\data\manual\nba_lines.csv`. Bad rows are listed with the reason and skipped.

**Re-running the backtests** (optional; 3 to 5 minutes each; they rewrite `params.json`):

```powershell
python -m modelroom nba backtest
python -m modelroom nfl backtest
python -m modelroom nfl props-backtest     # about 20 minutes; rewrites nfl\props\params.json
```

## Private online preview

A protected Vercel preview, refreshed daily by a GitHub Action, so you can test from a phone without your PC. Setup and safety notes: [docs/preview-deploy.md](docs/preview-deploy.md).

## Tests

```powershell
npm run lint
npx tsc --noEmit
npm test                       # website data layer: gating, missing data, unavailable states
npm run build                  # production build
cd modeling; pytest            # engines, data validation, ledger, boards (data tests use your downloaded data)
python -m modelroom ledger verify
```

Database security tests (`npm run db:test`) need a local PostgreSQL superuser; see `docs/database.md`.

## How it fits together

```
modeling/ (Python)                                     src/ (Next.js)
  ingest    raw files -> data/raw, data/processed        server/engine/board.ts   reads published JSON per request
  validate  coverage, duplicates, missing, conflicts     server/data/             gates every premium field per plan
  engines   nba/  nfl/  (separate; no shared model code) components/tables/       game board, results, ratings, injuries
  project   -> data/published/<league>.json  ----------> app/ nfl, nba, home, ratings, injuries
            -> ledger/<league>.jsonl (append-only)
```

- **Missing data is shown as missing.** No market line means no edge. No injury feed means "not connected". If a board is absent or unreadable, the page says so instead of showing anything made up.
- **Premium data never leaves the server unless the plan includes it.** That covers HTML, React payloads and `/api/v1/games`.
- **Every projection records its model version, parameter hash and input hash.** A model change gets a new version, and older ledger entries stay.

## More documentation

- `modeling/README.md`: engine commands and folders
- `docs/models/nba.md`, `docs/models/nfl.md`, `docs/models/nfl-props.md`: methodology
- `docs/markets.md`: Polymarket US, Kalshi and manual prop prices; edge rules; terms
- `docs/models/results/`: backtest reports, including superseded versions
- `docs/data-sources.md`, `docs/data-inventory.md`: sources, terms, coverage
- `docs/database.md`, `docs/auth-architecture.md`: Supabase schema and the planned Shopify login (not needed to run locally)

## Design tokens

Defined in `src/app/globals.css`: navy background, **blue = market**, **teal = model**, **orange = edge**. Barlow Condensed for headings and numbers, Barlow for text.
