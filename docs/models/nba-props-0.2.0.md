# NBA props 0.2.0 (test site only)

Status: active on the hosted test site since 2026-11-03. Production and every other run use 0.1.0.

| | 0.1.0 (default, rollback) | 0.2.0 (test site) |
| --- | --- | --- |
| Parameters | `modeling/modelroom/nba/props/params.json` | `modeling/modelroom/nba/props/params_0.2.0.json` |
| Backtest | `docs/models/results/nba-props-backtest-0.1.0.json` | `docs/models/results/nba-props-backtest-0.2.0.json` |
| Selected by | nothing set | `MODELROOM_NBA_PROPS_VERSION=0.2.0` (`.github/workflows/preview.yml`) |

Changes: per-minute rates shrink toward players in the same role (position x minutes band) instead of the
position average; missing team minutes go to players with room below their recent high instead of scaling
everyone up; the usage boost from an absent teammate fades as the absence ages and is half as strong;
wider game-to-game minutes noise. Comparison with 0.1.0 on the same rows: `nba-props-candidate-0.2.0.json`.

Versioning: the board shows `model.version` = 0.2.0 and every ledger record carries `model_version`. The
ledger is append-only and hash-chained, so 0.1.0 predictions recorded before the switch are unchanged.

Monitoring: `python -m modelroom nba props-monitor` (run on every test-site refresh) grades the last
pre-game prediction per player-game for each version against final box scores:
`modeling/data/published/props_monitor_nba.json` on the `preview` branch. It reports minutes (starters and
bench), points / PRA bias and error by role and by teammate-out, and Over / Under calibration per market.

Rollback: remove the `MODELROOM_NBA_PROPS_VERSION` line from `.github/workflows/preview.yml` (or set it to
"0.1.0") and push to main. The next refresh republishes 0.1.0; nothing else changes.
