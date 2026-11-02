"""Walk-forward backtest for NFL player props.

Each week is projected with games before that week only. Graded on players who took part (props on
players who don't play are voided by the exchanges). Every market threshold is scored as a probability:
Brier score, log loss and calibration, against a baseline (how often the player cleared the threshold in
his recent games). Mean projections are compared with the player's recent average.

Tuning uses 2021-22 only; 2023-25 is scored once with the chosen settings.

There are no historical prop prices in the free data, so this backtest cannot measure ROI or closing-line
value. Those come from the stored market snapshots (modelroom.markets) as they accumulate.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common.metrics import calibration_table, probability_summary
from modelroom.common.paths import ensure, output_dir

from . import features as F
from . import inputs as I
from . import model as M
from .config import FIT_SEASONS, MARKETS, MODEL_VERSION, TEST_SEASONS, TUNE_SEASONS, PropParams, PropSettings, VolumeModel

FEATURE_KEYS = ("half_life_games", "season_carry", "def_half_life_games", "share_prior_games", "rate_prior", "td_prior", "def_prior_games")
BASELINE_GAMES = 16


def _weeks(games: pd.DataFrame, seasons) -> list[tuple[int, int, pd.DataFrame]]:
    g = games[games["season"].isin(seasons) & (games["status"] == "final")]
    return [(int(s), int(w), d) for (s, w), d in g.groupby(["season", "week"], sort=True)]


class Runner:
    """Caches feature contexts by cutoff + feature settings, so tuning simulation settings is cheap."""

    def __init__(self, inp: I.Inputs):
        self.inp = inp
        self._ctx: dict = {}

    def ctx(self, cutoff, season, s: PropSettings) -> F.Context:
        key = (cutoff, season, tuple(getattr(s, k) for k in FEATURE_KEYS))
        if key not in self._ctx:
            self._ctx[key] = F.build(self.inp.player_games, self.inp.passes, self.inp.rushes, cutoff, season, s)
        return self._ctx[key]

    def volume_rows(self, seasons, s: PropSettings) -> pd.DataFrame:
        pg = self.inp.player_games
        actual = pg.drop_duplicates(["game_id", "team"]).set_index(["game_id", "team"])[["team_pass_att", "team_carries"]]
        rows = []
        for season, week, g in _weeks(self.inp.games, seasons):
            ctx = self.ctx(pd.Timestamp(g["game_date"].min()), season, s)
            T = ctx.teams
            for _, x in g.iterrows():
                m = x["proj_home_score"] - x["proj_away_score"]
                tot = x["proj_home_score"] + x["proj_away_score"]
                for team, opp, mm in ((x["home_team"], x["away_team"], m), (x["away_team"], x["home_team"], -m)):
                    if (x["game_id"], team) not in actual.index or team not in T.index:
                        continue
                    a = actual.loc[(x["game_id"], team)]
                    rows.append({"pa_base": T.at[team, "pa_base"], "pa_faced": T["pa_faced"].get(opp, 0.0),
                                 "ru_base": T.at[team, "ru_base"], "ru_faced": T["ru_faced"].get(opp, 0.0),
                                 "margin": mm, "total": tot, "pa": a["team_pass_att"], "ru": a["team_carries"]})
        return pd.DataFrame(rows)

    def fit_volume(self, seasons, s: PropSettings) -> VolumeModel:
        d = self.volume_rows(seasons, s)
        out = {}
        for k, base, faced in (("pass", "pa_base", "pa_faced"), ("rush", "ru_base", "ru_faced")):
            X = np.column_stack([np.ones(len(d)), d[base], d[faced], d["margin"], d["total"]])
            y = d["pa" if k == "pass" else "ru"].to_numpy(float)
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            out[k] = (tuple(round(float(c), 4) for c in coef), round(float(np.std(y - X @ coef)), 3))
        return VolumeModel(out["pass"][0], out["rush"][0], out["pass"][1], out["rush"][1])

    def walk(self, seasons, p: PropParams) -> pd.DataFrame:
        """One row per projected player-game that was actually played, with simulated distributions."""
        pg = self.inp.player_games
        act = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
        act = act.drop_duplicates(["game_id", "player_id"]).set_index(["game_id", "player_id"])
        recs = []
        for season, week, g in _weeks(self.inp.games, seasons):
            cutoff = pd.Timestamp(g["game_date"].min())
            ctx = self.ctx(cutoff, season, p.settings)
            ro, inj = I.week_slices(self.inp, season, week)
            projs = M.project_games(ctx, g, ro, inj, p, seed=season * 100 + week)
            base = _baseline_history(pg, cutoff, season)
            for x in projs:
                k = (x.game_id, x.player_id)
                if k not in act.index:
                    continue
                a = act.loc[k]
                recs.append({"season": season, "week": week, "game_id": x.game_id, "player_id": x.player_id, "name": x.name,
                             "group": x.group, "team": x.team, "proj": x, "actual": a, "base": base.get(x.player_id)})
        return recs


def _baseline_history(pg: pd.DataFrame, cutoff, season) -> dict:
    h = pg[(pd.to_datetime(pg["game_date"]) < cutoff) & (pg["season"] >= season - 1)]
    h = h[(h["offense_snaps"].fillna(0) > 0) | (h[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
    h = h.assign(rush_rec_yds=h["rush_yds"] + h["rec_yds"], td_any=h["rush_td"] + h["rec_td"])
    h = h.sort_values("game_date").groupby("player_id").tail(BASELINE_GAMES)
    return {pid: d for pid, d in h.groupby("player_id")}


def eligible(x: M.PlayerProjection) -> bool:
    """Roughly the players an exchange lists: the starting QB and skill players with a real role."""
    if x.group == "QB":
        return x.mean("pass_att") >= 15
    return x.mean("targets") >= 2.5 or x.mean("carries") >= 6


def score(recs: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Threshold rows (prob, baseline prob, outcome) and mean rows (projection vs actual)."""
    trows, mrows = [], []
    for r in recs:
        x: M.PlayerProjection = r["proj"]
        if not eligible(x):
            continue
        a = r["actual"]
        actual = {"rush_rec_yds": a["rush_yds"] + a["rec_yds"], "td_any": a["rush_td"] + a["rec_td"]}
        hist = r["base"]
        for mkey, m in MARKETS.items():
            if x.group not in m["positions"]:
                continue
            stat = m["stat"]
            y = float(actual.get(stat, a.get(stat, np.nan)))
            if np.isnan(y):
                continue
            hv = hist[stat].to_numpy(float) if hist is not None and stat in hist else None
            mrows.append({"market": mkey, "group": x.group, "season": r["season"], "proj": x.mean(stat), "actual": y,
                          "baseline": float(np.mean(hv)) if hv is not None and len(hv) else np.nan})
            for k in m["ladder"]:
                p = x.prob(stat, k)
                if p < 0.02 or p > 0.98:
                    continue
                if hv is not None and len(hv):
                    hits = float(np.sum(np.asarray(hv) >= k))
                    bp = (hits + 0.5) / (len(hv) + 1.0)
                else:
                    bp = np.nan
                trows.append({"market": mkey, "group": x.group, "season": r["season"], "threshold": k, "p": p,
                              "baseline_p": bp, "y": float(y >= k), "player_id": r["player_id"], "game_id": r["game_id"],
                              "support": x.support(mkey)[0]})
    return pd.DataFrame(trows), pd.DataFrame(mrows)


def ece(p, y, bins: int = 10) -> float:
    """Expected calibration error: average |predicted − actual| over probability bins, weighted by count."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    if not p.size:
        return float("nan")
    idx = np.minimum((p * bins).astype(int), bins - 1)
    tot = 0.0
    for b in range(bins):
        s = idx == b
        if s.any():
            tot += s.sum() * abs(p[s].mean() - y[s].mean())
    return round(float(tot / p.size), 4)


def summarize(t: pd.DataFrame, m: pd.DataFrame) -> dict:
    out = {"thresholds": int(len(t)), "player_games": int(t["game_id"].astype(str).add(t["player_id"]).nunique()) if len(t) else 0, "markets": {}}
    for mkey, d in t.groupby("market"):
        b = d.dropna(subset=["baseline_p"])
        mm = m[m["market"] == mkey]
        mb = mm.dropna(subset=["baseline"])
        out["markets"][mkey] = {
            "model": probability_summary(d["p"], d["y"]),
            "ece": ece(d["p"], d["y"]),
            "by_support": {lvl: {**probability_summary(g["p"], g["y"]), "ece": ece(g["p"], g["y"])}
                           for lvl, g in d.groupby("support")} if "support" in d else {},
            "baseline_same_rows": {"model": probability_summary(b["p"], b["y"]), "baseline": probability_summary(b["baseline_p"], b["y"])} if len(b) else None,
            "calibration": calibration_table(d["p"], d["y"]),
            "mean_projection": {"n": int(len(mm)), "model_mae": round(float(np.mean(np.abs(mm["proj"] - mm["actual"]))), 3),
                                "model_bias": round(float(np.mean(mm["proj"] - mm["actual"])), 3),
                                "recent_avg_mae": round(float(np.mean(np.abs(mb["baseline"] - mb["actual"]))), 3) if len(mb) else None},
        }
    # Confidence: distance of the probability from 50%.
    if len(t):
        conf = pd.cut((t["p"] - 0.5).abs(), [0, 0.1, 0.2, 0.3, 0.4, 0.5], include_lowest=True)
        out["by_confidence"] = [{"distance_from_50": str(k), **probability_summary(g["p"], g["y"]),
                                 "predicted": round(float(g["p"].mean()), 3), "actual": round(float(g["y"].mean()), 3)}
                                for k, g in t.groupby(conf, observed=True)]
        out["overall"] = {**probability_summary(t["p"], t["y"]), "ece": ece(t["p"], t["y"])}
        if "support" in t:
            out["by_support"] = {lvl: {**probability_summary(g["p"], g["y"]), "ece": ece(g["p"], g["y"])} for lvl, g in t.groupby("support")}
        b = t.dropna(subset=["baseline_p"])
        out["overall_vs_baseline"] = {"model": probability_summary(b["p"], b["y"]), "baseline": probability_summary(b["baseline_p"], b["y"])}
        out["calibration"] = calibration_table(t["p"], t["y"])
    return out


def fit_calibration(t: pd.DataFrame) -> dict:
    """Per market, p' = σ(a + b·logit(p)) by Newton's method on log loss. Fit on tuning seasons only."""
    out = {}
    for mkey, d in t.groupby("market"):
        p = np.clip(d["p"].to_numpy(float), 1e-4, 1 - 1e-4)
        y = d["y"].to_numpy(float)
        X = np.column_stack([np.ones_like(p), np.log(p / (1 - p))])
        w = np.array([0.0, 1.0])
        for _ in range(25):
            q = 1 / (1 + np.exp(-(X @ w)))
            g = X.T @ (q - y)
            h = (X * (q * (1 - q))[:, None]).T @ X + 1e-6 * np.eye(2)
            step = np.linalg.solve(h, g)
            w = w - step
            if np.max(np.abs(step)) < 1e-7:
                break
        out[mkey] = [round(float(w[0]), 4), round(float(w[1]), 4)]
    return out


def apply_calibration(t: pd.DataFrame, cal: dict) -> pd.DataFrame:
    t = t.copy()
    p = np.clip(t["p"].to_numpy(float), 1e-4, 1 - 1e-4)
    a = t["market"].map(lambda m: cal.get(m, [0.0, 1.0])[0]).to_numpy(float)
    b = t["market"].map(lambda m: cal.get(m, [0.0, 1.0])[1]).to_numpy(float)
    t["p_raw"] = t["p"]
    t["p"] = 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))
    return t


def objective(t: pd.DataFrame) -> float:
    """Mean of per-market log loss (each market counts equally)."""
    vals = []
    for _, d in t.groupby("market"):
        p = np.clip(d["p"].to_numpy(), 1e-4, 1 - 1e-4)
        y = d["y"].to_numpy()
        vals.append(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))))
    return float(np.mean(vals))


GRID = {
    "carry_dispersion": [3.0, 6.0, 12.0],
    "target_dispersion": [15.0, 30.0, 60.0],
    "efficiency_sd": [0.0, 0.15, 0.3],
    "matchup_strength": [0.0, 0.5, 1.0],
    "half_life_games": [5.0, 8.0, 12.0],
    "rate_prior": [20.0, 40.0, 80.0],
    "share_prior_games": [1.0, 2.0, 4.0],
    "coverage_strength": [0.0, 1.0],
    "blitz_strength": [0.0, 1.0],
    "pressure_strength": [0.0, 1.0],
    "snap_trend_strength": [0.0, 0.5, 1.0],
}


def tune(run: Runner, base: PropParams, log=print, rounds: int = 1) -> tuple[PropParams, list[dict]]:
    """Coordinate search on the tuning seasons. Each result is checkpointed, so an interrupted run resumes."""
    p = base
    history = []
    ckpt = ensure(output_dir("nfl")) / "props_tuning_checkpoint.json"
    done: dict = json.loads(ckpt.read_text()) if ckpt.exists() else {}

    def evaluate(cand: PropParams) -> float:
        key = json.dumps(asdict(cand.settings), sort_keys=True) + json.dumps(asdict(cand.volume), sort_keys=True)
        if key in done:
            return done[key]
        t, _ = score(run.walk(TUNE_SEASONS, cand))
        done[key] = objective(t)
        ckpt.write_text(json.dumps(done))
        return done[key]

    best = evaluate(p)
    history.append({"settings": asdict(p.settings), "objective": round(best, 5)})
    log(f"start {best:.5f}")
    for _round in range(rounds):
        changed = False
        for key, values in GRID.items():
            for v in values:
                if getattr(p.settings, key) == v:
                    continue
                cand = replace(p, settings=replace(p.settings, **{key: v}))
                val = evaluate(cand)
                history.append({"change": {key: v}, "objective": round(val, 5)})
                log(f"  {key}={v}: {val:.5f}{'  *' if val < best - 1e-5 else ''}")
                if val < best - 1e-5:
                    best, p, changed = val, cand, True
        if not changed:
            break
    return p, history


def run(*, do_tune: bool = True, tune_sims: int = 1000, log=print) -> dict:
    t0 = time.time()
    seasons = set(FIT_SEASONS) | set(TUNE_SEASONS) | set(TEST_SEASONS)
    inp = I.load(seasons)
    runner = Runner(inp)
    s = replace(PropSettings(), sims=tune_sims)
    vol = runner.fit_volume(FIT_SEASONS, s)
    log(f"volume model {vol}")
    p = PropParams(s, vol)
    history = []
    if do_tune:
        p, history = tune(runner, p, log)
    else:  # re-score with the settings already in params.json
        p = PropParams(replace(PropParams.load().settings, sims=tune_sims), vol)
    final_s = replace(p.settings, sims=4000)
    # Refit volume with the tuned feature settings on seasons before the test period.
    vol = runner.fit_volume(FIT_SEASONS, final_s)
    p = PropParams(final_s, vol)
    tune_t, tune_m = score(runner.walk(TUNE_SEASONS, p))
    cal = fit_calibration(tune_t)
    test_raw, test_m = score(runner.walk(TEST_SEASONS, p))
    test_t = apply_calibration(test_raw, cal)
    p = replace(p, calibration=cal)
    # Ablation on the test seasons: does each matchup input help?
    ablation = {}
    for key in ("matchup_strength", "coverage_strength", "blitz_strength", "pressure_strength", "snap_trend_strength"):
        if getattr(p.settings, key) == 0:
            continue
        q = replace(p, settings=replace(p.settings, **{key: 0.0}, sims=2000))
        tt, _ = score(runner.walk(TEST_SEASONS, q))
        ablation[key] = {"without": round(objective(tt), 5)}
    q = replace(p, settings=replace(p.settings, sims=2000))
    ref = round(objective(score(runner.walk(TEST_SEASONS, q))[0]), 5)  # uncalibrated, same sims as the ablations
    for v in ablation.values():
        v["with"] = ref

    report = {
        "model_id": "nfl-props", "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tuning_seasons": list(TUNE_SEASONS), "test_seasons": list(TEST_SEASONS), "volume_fit_seasons": list(FIT_SEASONS),
        "settings": asdict(p.settings), "volume": asdict(vol),
        "tuning": {"objective": round(objective(tune_t), 5), "history": history},
        "calibration": cal,
        "test": summarize(test_t, test_m), "test_objective": round(objective(test_t), 5),
        "test_uncalibrated": {"objective": round(objective(test_raw), 5), "overall": summarize(test_raw, test_m).get("overall"),
                              "calibration": summarize(test_raw, test_m).get("calibration")},
        "tune_summary": summarize(tune_t, tune_m),
        "ablation_test_log_loss": ablation,
        "notes": [
            "Graded only on players who played (exchanges void props on players who don't take a snap).",
            "Thresholds the model put below 2% or above 98% are excluded from scoring.",
            "Baseline: share of the player's last 16 games (this season and last) that cleared the threshold, smoothed.",
            "Coverage (man/zone) data for the season being projected is not used; only earlier seasons, as in live use.",
            "Anytime TD is scored on rushing + receiving touchdowns.",
            "Each week is simulated with a fixed seed (season × 100 + week), so every number here reproduces exactly.",
            "Calibration (p' = σ(a + b·logit p)) is fit per market on the tuning seasons and applied unchanged to the test seasons.",
            "Support levels: ok / limited / insufficient history behind the player's estimate (see config.SUPPORT).",
            "No historical prop prices: ROI and closing-line value need stored market snapshots.",
        ],
        "runtime_s": round(time.time() - t0, 1),
    }
    p = replace(p, provenance={"fitted_at": report["generated_at"], "tuning_seasons": list(TUNE_SEASONS),
                               "test_seasons": list(TEST_SEASONS), "status": "provisional: first NFL prop version"})
    p.save()
    out = ensure(output_dir("nfl")) / "props_backtest.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    return report
