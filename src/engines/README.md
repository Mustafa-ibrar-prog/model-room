# Modeling engines

Engines turn inputs into projections. They are kept apart from the UI on purpose:

- No imports from `src/app`, `src/components`, React or Next.js.
- No knowledge of plans or tiers. Gating happens in `src/server/data`.
- Deterministic for a given input and `asOf` timestamp, so results can be backtested.

## Status

| Engine | Status |
| --- | --- |
| NFL (`nfl/`) | Interface only. Throws `EngineNotImplementedError`. |
| NBA (`nba/`) | Interface only. Throws `EngineNotImplementedError`. |

## Build order for each engine

1. Ingest and store schedules, final scores and closing lines (Supabase tables).
2. Team ratings from historical results (offense, defense, pace, home field).
3. Injury and availability adjustments, with player value estimates.
4. Game projection: spread, total and team scores from ratings + adjustments.
5. Backtest against closing lines across past seasons. Publish error metrics.
6. Only after validation: a live provider in `src/server/providers` that reads stored engine output.

Engines should run as scheduled jobs (Vercel Cron, Supabase Edge Functions or a
separate worker) that write projections to the database. Pages never call an
engine directly.
