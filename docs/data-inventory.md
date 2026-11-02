# Data-source inventory

Generated 2026-11-02 06:33 UTC by `python -m modelroom sources inventory`. Do not edit by hand.

Status: **collected** = refreshed by an ingest command; **optional** = used only if you set it up; **manual** = you enter it; **reference-only** = checked by hand, not collected (terms); **unavailable** = no permitted access.

| Source | Sport | Status | Official | API key | Historical coverage | Current season | Last successful update |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nflverse schedules and results (nfldata games.csv) | NFL | collected | no | none | 1999 to 2026, 7,396 final games | 2026: 120 final through 2026-11-01, 152 scheduled | 2026-11-02T06:30:46+00:00 |
| nflverse play-by-play | NFL | collected | no | none | 2023 to 2026 ingested (168,946 plays) | 2026: 120 games, through week 8 | 2026-11-02T06:30:51+00:00 |
| nflverse injury reports | NFL | collected | no | none | 2009 to the current season | 2026: through week 8 | 2026-11-02T06:30:53+00:00 |
| NFL.com | NFL | reference-only | yes | none | varies by page | n/a | never |
| hoopR NBA schedules (sportsdataverse, from ESPN) | NBA | collected | no | none | 2015-16 to 2026-27, 14,248 games with box scores | 2026-27: 88 final through 2026-10-31, 1112 scheduled through 2027-04-11 | 2026-11-02T06:30:57+00:00 |
| hoopR NBA team box scores | NBA | collected | no | none | 2015-16 to 2026-27, 14,248 games with box scores | 2026-27: 88 final through 2026-10-31, 1112 scheduled through 2027-04-11 | 2026-11-02T06:30:57+00:00 |
| hoopR NBA player box scores | NBA | collected | no | none | 2015-16 onward, 369,277 player-games | 2,405 player-games this season | 2026-11-02T06:30:57+00:00 |
| Land of Basketball results | NBA | collected | no | none | 1946-47 to the current season | 88 games cross-checked (2026-10-20 to 2026-10-31) | 2026-11-02T06:30:57+00:00 |
| StatsCrew NBA team season statistics | NBA | reference-only | no | none | 1946-47 onward | n/a | never |
| NBA.com / stats.nba.com / cdn.nba.com | NBA | reference-only | yes | none | 1946-47 onward | n/a | never |
| The Odds API | NBA, NFL | optional | no | optional | historical snapshots from 2020 on paid plans | n/a | never |
| Manual line entry (CSV) | NBA, NFL | manual | no | none | whatever is entered | n/a | never |
| Sportsbook websites (DraftKings, FanDuel, BetMGM, ...) | NBA, NFL | unavailable | no | none | none (current lines only) | n/a | never |
| SportsbookReviewsOnline odds archive | NBA, NFL | unavailable | no | none | formerly 2007 onward | n/a | never |
| Licensed official data (Sportradar, Genius Sports, SportsDataIO) | NBA, NFL | optional | yes | required | full | n/a | never |

## Details

### nflverse schedules and results (nfldata games.csv)

- **Data:** schedules, scores, spreads, totals, moneylines, rest, starting QBs, stadium, roof, weather
- **Access:** `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`
- **License / terms:** nflverse data, CC-BY 4.0 (credit nflverse)
- **Update frequency:** about every 5 minutes in season
- **Limitation:** spread_line is positive when the HOME team is favored; converted on ingest
- **Limitation:** capture time of spread_line/total_line is not documented; treated as a late line, not a verified close
- **Limitation:** one line per game; no sportsbook name and no line history

### nflverse play-by-play

- **Data:** play-by-play, EPA, success rate, win probability, passing, rushing, QB
- **Access:** `https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_<season>.parquet (or a local folder)`
- **License / terms:** nflverse data, CC-BY 4.0 (credit nflverse)
- **Update frequency:** nightly after game days; stat corrections settle by Thursday
- **Limitation:** GitHub release file: downloads on your PC; the cloud build environment cannot fetch it

### nflverse injury reports

- **Data:** injuries, practice participation, game status
- **Access:** `https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_<season>.parquet`
- **License / terms:** nflverse data, CC-BY 4.0
- **Update frequency:** during the season (nflverse does not publish an exact schedule)
- **Limitation:** mirrors the NFL's official injury reports; check freshness before games

### NFL.com

- **Data:** schedules, scores, standings, team stats, player stats, rosters, injuries
- **Access:** public web pages
- **License / terms:** NFL Terms: no robots/spiders collecting information 'for any commercial purpose'
- **Update frequency:** live
- **Limitation:** robots.txt allows most pages, but the Terms forbid automated collection for commercial use
- **Limitation:** used for manual verification only until the data is licensed

### hoopR NBA schedules (sportsdataverse, from ESPN)

- **Data:** schedules, scores, status, neutral site, venue, periods/OT
- **Access:** `https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/schedules/parquet/nba_schedule_<season>.parquet`
- **License / terms:** hoopR code MIT; data scraped from ESPN, ESPN terms apply
- **Update frequency:** daily
- **Limitation:** ESPN-derived, not official league records
- **Limitation:** season named by end year (2027 = 2026-27)

### hoopR NBA team box scores

- **Data:** team box scores, possession inputs, efficiency, pace
- **Access:** `https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/team_box/parquet/team_box_<season>.parquet`
- **License / terms:** hoopR code MIT; data scraped from ESPN, ESPN terms apply
- **Update frequency:** daily
- **Limitation:** 2017-18 file lacks team turnovers; player turnovers used (about one possession low per game)

### hoopR NBA player box scores

- **Data:** player box scores, minutes, inactive players with reason
- **Access:** `https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/player_box/parquet/player_box_<season>.parquet`
- **License / terms:** hoopR code MIT; data scraped from ESPN, ESPN terms apply
- **Update frequency:** daily
- **Limitation:** inactive reasons are free text

### Land of Basketball results

- **Data:** final scores, overtime
- **Access:** `https://www.landofbasketball.com/results/<YYYY>_<YYYY>_<mon>_scores.htm`
- **License / terms:** All rights reserved; used only to cross-check final scores, never republished
- **Update frequency:** daily
- **Limitation:** robots.txt: /box_scores and player stats pages are off limits; 20 s crawl delay honored
- **Limitation:** scores and team names only (no box-score stats)

### StatsCrew NBA team season statistics

- **Data:** team season totals, standings
- **Access:** `https://www.statscrew.com/basketball/l-NBA/y-<season start>`
- **License / terms:** site terms apply
- **Update frequency:** during the season
- **Limitation:** season-level totals only, not game level; robots.txt crawl delay 5 s

### NBA.com / stats.nba.com / cdn.nba.com

- **Data:** schedules, scores, standings, team stats, player stats, box scores, rosters, injury report
- **Access:** public web pages; the data CDN refuses direct downloads (Access Denied)
- **License / terms:** NBA Terms (updated 2026-07-13): NBA Statistics may not be used in connection with any gambling activity, commercial products, or comprehensive regularly updated databases without NBA consent
- **Update frequency:** live
- **Limitation:** robots.txt disallows /api/* and blocks AI crawlers
- **Limitation:** use is incompatible with a betting-analytics product without a license; manual verification only

### The Odds API

- **Data:** spreads, totals, moneylines, sportsbook, timestamp
- **Access:** `https://api.the-odds-api.com/v4/sports/<sport>/odds (ODDS_API_KEY)`
- **License / terms:** commercial API terms
- **Update frequency:** on request (poll)
- **Limitation:** needs a key: no public NBA line feed exists that sportsbook terms allow automated access to
- **Limitation:** free tier is 500 credits a month

### Manual line entry (CSV)

- **Data:** spreads, totals, moneylines, sportsbook, timestamp
- **Access:** data/manual/<league>_lines.csv (template in modeling/templates/lines_template.csv)
- **License / terms:** your own records
- **Update frequency:** whenever entered
- **Limitation:** validated on ingest: book, market, timestamp and line are required

### Sportsbook websites (DraftKings, FanDuel, BetMGM, ...)

- **Data:** spreads, totals, moneylines
- **Access:** n/a
- **License / terms:** sportsbook terms prohibit automated access; pages require location checks
- **Update frequency:** live
- **Limitation:** not collected

### SportsbookReviewsOnline odds archive

- **Data:** historical closing lines
- **Access:** archive URL now redirects to an advertising page (checked 2026-11-02)
- **License / terms:** n/a
- **Update frequency:** n/a
- **Limitation:** no longer published

### Licensed official data (Sportradar, Genius Sports, SportsDataIO)

- **Data:** official stats, injuries, odds
- **Access:** commercial contract
- **License / terms:** covers commercial and betting-adjacent use when contracted
- **Update frequency:** live
- **Limitation:** cost and terms by quote; evaluate before a paid launch

