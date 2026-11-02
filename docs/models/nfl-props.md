# NFL player-prop model (nfl-props 0.1.0, provisional)

Code: `modeling/modelroom/nfl/props/`. Backtest report: `docs/models/results/nfl-props-backtest-0.1.0.json`.

## What it is

The model produces its own probability for every threshold of every market a player has:
- QB: passing yards, attempts, completions, passing TDs, interceptions, rushing
- RB / WR / TE: receiving yards, receptions, longest reception, rushing yards and attempts, rush + rec yards
- Everyone: anytime TD, fantasy points (ESPN PPR and Sleeper PPR)

**It is independent of the market.** Its inputs are nflverse play-by-play, snap counts, rosters, injury reports, FTN charting and participation data, plus the Model Room game engine's projected score. No sportsbook or exchange price is an input. Exchange prices are only compared afterwards (`docs/markets.md`).

## How a projection is built

For each team in a game:

1. **Team volume.** Pass attempts and carries come from the team's recent per-game rates, what the opponent usually faces, and the game engine's projected margin and total. This is a linear model fit on 2019–22.
2. **Usage.**
   - Each player's target share and carry share are recency-weighted over his games, which halve in weight every ~12 games, with earlier seasons counting half.
   - Shares are shrunk toward his position's typical share.
   - They're nudged by his recent snap share against his longer-run snap share.
   - They're nudged by how much this defense funnels targets to his position.
3. **Availability.** Players listed Out or Doubtful on that week's injury report are removed. Players not on the team's active or inactive roster for the week are removed. The removed players' shares are spread over the rest of the team.
4. **Efficiency.** Each rate is shrunk toward the position average:
   - catch rate
   - yards per catch and per carry
   - TD rates
   - QB completion %, yards per completion, INT and TD rates

   Each is then multiplied by the opponent's allowed ratio for that position group. On top of that:
   - a receiver's man/zone split is weighed against the defense's man-coverage rate
   - the QB's blitz split is weighed against the defense's blitz rate
5. **Simulation.** Every player is simulated many times (10,000 live, 4,000 in the backtest):
   - Team volume varies from game to game.
   - Shares vary with a beta distribution.
   - Each catch or carry gains yards drawn from the league's real distribution for that position group, scaled by the player's factor.
   - A shared "good or bad day" multiplier is applied to the player's yards.

   One simulation set gives the mean, median, standard deviation, 80% range and every threshold probability, all consistent with each other.
6. **Calibration.** Per market type, probabilities are mapped through σ(a + b·logit p), fitted on the tuning seasons only.

**Reproducibility.** Each team-game is simulated from its own random stream seeded by (season × 100 + week, game, team). The seed is stored with every published projection and ledger record. Rerunning with the same data and seed gives the same numbers.

**Sample size.** Each market carries a support level from the player's unweighted history in the model's window:

| Support | Receiving | Rushing | QB passing | Games |
|---|---|---|---|---|
| ok | 40+ targets | 50+ carries | 150+ attempts | and 6+ games |
| limited | 15+ targets | 20+ carries | 60+ attempts | and 3+ games |
| insufficient | below that | | | |

The site labels limited and insufficient projections. They can never be a "strong" edge.

## No look-ahead in the backtest

- Every week is projected with games **before that week's first game** only. This covers player rates, defense rates, league yardage distributions, position priors and the game engine's projections.
- Coverage (man/zone) for the season being projected isn't published while it's played, so the model uses earlier seasons only, live and in the backtest.
- Injury reports and weekly rosters are the pre-game versions. Game-day inactives aren't used to remove players.
- The team-volume model is fit on 2019–22.
- Settings are tuned on 2021–22, and calibration is fit on 2021–22.
- 2023–25 is scored once with everything frozen.
- Grading uses only players who played, because exchanges void or fair-price props on players who don't take a snap.

## Results (2023–25, never used for tuning)

All markets together: **502,813 thresholds**, log loss **0.418** vs **0.446** for the baseline (each player's smoothed hit rate over his last 16 games), Brier 0.135 vs 0.144. Calibration error 1.1% after calibration (4.1% before; the raw simulation slightly under-predicted overs).

| Market | Thresholds scored | Log loss: model | Log loss: recent hit rate | Calibration error | Mean error: model | Mean error: recent average |
|---|---|---|---|---|---|---|
| Passing yards | 15,030 | 0.491 | 0.527 | 4.1% | 59.30 | 68.23 |
| Pass attempts | 8,188 | 0.502 | 0.549 | 2.5% | 6.78 | 8.14 |
| Completions | 13,350 | 0.526 | 0.577 | 3.4% | 4.72 | 5.65 |
| Passing TDs | 5,010 | 0.547 | 0.584 | 3.6% | 0.91 | 0.93 |
| Interceptions | 3,340 | 0.562 | 0.602 | 1.8% | 0.70 | 0.70 |
| Rushing yards | 48,132 | 0.363 | 0.386 | 1.2% | 10.19 | 10.62 |
| Rush attempts | 17,947 | 0.332 | 0.363 | 1.2% | 3.31 | 3.49 |
| Receiving yards | 94,064 | 0.406 | 0.429 | 1.2% | 21.14 | 21.81 |
| Receptions | 83,140 | 0.376 | 0.403 | 1.0% | 1.57 | 1.64 |
| Rush + rec yards | 50,155 | 0.385 | 0.410 | 0.7% | 25.74 | 26.75 |
| Anytime TD | 19,175 | 0.394 | 0.418 | 1.3% | 0.41 | 0.41 |
| Longest reception | 53,429 | 0.485 | 0.510 | 2.0% | 9.09 | 9.62 |
| Fantasy points | 91,853 | 0.453 | 0.483 | 1.4% | 5.50 | 5.74 |

Lower is better everywhere. "Calibration error" is the average gap between predicted and actual hit rates across probability bins (ECE). The model beats the baseline in every market. **Passing yards (4.1%), passing TDs (3.6%) and completions (3.4%) are above the 3% calibration bar**, so those markets can show a lean but never a strong edge.

By history behind the projection: ok 452,765 thresholds, calibration error 1.0%; limited 32,543, 2.2%; insufficient 17,505, 3.3%. Thin history is measurably less reliable, which is why it blocks a strong edge.

**What the matchup inputs add (test seasons, log loss without → with, before calibration):**
- Opponent allowed rates by position: 0.4554 → 0.4551 (small help; tuning chose half strength)
- Recent snap-share trend: 0.4559 → 0.4551 (helps)
- Receiver man/zone split × defense man rate: 0.4551 → 0.4551 (no measurable effect)
- QB blitz split × defense blitz rate: 0.4551 → 0.4551 (no measurable effect)
- Pressure (QB hits) → completion %: switched off by tuning (no effect on 2021–22).

Coverage and blitz stay in the model as computed and shown, but they don't move accuracy. Week-to-week splits that small are mostly noise after shrinkage. They aren't switched off based on the test seasons, because that would be tuning on the test set.

Settings chosen on 2021–22: {"half_life_games": 12.0, "season_carry": 0.5, "def_half_life_games": 10.0, "share_prior_games": 1.0, "rate_prior": 40.0, "td_prior": 120.0, "def_prior_games": 6.0, "target_dispersion": 15.0, "carry_dispersion": 3.0, "efficiency_sd": 0.3, "matchup_strength": 0.5, "coverage_strength": 1.0, "blitz_strength": 1.0, "pressure_strength": 0.0, "snap_trend_strength": 1.0}.


## Limits

- There are no historical prop prices in the free data. The backtest therefore measures probability accuracy (log loss, Brier score, calibration), not ROI or closing-line value. Those come from stored exchange snapshots as they accumulate, which is Phase 5.
- Fumbles aren't simulated. The model's fantasy points are slightly high on average, by about 0.1 point per player.
- Players with no history (rookies before their first games, new signings) get the position prior and an "insufficient" label.
- Correlation between teammates isn't modeled. It matters for parlays, not single props.
