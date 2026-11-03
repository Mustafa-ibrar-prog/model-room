# NBA player-prop model (nba-props 0.1.0, provisional)

Code: `modeling/modelroom/nba/props/`. Backtest report: `docs/models/results/nba-props-backtest-0.1.0.json`. Settings: `modeling/modelroom/nba/props/params.json`.

## What it is

The model gives its own probability for every threshold of seven markets: points, rebounds, assists, points + rebounds + assists, threes made, steals and blocks. It also gives the mean, median, standard deviation and 80% range.

**It is independent of the market.** Its inputs are hoopR box scores and the Model Room NBA game engine's projected pace and margin. No sportsbook or exchange price is an input. Exchange prices are only compared afterwards (`docs/markets.md`).

## How a projection is built

At a cutoff date, the model uses only games before it.

1. **Minutes.**
   - Recency-weighted minutes when the player plays (half-life 3 games), times how often he has played lately.
   - A rotation player who missed his team's last 2 games is treated as out. There is no NBA injury feed yet.
   - Team minutes are scaled to 240 plus the average overtime share.
   - Starters lose a little time in projected blowouts.
2. **Per-minute rates.**
   - 2-point makes, 3-point makes, free throws made, rebounds, assists, steals and blocks.
   - Recency-weighted (half-life 20 games), with earlier seasons counting 0.5.
   - Pulled toward the position group (G / F / C) average by 250 minutes of prior.
3. **Matchup and pace.**
   - The opponent's allowed per-minute rate to that position group, as a ratio to the league, pulled toward 1 (strength 0.5).
   - The game engine's projected pace over the team's usual pace (strength 1).
   - Teammates ruled out free up usage, which lifts scoring and assists (strength 1).
4. **Simulation.**
   - 10,000 draws live; 3,000 in the backtest.
   - Minutes vary from game to game (sd 7).
   - Each stat is Poisson given minutes.
   - A shared lognormal shooting-night shock (sd 0.35) moves 2s, 3s and free throws together. Rebounds, assists and steals/blocks have their own shocks.
   - Points = 2·2PM + 3·3PM + FTM, so points and threes stay consistent.
5. **Calibration.** Per market, probabilities are mapped through σ(a + b·logit p), fitted on the tuning seasons only.

**Reproducibility.** Each game day is simulated with a fixed seed (the date as YYYYMMDD) per game and team. Rerunning with the same data gives the same numbers.

**Sample size.** Each projection has a support level from the player's history in the model's window: ok at 15+ games and 300+ minutes, limited at 5+ games and 100+ minutes, insufficient below that. Limited and insufficient projections are labelled on the site and can never be a "strong" edge.

## No look-ahead in the backtest

- Every game day is projected from games before that day only. This covers player rates, defense-vs-position, position priors and the game engine's projections, which come from its own walk-forward.
- Settings are tuned on 2021-22. 2020-21 was shortened and mostly played without fans.
- Calibration is fit on 2020-21 and 2021-22.
- 2022-23 to 2025-26 is scored once with everything frozen.
- Grading uses only players who played and were projected for 18 or more minutes. Thresholds the model put below 2% or above 98% are excluded.

## Results (2022-23, 2023-24, 2024-25, 2025-26, never used for tuning)

All markets together: **2,395,644 thresholds**.
- Log loss **0.408** vs **0.415** for the baseline. The baseline is each player's smoothed hit rate over his last 20 games.
- Brier 0.131.
- Calibration error 0.7% after calibration (2.1% before).

| Market | Thresholds scored | Log loss: model | Log loss: recent hit rate | Calibration error | Mean error: model | Mean error: recent average |
|---|---|---|---|---|---|---|
| Points | 450,603 | 0.375 | 0.378 | 1.5% | 5.38 | 5.22 |
| Rebounds | 402,686 | 0.393 | 0.404 | 0.7% | 2.06 | 2.05 |
| Assists | 288,215 | 0.404 | 0.411 | 0.7% | 1.56 | 1.54 |
| Pts + reb + ast | 520,368 | 0.399 | 0.400 | 1.3% | 6.89 | 6.72 |
| Threes made | 349,190 | 0.432 | 0.441 | 0.4% | 1.04 | 1.02 |
| Steals | 214,682 | 0.482 | 0.501 | 0.6% | 0.78 | 0.79 |
| Blocks | 169,900 | 0.424 | 0.439 | 0.3% | 0.59 | 0.58 |

Every market is within 3% calibration error.

**Does each adjustment help?** Below is test-season log loss at 1,500 draws, with each adjustment and with it switched off:

| Adjustment | With | Without |
|---|---|---|
| matchup strength | 0.41781 | 0.41797 |
| pace strength | 0.41781 | 0.41853 |
| usage boost | 0.41781 | 0.42039 |

**By history behind the projection:** calibration error is 0.8% with enough history (2,351,049 lines), 3.1% for limited history (33,255), and 6.9% for thin history (11,340). This is why only "ok" projections can be graded a strong edge.

## Limits

- **Points and PRA barely beat the baseline.** Log loss is 0.375 vs 0.378 for points and 0.399 vs 0.400 for PRA. The projected *mean* is slightly worse than a plain recent average for points, PRA, assists, threes and blocks, and points run about 0.4 high on average. The gain is in the shape of the distribution, meaning the threshold probabilities, not in the centre. Rebounds, steals, blocks and threes are where the model adds the most over recent form.

- **No NBA injury feed.** "Out" is inferred from the last 2 games, so a late scratch is still projected. Such a player doesn't play, so his props would be voided.
- **No historical prop prices.** These numbers measure probability accuracy only. ROI and closing-line value need stored market snapshots, which build up from now on (`python -m modelroom markets ...`, off by default).
- **Provisional.** Version 0.1.0 is the first NBA prop version. Treat small edges as noise.
