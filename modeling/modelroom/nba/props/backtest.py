"""Walk-forward backtest for NBA player props.

Every game day is projected with games before that day only (player rates, minutes, defense vs position,
team pace) and the game engine's walk-forward projection for that game. Graded on players who played.
Tuned on 2020-21 and 2021-22; 2022-23 to 2025-26 is scored once. Calibration (per market) is fit on the
tuning seasons. Baseline: the player's smoothed hit rate over his last 20 games.

No historical prop prices: ROI and closing-line value come from stored exchange snapshots (Phase 5).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common.paths import ensure, output_dir
from modelroom.common.propeval import apply_calibration, fit_calibration, objective, summarize

from . import inputs as I
from . import model as M
from .config import MARKETS, MODEL_VERSION, TEST_SEASONS, TUNE_SEASONS, PropParams, PropSettings

OBJECTIVE_SEASONS = (2022,)  # settings are chosen on 2021-22 alone (2020-21 was a shortened, mostly fan-less season)

FEATURE_KEYS = ("minutes_half_life", "rate_half_life", "season_carry", "def_half_life", "rate_prior_minutes", "def_prior_minutes")
BASELINE_GAMES = 20
MIN_PROJECTED_MINUTES = 18.0  # roughly the players exchanges list


class Runner:
    def __init__(self, inp: I.Inputs):
        self.inp = inp
        self._ctx: dict = {}
        g = inp.games
        self.days = {s: sorted(g.loc[(g["season"] == s) & (g["status"] == "final"), "game_date"].astype(str).unique())
                     for s in sorted(g["season"].unique())}
        pg = inp.player_games
        played = pg[pg["played"]]
        cols = ["pts", "reb", "ast", "pra", "fg3m", "stl", "blk"]
        self.actual = {(gid, pid): dict(zip(cols, vals)) for gid, pid, *vals in played[["game_id", "player_id", *cols]].itertuples(index=False)}
        self.pg_dates = pd.to_datetime(pg["game_date"])
        self._base: dict = {}

    def ctx(self, day: str, season: int, s: PropSettings) -> M.Context:
        fkey = tuple(getattr(s, k) for k in FEATURE_KEYS)
        if self._ctx and next(iter(self._ctx))[2] != fkey:
            self._ctx.clear()
        key = (day, season, fkey)
        if key not in self._ctx:
            self._ctx[key] = M.build(self.inp.player_games, self.inp.pace, pd.Timestamp(day), season, s)
        return self._ctx[key]

    def scored(self, seasons, p: PropParams) -> tuple[pd.DataFrame, pd.DataFrame]:
        ts, ms = [], []
        g = self.inp.games
        for season in sorted(seasons):
            for day in self.days.get(season, []):
                day_games = g[(g["game_date"].astype(str) == day) & (g["status"] == "final")]
                ctx = self.ctx(day, season, p.settings)
                projs = M.project_games(ctx, day_games, p, seed=int(day.replace("-", "")))
                if day not in self._base:
                    self._base[day] = _baseline(self.inp.player_games, self.pg_dates, pd.Timestamp(day), season)
                base = self._base[day]
                t, m = score(projs, self.actual, base, season)
                ts.append(t)
                ms.append(m)
        return pd.concat(ts, ignore_index=True), pd.concat(ms, ignore_index=True)


def _baseline(pg, dates, cutoff, season) -> dict:
    h = pg[(dates < cutoff) & (pg["season"] >= season - 1) & pg["played"]]
    h = h.sort_values("game_date").groupby("player_id").tail(BASELINE_GAMES)
    stats = [m["stat"] for m in MARKETS.values()]
    return {pid: {s: d[s].to_numpy(float) for s in stats} for pid, d in h.groupby("player_id")}


def eligible(x: M.PlayerProjection) -> bool:
    return x.inputs.get("projected_minutes", 0) >= MIN_PROJECTED_MINUTES


def score(projs, actual, base, season) -> tuple[pd.DataFrame, pd.DataFrame]:
    trows, mrows = [], []
    for x in projs:
        k = (x.game_id, x.player_id)
        if not eligible(x) or k not in actual:
            continue
        a = actual[k]
        hist = base.get(x.player_id)
        support = x.support()[0]
        for mkey, m in MARKETS.items():
            stat = m["stat"]
            y = float(a[stat])
            hv = hist[stat] if hist is not None else None
            mrows.append({"market": mkey, "season": season, "proj": x.mean(stat), "actual": y,
                          "baseline": float(np.mean(hv)) if hv is not None and len(hv) else np.nan})
            for thr in m["ladder"]:
                p = x.prob(stat, thr)
                if p < 0.02 or p > 0.98:
                    continue
                bp = (float(np.sum(hv >= thr)) + 0.5) / (len(hv) + 1.0) if hv is not None and len(hv) else np.nan
                trows.append({"market": mkey, "season": season, "threshold": thr, "p": p, "baseline_p": bp, "y": float(y >= thr),
                              "player_id": x.player_id, "game_id": x.game_id, "support": support})
    return pd.DataFrame(trows), pd.DataFrame(mrows)


GRID = {
    "minutes_sd": [3.5, 5.0, 7.0],
    "scoring_sd": [0.15, 0.25, 0.35],
    "rebound_sd": [0.15, 0.25, 0.35],
    "assist_sd": [0.15, 0.25, 0.35],
    "stock_sd": [0.1, 0.25, 0.4],
    "matchup_strength": [0.0, 0.5, 1.0],
    "pace_strength": [0.0, 0.5, 1.0],
    "usage_boost": [0.0, 0.5, 1.0],
    "minutes_half_life": [3.0, 10.0],
    "rate_half_life": [10.0, 40.0],
    "rate_prior_minutes": [100.0, 600.0],
}


def tune(run: Runner, base: PropParams, log=print) -> tuple[PropParams, list[dict]]:
    p, history = base, []
    ckpt = ensure(output_dir("nba")) / "props_tuning_checkpoint.json"
    done: dict = json.loads(ckpt.read_text()) if ckpt.exists() else {}

    def evaluate(cand: PropParams) -> float:
        key = json.dumps(asdict(cand.settings), sort_keys=True)
        if key not in done:
            done[key] = objective(run.scored(OBJECTIVE_SEASONS, cand)[0])
            ckpt.write_text(json.dumps(done))
        return done[key]

    best = evaluate(p)
    log(f"start {best:.5f}")
    history.append({"settings": asdict(p.settings), "objective": round(best, 5)})
    for key, values in GRID.items():
        for v in values:
            if getattr(p.settings, key) == v:
                continue
            cand = replace(p, settings=replace(p.settings, **{key: v}))
            val = evaluate(cand)
            history.append({"change": {key: v}, "objective": round(val, 5)})
            log(f"  {key}={v}: {val:.5f}{'  *' if val < best - 1e-5 else ''}")
            if val < best - 1e-5:
                best, p = val, cand
    return p, history


def run(*, tune_sims: int = 800, log=print) -> dict:
    t0 = time.time()
    inp = I.load()
    runner = Runner(inp)
    p = PropParams(replace(PropSettings(), sims=tune_sims))
    p, history = tune(runner, p, log)
    final = replace(p, settings=replace(p.settings, sims=3000))
    tune_t, tune_m = runner.scored(TUNE_SEASONS, final)
    cal = fit_calibration(tune_t)
    test_raw, test_m = runner.scored(TEST_SEASONS, final)
    test_t = apply_calibration(test_raw, cal)
    ablation = {}
    q = replace(final, settings=replace(final.settings, sims=1500))
    ref = round(objective(runner.scored(TEST_SEASONS, q)[0]), 5)
    for key in ("matchup_strength", "pace_strength", "usage_boost"):
        if getattr(final.settings, key) == 0:
            continue
        tt, _ = runner.scored(TEST_SEASONS, replace(q, settings=replace(q.settings, **{key: 0.0})))
        ablation[key] = {"without": round(objective(tt), 5), "with": ref}
    report = {
        "model_id": "nba-props", "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tuning_seasons": list(TUNE_SEASONS), "test_seasons": list(TEST_SEASONS),
        "settings": asdict(final.settings), "calibration": cal,
        "tuning": {"objective": round(objective(tune_t), 5), "history": history},
        "test": summarize(test_t, test_m), "test_objective": round(objective(test_t), 5),
        "test_uncalibrated": {"objective": round(objective(test_raw), 5), "overall": summarize(test_raw, test_m).get("overall")},
        "ablation_test_log_loss": ablation,
        "notes": [
            "Each game day is projected with games before that day only; graded on players who played.",
            f"Players projected under {MIN_PROJECTED_MINUTES:.0f} minutes and thresholds below 2% or above 98% are not scored.",
            f"Baseline: share of the player's last {BASELINE_GAMES} games (this season and last) that cleared the threshold, smoothed.",
            "There is no NBA injury feed: a rotation player who missed his team's last two games is treated as out; otherwise players are assumed available.",
            "Each game day is simulated with a fixed seed (the date as YYYYMMDD) per game and team, so every number reproduces.",
            "No historical prop prices: ROI and closing-line value need stored market snapshots.",
        ],
        "runtime_s": round(time.time() - t0, 1),
    }
    out_p = replace(final, calibration=cal, settings=replace(final.settings, sims=10000),
                    provenance={"fitted_at": report["generated_at"], "tuning_seasons": list(TUNE_SEASONS),
                                "test_seasons": list(TEST_SEASONS), "status": "provisional: first NBA prop version"})
    out_p.save()
    (ensure(output_dir("nba")) / "props_backtest.json").write_text(json.dumps(report, indent=2, default=str))
    return report
