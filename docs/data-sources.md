# Data sources

What each engine reads, what it costs, and what it can't do. Checked November 2026.

## Summary

| Need | NFL source | NBA source | Status |
| --- | --- | --- | --- |
| Schedules and results | nflverse `games.csv` | hoopR `nba_schedule_<season>.parquet` | Connected |
| Team box scores | nflverse play-by-play (aggregated) | hoopR `team_box_<season>.parquet` | NBA connected; NFL needs play-by-play download |
| Play-by-play (EPA) | nflverse `play_by_play_<season>.parquet` | not used | Download on your PC (GitHub release file) |
| Starting quarterbacks | nflverse `games.csv` (`home_qb_id`, `away_qb_id`) | n/a | Connected |
| Rest days | nflverse `games.csv` (`home_rest`, `away_rest`) | computed from the schedule | Connected |
| Injuries | nflverse `injuries_<season>.parquet` | NBA official injury report (no free structured feed) | NFL after download; NBA not connected |
| Spreads and totals | nflverse `games.csv` (`spread_line`, `total_line`) | The Odds API (paid key) | NFL connected; NBA not connected |

Missing feeds show as "Not connected" in the app, never as zero.

## nflverse (NFL)

- **What:** schedules, results, spreads, totals, rest, starting QBs and stadiums in `nfldata/data/games.csv`. Play-by-play with EPA, success and win probability in `nflverse-data` release files. Injury reports in `nflverse-data` release files.
- **URLs:**
  - `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`
  - `https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_<season>.parquet`
  - `https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_<season>.parquet`
- **Cost:** free.
- **License:** nflverse-data is released under **CC-BY 4.0**. Credit nflverse wherever the data or anything derived from it is shown. The site footer credits each source.
- **Update frequency** (nflverse's published schedule): `games.csv` refreshes about every 5 minutes in season. Play-by-play updates nightly after game days; stat corrections settle by Thursday.
- **Credentials:** none.
- **Limitations:**
  - nflverse doesn't say when `spread_line` and `total_line` are captured, so treat them as a single late market line, not a verified closing line. There's no line history.
  - `spread_line` is positive when the **home team is favored**. Ingestion converts it to Model Room's convention (negative = home favored).
  - Release files (play-by-play, injuries) are GitHub release assets. This cloud workspace can't download them, but your PC can.
  - Play-by-play data before 2006 lacks some fields. Model Room uses the last 3 completed seasons plus the current one.

## hoopR / sportsdataverse (NBA)

- **What:** every NBA game's schedule, status, venue, neutral-site flag, final score and line scores, plus team box scores (field goals, free throws, rebounds, turnovers) from 2002 onward. Model Room uses 2015-16 onward.
- **URLs:**
  - `https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/schedules/parquet/nba_schedule_<season>.parquet`
  - `https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/team_box/parquet/team_box_<season>.parquet`
  - hoopR names a season by the year it ends (`2027` = 2026-27).
- **Cost:** free.
- **License:** the hoopR code is MIT. The data is scraped from ESPN's public endpoints, and ESPN's terms of use apply to it. That's fine for personal research. Before charging subscribers for projections built on it, get a licensed feed or written permission. (I'm not a lawyer; treat this as a flag, not advice.)
- **Update frequency:** hoopR's scraper runs daily. In practice the current-season files lag the games by under a day.
- **Credentials:** none.
- **Limitations:**
  - No betting lines.
  - No injury reports.
  - ESPN's box scores can be corrected after games.
  - The 2019-20 season includes the neutral-site bubble, and the 2020-21 season had limited crowds. The schedule's neutral-site flag covers the bubble games.

## NBA injuries

- **Official NBA injury report:** free PDFs published by the league several times a day on game days. There's no structured API; parsing the PDFs is brittle.
- **ESPN injuries endpoint:** unofficial and undocumented, and ESPN's terms apply.
- **Paid feeds** (Sportradar, SportsDataIO and others) cost a few hundred dollars a month or more, and require a key and a license agreement.
- **In Model Room:** the NBA injury module is built and tested. It takes a normalized file (`modeling/data/nba/injuries.csv`: date, team, player, status) and applies each player's estimated impact. Until a feed is chosen, NBA injury adjustments show "Not connected".

## Sportsbook lines

| Provider | Cost | Historical | Notes |
| --- | --- | --- | --- |
| [The Odds API](https://the-odds-api.com) | Free: 500 credits/month. Paid: $30, $59, $119 and $249 per month | Snapshots from 2020 (costs extra credits) | US books including DraftKings, FanDuel, BetMGM and Caesars. REST polling, API key. |
| nflverse `games.csv` | Free | Back to 1999 | NFL only, one line per game, capture time not documented |

- **NBA:** Model Room reads The Odds API when `ODDS_API_KEY` is set (`python -m modelroom nba odds`). Each call requests the spreads and totals markets for US books and takes the median line across books. Without a key, NBA market columns show "Not connected".
- **Backtesting against NBA closing lines** needs historical odds, which means The Odds API's historical endpoint on a paid plan. Until then, NBA validation measures error against actual results only.

## Credentials

| Variable | Needed for | Where to get it |
| --- | --- | --- |
| `ODDS_API_KEY` | NBA spreads and totals (optional for NFL) | the-odds-api.com, free sign-up |

No other credentials are needed.

## What this workspace could reach

The development environment that built the engines could read GitHub repositories but not GitHub release files or any sports or odds website. The NBA engine and its backtest ran on hoopR data, and the NFL schedule and market data came from `games.csv`. NFL play-by-play has to be downloaded on your PC (`python -m modelroom nfl ingest` does it).
