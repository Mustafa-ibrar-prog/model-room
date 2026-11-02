# NBA model: methodology

Model id `nba-game`. Code in `modeling/modelroom/nba/`. Every formula below maps to one function, named in brackets.

## Data

- **Games:** hoopR schedules. Regular season, play-in and playoff games are used; preseason and All-Star games are dropped. Each game carries its date and time, home and away teams, neutral-site flag, number of periods and status.
- **Team box scores:** hoopR team box, one row per team per game. Uses points, field-goal attempts, free-throw attempts, offensive rebounds and turnovers.
- **Market lines (optional):** spreads and totals from The Odds API. They are used only to compute edges; the model never sees them.
- **Injuries (optional):** players listed Out or Doubtful for a game.

Seasons are named by the year they end (2027 = 2026-27). Ratings start from the 2015-16 season, which is a burn-in year and is never scored.

## Box-score quantities `[features.py]`

For each team in each game:

```
possessions_team = FGA − OREB + TOV + 0.44 × FTA
possessions_game = mean(possessions_home, possessions_away)
minutes          = 48 + 5 × (periods − 4)
pace             = possessions_game × 48 / minutes          (possessions per 48 minutes)
efficiency       = 100 × points / possessions_game           (points per 100 possessions)
points_per_poss  = points / possessions_game
```

- **Rest days** = days since the team's previous game, capped at 4. The first game of a season counts as 4.
- **Back-to-back** = rest of 1 day.

## Team ratings `[ratings.py]`

Ratings are re-estimated every game day, using only games completed **before** that day.

Each team in each game produces one observation:

```
efficiency(team vs opp) = μ + off[team] + def[opp] + h × venue + noise
venue = +1 home, −1 away, 0 neutral
```

| Symbol | Meaning |
| --- | --- |
| `μ` | League-average points per 100 possessions |
| `off[t]` | Points per 100 the team scores above average against an average defense (opponent-adjusted offense) |
| `def[t]` | Points per 100 the team allows above average against an average offense. Negative is good. |
| `h` | Home edge per team per 100 possessions. The home-minus-away gap is `2h`. |

Displayed ratings:

```
Offensive rating = μ + off
Defensive rating = μ + def
Net rating       = off − def
```

**Estimation.** The unknowns are solved by weighted ridge regression **toward a prior**:

```
minimise  Σ_games w_i (y_i − ŷ_i)²
        + λ_r Σ_teams [(off_t − prior_off_t)² + (def_t − prior_def_t)²]
        + λ_h (h − prior_h)²
```

- **Recency weight:** `w_i = 0.5 ^ (days_ago_i / half_life)`. Recent games count more, but no single game can swing a rating, because the prior and every other game still count.
- **Prior (previous season):**
  ```
  prior_off_t = r × off_t(end of last season)
  prior_def_t = r × def_t(end of last season)
  ```
  `r` < 1 regresses last year toward average to allow for roster changes. `prior_h` is last season's fitted home edge.
- **λ (prior strength):** measured in "games of evidence". Early in the season the prior dominates; by midseason the current season does.
- **Solver:** the problem is linear with about 61 unknowns. It is solved exactly with the normal equations (`numpy.linalg.solve`). No randomness.

**Pace** uses the same method, one observation per game:

```
pace_game = μ_p + pace[home] + pace[away] + noise
```

It also uses recency weights and a prior from last season.

**Strength of schedule:** the average current net rating of the opponents a team has already played this season. Ratings are already opponent-adjusted; SOS is reported for context.

**Season vs recent performance (displayed, not used twice):**
- *Season:* unweighted, opponent-adjusted net rating for the current season.
- *Recent:* the plain point margin per 100 possessions over the last 10 games.

The projection uses only the recency-weighted ratings.

## Situational adjustments `[adjustments.py]`

Fitted once per training window by least squares on out-of-sample residuals (actual margin minus rating-only projected margin), using training seasons only:

```
residual_margin = β_b2b × (b2b_away − b2b_home) + β_rest × (min(rest_home,3) − min(rest_away,3)) + noise
```

The coefficients are learned from data, then stored in the model's parameter file with the seasons they were fitted on.

## Injury impact `[injuries.py]`

Player value comes from player box scores. A player's recent Game Score per minute (Hollinger's published formula), minus a replacement level, times his average minutes, gives his box-score production per game above a replacement:

```
value_p = (gamescore_per_min_p − replacement_per_min) × avg_minutes_p      (last 15 team games, rotation players)
```

- **Converting value to points:** a coefficient `k` is fitted from history. A player who normally plays but is missing from a game's box score counts as absent, and `k` comes from regressing residual margins on the absent value.
- **Adjustment:** for an upcoming game, each team's adjustment is `−k × Σ value of players listed Out` (Doubtful counts at 75%). The adjustment is split evenly between that team's points and its opponent's.
- **When there's no injury feed:** the adjustment is reported as *not available*, not as 0.

## Projection `[project.py]`

For home team H and away team A on date d, with ratings from before d:

```
pace        = μ_p + pace[H] + pace[A]
eff_home    = μ + off[H] + def[A] + h × venue
eff_away    = μ + off[A] + def[H] − h × venue
margin_raw  = (eff_home − eff_away) × pace / 100
situational = β_b2b × (b2b_A − b2b_H) + β_rest × (rest_H' − rest_A') + injury_adj
margin      = margin_raw + situational
total       = (eff_home + eff_away) × pace / 100 + total_adj
home_score  = (total + margin) / 2
away_score  = (total − margin) / 2
win_prob    = Φ(margin / σ)              σ = std. dev. of out-of-sample margin errors in training
model_spread = −margin                   (Model Room convention: negative = home favored)
model_total  = total
spread_edge  = market_spread − model_spread    (positive = value on the home side)
total_edge   = model_total − market_total      (positive = over)
```

`Φ` is the standard normal CDF.

## Fitting and validation `[backtest.py]`

Chronological walk-forward. No game's projection uses anything from on or after its own date.

1. **Burn-in (2015-16):** builds the first priors. Never scored.
2. **Tuning (2016-17 to 2021-22):** a grid search over `half_life`, `λ_r`, `r` and the pace prior strength. The setting with the lowest margin mean absolute error (MAE) is chosen. `β`, `k` and `σ` are fitted on these seasons.
3. **Test (2022-23 to 2025-26):** frozen parameters, scored once.
4. **Live (2026-27):** projections are logged before tip-off to the prediction ledger.

**Reported:**
- MAE of margin and total
- Root mean squared error (RMSE)
- Bias
- Brier score and log loss of win probability
- Calibration table: predicted vs actual win rate in 10% bins
- Comparison against two baselines:
  - **Home-court only:** home team by the league home edge; total = league average.
  - **Season-to-date margin:** each team's average point margin so far, adjusted for home court.
- **Market comparison:** model vs closing spreads and totals, whenever historical lines are available. Not run yet for the NBA (see data-sources.md).

## Reproducibility

- **Every projection records** the model version, a hash of the parameter file, and a hash of the input rows it was computed from (the games before the cutoff).
- **Same inputs, same output:** re-running with the same inputs and version gives identical numbers. Tests check this.
- **The prediction ledger is append-only:**
  - It accepts a record only before the game starts.
  - Each record includes the previous record's hash, so any edit breaks the chain.
  - `python -m modelroom ledger verify` checks it.
