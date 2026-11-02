# NFL model: methodology

Model id `nfl-game`. Code in `modeling/modelroom/nfl/`. It is separate from the NBA engine and shares only generic utilities (ridge solver, metrics, ledger).

## Why play-by-play, not scores

An NFL team plays 17 games a season, so final scores are a small, noisy sample. Play-level expected points added (EPA) gives about 60 offensive plays a game, each valued by how it changed the expected score. That makes it a far more stable measure of team quality than points. Ratings are built in EPA per play, and a fitted regression converts them into points.

## Data

- **nflverse play-by-play:** EPA, success, win probability, down, distance, field position, passer.
- **nflverse `games.csv`:** schedule, results, rest days, projected and actual starting QBs, roof, and the published spread and total.

The ratings use the three seasons before a game plus the current season up to the day before it. Backtests run from 2021, so play-by-play starts in 2018.

## Plays used `[features.py]`

- **Included:** pass and run plays, including sacks and scrambles.
- **Excluded:** kneels, spikes, two-point tries, plays wiped out by penalty (`no_play`), and special teams.
- **Garbage time:** a play counts in full when the offense's pre-snap win probability is between 10% and 90%. Outside that range it counts at 25%. Late-game stats in decided games still exist, but they can't drag a rating far.

Per team per game, from those weighted plays:

| Measure | Definition |
| --- | --- |
| Offensive EPA/play | weighted mean EPA, offense |
| Defensive EPA/play | weighted mean EPA allowed |
| Pass EPA/dropback, rush EPA/carry | same, split by play type |
| Success rate | share of plays with EPA > 0 |
| Yards per play | yards gained / plays |
| 3rd-down conversion | 3rd-down plays gaining at least the distance needed / 3rd-down plays |
| Red-zone TD rate | drives reaching the opponent's 20 that score a touchdown / such drives (display only; small samples) |
| Turnover rate | interceptions and fumbles lost per play |

Only EPA enters the projection. The other measures are shown for context, because they are already captured inside EPA.

## Team ratings `[ratings.py]`

Each team-game gives one observation for that team's offense:

```
off_epa(team vs opp) = μ + off[team] + def[opp] + h × venue + noise
venue = +1 home, −1 away, 0 neutral
```

- **Fit:** solved by ridge regression toward 0 (league average). The weight of each team-game is
  ```
  weight = plays_weighted × 0.5^(games_ago / half_life) × season_carry^(seasons_ago)
  ```
  - `games_ago` counts the team's own games, so bye weeks don't age anything.
  - `season_carry` < 1 fades older seasons, allowing for roster turnover.
  - The ridge penalty keeps September ratings from reacting to one or two games.
- **Separate pass and rush ratings:** the same fit, run on pass plays and run plays separately. Shown for context.
- **Strength of schedule:** average current rating of opponents played this season.

## Quarterback adjustment `[qb.py]`

The ratings describe the offense with the QBs who actually played. When the projected starter is someone else, the projection adjusts:

```
qb_value   = shrunk EPA per dropback over the window
           = (Σ weighted EPA + k × replacement) / (Σ weight + k)
team_qb    = qb_value of the team's QBs, weighted by dropbacks × the same recency and season weights as the rating
qb_adjust  = dropback_share × (qb_value(starter) − team_qb)
```

- **Replacement level** is fitted from training data: the average EPA per dropback of QBs outside a team's top starter.
- **`k` (shrinkage)** is tuned.
- **`dropback_share`** is the team's share of plays that are dropbacks.
- **The starter** comes from nflverse's projected QB. If none is listed, the adjustment is 0 and flagged.

Other injuries are listed on the site but aren't used yet. A non-QB player value model needs participation data and its own validation.

A first draft compared the starter with only the team's last 4 games. That cancelled the adjustment out when a backup had already started recent games, even though the rating still mostly reflected the regular starter (for example, Baltimore in 2026 week 9). It was replaced before publication; both backtests are kept in `modeling/data/output/nfl/`.

## Points, margin, total and win probability `[project.py]`

- **Expected offensive EPA for a matchup:**
  ```
  exp_off(home) = μ + off[home] + def[away] + h + qb_adjust(home)
  exp_off(away) = μ + off[away] + def[home] − h + qb_adjust(away)
  ```
- **Points:** each team's points come from a regression fitted on training seasons, using only pre-game values:
  ```
  points = a + b × exp_off + c × rest_advantage + d × indoor_stadium
  ```
- **Derived outputs:**
  ```
  margin = home_points − away_points
  total  = home_points + away_points
  model_spread = −margin                   (negative = home favored)
  win_prob(home) = Φ(margin / σ)           σ = std. dev. of training-season margin errors
  ```
- **Rest advantage:** home rest days minus away rest days, capped at ±7, which captures byes and short weeks.
- **Indoor stadium:** that stadium's usual roof type from earlier games. Game-day weather isn't used, because nflverse records the weather after the game and that would leak results.
- **Travel:** not used. There are no reliable stadium coordinates in the data, and travel effects are small next to rest.

A normal margin distribution is a known simplification for the NFL, where key numbers like 3 and 7 cluster results. Calibration is checked; if it's poor, the next version will model margins directly.

## Validation `[backtest.py]`

Walk-forward by game date. Each game is projected with plays from earlier dates only.

| Window | Seasons |
| --- | --- |
| Rating history | 2018–2020 (never scored) |
| Tuning | 2021–2022: `half_life`, `season_carry`, ridge strength, QB `k` |
| Coefficients | `a`, `b`, `c`, `d`, `σ` fitted on tuning seasons |
| Test | 2023–2025, scored once with frozen settings |
| Live | 2026, stored in the ledger before kickoff |

**Reported:**
- Margin and total MAE, score error, bias
- Brier score and calibration
- By season, by team, and home vs away
- Baselines: home edge only, and the published market line

The market line's capture time isn't documented (see data-sources.md), so the market comparison measures accuracy, not a betting record. No claim of beating the market is made without line timing.
