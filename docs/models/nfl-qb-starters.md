# NFL starting QB: projected starter (candidate, not active)

Code: `modeling/modelroom/nfl/starters.py`. Comparison: `modeling/modelroom/nfl/qb_compare.py`. Results: `docs/models/results/nfl-qb-starter-comparison.json`.

**Status:** validated against the old rule, **not active**. The live engines still use the schedule's QB field (`MODELROOM_NFL_QB_SOURCE` unset, meaning `listed`). Setting it to `projected` switches both engines once approved.

## The problem

Both NFL engines took the starting QB from the schedule file (nflverse `games.csv`). That field has two problems:

- **Coming games:** it holds the previous week's starter, so a starter returning from injury, a benching, or a new injury is missed.
- **Past games:** it holds the actual starter, known only afterwards. The existing backtests therefore had a small look-ahead advantage on QBs.

## The new rule (as of kickoff, pre-game information only)

1. **Candidates:** QBs on the team's weekly roster with status ACT or INA, minus anyone listed Out or Doubtful on that week's injury report. Game-day inactives are not used.
2. **Depth chart:** the highest-ranked candidate.
   - **2025 on:** the last ESPN snapshot before kickoff. These are timestamped, and live projections always use them.
   - **Through 2024:** only undated weekly charts exist. Where one disagrees with last week's starter and that starter is still a candidate, the previous starter is used. In 2018–24 the previous starter was right in 155 of 244 such disagreements.
3. **Fallbacks:** last week's starter, then recent passing volume.

## Results (2023–2025, held out; every setting frozen, only the QB differs)

| | Picks the actual starter | Game margin error | Total error | Win-prob Brier | Props log loss (same 497,616 lines) |
|---|---|---|---|---|---|
| Schedule field (after the fact, current backtest) | 94.9% | 10.206 | 10.353 | 0.2217 | 0.41804 |
| Previous starter (what coming games get today) | 84.9% | 10.296 | 10.335 | 0.2241 | — |
| **Projected starter (new)** | **92.2%** | **10.249** | 10.390 | **0.2226** | **0.41802** |

- **Projections that change:**
  - **Game engine:** 118 of 855 test games compared with the current backtest, and 124 compared with the previous-starter rule.
  - **Props:** 1,378 of 10,792 player-games (59,817 of 497,616 lines).
  - **Live now (week 9):** one team, ARI: Gardner Minshew instead of Jacoby Brissett (ESPN depth chart).
- **Against what live projections use today (previous starter):** the new rule is better on margin error, win probability and starter accuracy. It catches 132 of 258 actual starter changes.
- **Against the after-the-fact field:** the new rule is slightly behind on game margin (+0.04 pts) and Brier (+0.0009). That gap is the look-ahead the old backtest enjoyed, which live projections never had.
- **Props:** equal or slightly better.
  - Passing yards log loss 0.4891 vs 0.4912; completions 0.5224 vs 0.5264.
  - Calibration error 1.06% vs 1.07% overall.
  - Passing TDs and interceptions are slightly worse.
- **Lamar Jackson (BAL, week 9):** the ESPN depth chart moved Tyler Huntley to QB1 on Nov 2, with Jackson listed third. Both rules pick Huntley, so that pick stands on current information; it isn't the bug it first looked like.
