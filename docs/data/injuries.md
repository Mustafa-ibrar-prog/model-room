# Injury data (test site)

Everything here runs on the **test site only**. Production is unchanged.

## Sources

| Source | What it gives | Kind | Cadence | Cost | Licensing |
|---|---|---|---|---|---|
| Official NBA injury report (`ak-static.cms.nba.com/referee/injury/…pdf`) | Out / Doubtful / Questionable / Probable / Available for each game, "NOT YET SUBMITTED" per team | **official** | Republished about every 15 min on game days | Free | Published by the NBA for the public; the NBA's terms govern reuse. Fine for testing. Get permission before production use. |
| ESPN site API (`site.api.espn.com/apis/site/v2/sports/…`): team rosters (injury entries, experience), league injury feed (comments, return dates), NFL depth charts, NBA game rosters (starters once posted) | Injury status and news for both leagues, depth charts, starters | **report** | Updated as news breaks, usually minutes | Free, no key | **Undocumented, unlicensed API.** ESPN's terms of use limit commercial use of ESPN content. Test site only. **Do not use in production without written permission from ESPN.** |
| nflverse injuries (`nflverse-data` releases) | NFL official Wed–Sat designations and practice participation | official copy | Lags by hours to a day | Free (CC-BY) | Allowed with attribution |

Not available from free sources:
- NFL official gameday inactives (about 90 min before kickoff). The pregame refresh uses the newest Out designations and roster moves.
- Confirmed NBA starters before ESPN posts the game's rosters (around tip-off). Until then starters are the model's estimate and are labeled that way.

Possible replacements later, each a new adapter in `modeling/modelroom/injuries/` with the same normalized row (`schema.py`):
- BALLDONTLIE: injuries $9.99/mo per sport, lineups $39.99/mo.
- SportsDataIO or Sportradar: official feeds, B2B contract.

## How the rows are combined (`injuries/merge.py`)

1. **Identity.** ESPN athlete ids are the NBA box-score ids. NFL ids are mapped to gsis ids via nflverse's `espn_id`. Official NBA rows are matched by name within the team.
2. **Stale rows are shown but never used as current.** A row is stale when it is:
   - a game designation set before the team's previous game;
   - "out" reported before the player's most recent appearance;
   - an official NBA row for a past game date.
3. **Precedence.**
   - NBA: the official report for the team's next game wins. A team that submitted its report and didn't list a player means that player is available.
   - NFL: the newest current row wins.
4. **Conflicts** between current rows are kept on the row and shown on the site.
5. **Missing data is never "healthy".** With no current row, the engine's own availability rule applies, and the player is flagged as unconfirmed. "NOT YET SUBMITTED" teams are flagged too.
6. **Late scratch:** a player newly Out or Doubtful within 3 hours of his game, compared with the previous refresh.

**Snapshots.** Every fetch appends to `preview-ledger/injury_snapshots_<lg>.jsonl`:
- the sources' status on every fetch;
- the full table only when it changed.

Prediction snapshots fold the injury picture into their inputs hash. A change therefore writes a **new** ledger record, and earlier records are never touched.

## How the engines use it

| Engine | Version on the test site | Injury use | Rollback |
|---|---|---|---|
| NFL props | 0.1.1 (0.1.0 recorded alongside as a shadow) | Availability and starters as below; inexperienced-QB passing factor | `MODELROOM_NFL_PROPS_VERSION: "0.1.0"` |
| NBA props | 0.2.1 (0.2.0 recorded alongside as a shadow) | Availability, returning players, restrictions, confirmed starters as below | `MODELROOM_NBA_PROPS_VERSION: "0.2.0"` |
| NBA game (1.1.0) | unchanged | The fitted injury adjustment is switched on with the feed | `MODELROOM_NBA_INJURY_FEED: "off"` |
| NFL game (1.0.1) | unchanged | The QB adjustment uses the projected starter (step 1 below) | Remove the injury steps from `preview.yml` |

### NFL (props 0.1.1; the game engine is unchanged)

1. **Starting QB.** The starter is the first available QB on ESPN's current depth chart, after removing Out / Doubtful players. The depth chart is the same source nflverse snapshots, just fresher. Current active-roster QBs from ESPN are added as candidates.
   - Ravens test case, 2026-11-04: Lamar Jackson (Out), Tyler Huntley (Out, season-ending), Joe Fagnano QB1, so **Fagnano starts**.
   - The game engine's QB adjustment then values him from his own dropbacks, shrunk to replacement level.
2. **Inexperienced QB (props).** When the starter has fewer than 150 career attempts, his passing yards and his receivers' receiving yards are scaled by **0.931**.
   - Measured on QB passing yards, 2,762 QB-games: in 2021–22 such QBs reached 0.914 of their projection against 0.982 for veterans, a relative 0.931. Held out on 2023–25: 0.946 against 1.016, also a relative 0.931.
   - QBs with 150–500 attempts were not consistent across those periods and are not adjusted.
3. **Uncertainty.** Game margin and total errors were *not* wider with an inexperienced starter: the ratio was about 1.0 in both 2016–21 and 2022–25. So the game ranges are not widened.
4. **Designations.** Out and Doubtful players are removed, and their share goes to teammates by the 0.1.0 rule.

### NBA (props 0.2.1)

1. **Out / Doubtful from the feed** removes a player whatever his recent games. The freed usage is 100% for Out and 75% for Doubtful, the same weight the NBA game engine uses.
2. **Questionable / Probable / Available** (or not listed on a submitted official report) keeps a player in, even after missed games.
3. **Returning players:** the 1st, 2nd and 3rd games after missing 3+.
   - Minutes are scaled ×0.743 / 0.878 / 0.949, with the minutes spread ×1.31 / 1.21 / 1.18.
   - Measured on 2016–22 box scores; held out on 2023+: 0.740 / 0.848 / 0.937.
   - Source: `python -m modelroom.nba.props.returns`.
4. **Minutes restriction** in a report: capped at the stated number. With no number, returning-player minutes apply.
5. **Confirmed starters** (when ESPN posts them) set the starter flag.
6. **Teammates:** minutes are refilled to the team total, and freed usage is a share of one team total, so overlapping absences are never double counted.
7. **NBA game engine 1.1.0:** its fitted injury adjustment (Out 100%, Doubtful 75% of a player's Game Score value, then × k) is now switched on with the feed. Backtest with known absences, 2023–26: margin MAE 10.97 → 10.94, Brier 0.2142 → 0.2133.

## Refresh schedule

Slots are planned by `modeling/modelroom/refresh_plan.py`:
- 7:00 AM, 12:00 PM and 4:00 PM PT;
- NFL kickoff − 90 min;
- every game − 30 min.

**Triggers.** The primary trigger is Supabase pg_cron, every 5 minutes (`supabase/migrations/20261104000100_refresh_scheduler.sql`). GitHub's schedule every 10 minutes is the backup.

**Logging and duplicates.**
- Every run is logged per slot in `preview-ledger/refresh_log.jsonl` (success / failed, trigger).
- Failed slots are retried while their window is open.
- A run that was queued behind another re-checks the log, so it never repeats a slot.
- Missed slots are reported on the site.

**Sportsbook odds** are fetched only at the 7 AM and 12 PM refreshes, to stay within the free Odds API allowance.

### Supabase setup (owner)

1. Create a GitHub **fine-grained** token:
   - **Repository access:** only `Mustafa-ibrar-prog/model-room`.
   - **Permissions:** Actions, Read and write. Nothing else.
2. In the Supabase SQL editor for the **test site** project, run:
   `select vault.create_secret('<token>', 'model_room_github_dispatch', 'Model Room: dispatch the Preview workflow');`
   The token stays in Vault only: never in a table, this repo, GitHub secrets or the frontend.
3. The migration is applied by the "Supabase (test site)" workflow, which also switches the scheduler on for that database only.
4. Check health in the SQL editor with `select * from scheduler.health;`.
