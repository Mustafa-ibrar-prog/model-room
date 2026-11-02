# Model Room data and modeling (Python)

NBA and NFL data collection, validation and projection engines. The website (Next.js) lives one folder up and reads only the published output files.

## Status

- **Data collection and validation:** working for both leagues.
- **NBA engine 1.1.0:** live on the site, provisional. Backtest: `../docs/models/results/`.
- **NFL engine 1.0.1:** live on the site, provisional.

See `../docs/data-inventory.md` for every source and `../docs/data-sources.md` for the rules.

## Windows setup

1. **Install Python 3.12** from python.org. Tick **"Add python.exe to PATH"**.
2. **Install Git for Windows**, then clone the repo:
   ```powershell
   git clone https://github.com/Mustafa-ibrar-prog/model-room.git
   cd model-room\modeling
   ```
3. **Create a virtual environment and install:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   pip install -e .[dev]
   ```
4. **Optional settings** (PowerShell, current window):
   ```powershell
   $env:ODDS_API_KEY = "your-key"          # only for sportsbook lines; everything else works without it
   $env:MODELROOM_DATA_DIR = "D:\ModelRoomData"   # default is modeling\data
   ```

macOS/Linux: same steps, with `source .venv/bin/activate`.

## Collect and validate data

```powershell
python -m modelroom nba ingest            # hoopR schedules, team and player box scores (about 30 MB)
python -m modelroom nfl ingest            # nflverse games, play-by-play (last 3 seasons + current), injuries
python -m modelroom nba crosscheck        # Land of Basketball score check (20 s between pages; ~3 min per season)
python -m modelroom sources validate      # columns, coverage, missing values, duplicates, plausibility
python -m modelroom sources inventory --docs   # rebuild docs/data-inventory.md
```

Optional sportsbook lines:

```powershell
python -m modelroom nba odds              # The Odds API (needs ODDS_API_KEY)
python -m modelroom nba lines             # your manual CSV: data\manual\nba_lines.csv
python -m modelroom nfl lines             # data\manual\nfl_lines.csv
```

Copy `templates\lines_template.csv` to `data\manual\<league>_lines.csv` and fill one row per sportsbook line. Required: `game_date`, `home_team`, `away_team`, `sportsbook`, `market` (spread/total/moneyline), and `line` for spreads and totals. `captured_at` needs a timezone, e.g. `2026-11-02T18:30:00-08:00`. Rows that fail validation are listed and skipped.

## Projections, backtests and the ledger

```powershell
python -m modelroom nba project           # ratings -> next 7 days -> ledger -> data\published\nba.json
python -m modelroom nfl project           # next 10 days -> ledger -> data\published\nfl.json
python -m modelroom nba backtest          # walk-forward tuning + held-out test (~3 min); rewrites params.json
python -m modelroom nfl backtest          # same for NFL (~5 min)
python -m modelroom ledger verify         # check the prediction ledgers' hash chains
```

The website reads `data\published\<league>.json`. Re-run `project` after each `ingest`.

Ledger rules:
- A prediction is stored only before kickoff.
- Lines are never edited, and every record carries the model version, parameter hash and input hash.
- A model change gets a new version; its predictions are added alongside the old ones.
- Grading joins the stored predictions to final results without changing the file.

## Tests

```powershell
pytest                                   # all tests
pytest tests\nba                         # NBA engine only
pytest tests\nfl                         # NFL only
pytest tests\sources                     # data collection and validation only
```

- **Unit tests** use small synthetic inputs, created inside the tests and never saved, to check math and parsers.
- **Data tests** run against your downloaded data and skip if you haven't ingested yet.

## Folders

```
modelroom/
  common/     paths, downloads, hashing, metrics, ledger, publishing (no league logic)
  sources/    registry (inventory), validation, reconciliation, odds, Land of Basketball
  nba/        NBA ingestion, ratings, projections, backtest, pipeline
  nfl/        NFL ingestion, EPA ratings, QB adjustment, projections, backtest, pipeline
data/         gitignored: raw/ (as downloaded), processed/, output/, manual/
ledger/       append-only prediction ledgers (committed)
templates/    manual line entry template
```
