# NFL position-specific volume allocation research (Nov 2026)

Research only. Nothing here changes NFL props 0.1.1, its parameters, the NBA models or the shadow experiments.

Question: why does 0.1.1 split targets and carries among RBs, WRs and TEs incorrectly (lead backs and TE1s short,
third backs and third TEs over), and which fixes hold up out of sample?

## Files

- `collect.py <season>`: every skill candidate 0.1.1 considers per team-game (incl. players ruled Out), with the inputs
  to its share and what happened. Reproduces `model.project_team` share arithmetic for 0.1.1 settings without
  simulation (check vs the engine's own 2023 projections: correlation 0.997 targets / 0.999 carries, totals within 0.3%).
- `collect_fillin.py 0.25 <season>`: the same share inputs with fill-in games down-weighted (existing feature setting).
- `hist_feats.py`: last-3 / season-to-date shares known before each game.
- `diag.py` → `diag.json`: ghost volume, team totals, flatness, recency, depth diagnostics.
- `experiment.py [configs]` → `experiment.json`, `data/test_rows.pkl`: walk-forward (train 2021..S-1, test S = 2023, 2024,
  2025) of availability (AV), fill-in history (FI), RB carry recency (RC), within-position concentration (CN, CNsel =
  RB carries + TE targets only) and depth-chart role (DP). Market metrics: P(over the median-of-last-10 line) under a
  normal approximation scaled by the volume change, calibrated per market on training seasons ("refit") or with the
  0.1.1-equivalent calibration kept ("keepcal").
- `summarize.py` → `slices.csv`, `markets.csv`, `summary3.txt`: bias / MAE by position, role and season.
- `by_group_markets.py` → `by_group_markets.json`: market metrics split by position for CNsel vs 0.1.1.
- `tt_sens.py` → `tt_sens.json`: team RB-concentration tendency and sensitivity to the exponent.

`data/` (git-ignored) holds the collected rows; rerun `collect.py` for 2021-2025 to rebuild.
