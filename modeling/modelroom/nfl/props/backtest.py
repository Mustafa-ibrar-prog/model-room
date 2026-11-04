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

from modelroom.common.propeval import apply_calibration, fit_calibration, objective, summarize
from modelroom.common.paths import ensure, output_dir

from . import features as F
from . import depth as DEPTH
from . import inputs as I
from . import model as M
from .config import FIT_SEASONS, MARKETS, MODEL_VERSION, TEST_SEASONS, TUNE_SEASONS, PropParams, PropSettings, VolumeModel

FEATURE_KEYS = ("half_life_games", "season_carry", "def_half_life_games", "share_prior_games", "rate_prior", "td_prior", "def_prior_games",
                "share_half_life_games", "role_share_weight", "opp_redistribution", "fill_in_weight", "share_model")
BASELINE_GAMES = 16
KEEP_ALL = False  # True: keep every ladder row (the candidate comparison filters rows on the baseline instead)


def _weeks(games: pd.DataFrame, seasons) -> list[tuple[int, int, pd.DataFrame]]:
    g = games[games["season"].isin(seasons) & (games["status"] == "final")]
    return [(int(s), int(w), d) for (s, w), d in g.groupby(["season", "week"], sort=True)]


class Runner:
    """Caches feature contexts by cutoff + feature settings, so tuning simulation settings is cheap."""

    def __init__(self, inp: I.Inputs):
        self.inp = inp
        self._ctx: dict = {}
        self._dhist = None

    def ctx(self, cutoff, season, s: PropSettings, week: int | None = None) -> F.Context:
        role = ((s.opp_redistribution == "depth" and s.role_share_weight < 1.0) or s.share_model == "role") and week is not None
        fkey = tuple(getattr(s, k) for k in FEATURE_KEYS) + ((week,) if role else ())
        key = (cutoff, season, fkey)
        if self._ctx and next(iter(self._ctx))[2][:len(FEATURE_KEYS)] != fkey[:len(FEATURE_KEYS)]:
            self._ctx.clear()  # keep only one feature setting's contexts in memory
        if key not in self._ctx:
            kw = {}
            if role:
                if self._dhist is None:
                    self._dhist = DEPTH.history(self.inp.player_games)
                kw = {"depth_now": DEPTH.ranks(season, week, cutoff), "depth_hist": self._dhist}
            self._ctx[key] = F.build(self.inp.player_games, self.inp.passes, self.inp.rushes, cutoff, season, s, **kw)
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

    def scored(self, seasons, p: PropParams) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Walk and score week by week, keeping only the scored rows (simulations are dropped as we go)."""
        ts, ms = [], []
        for season in sorted(seasons):
            for wk in sorted(self.inp.games.loc[(self.inp.games["season"] == season) & (self.inp.games["status"] == "final"), "week"].unique()):
                t, m = score(self.walk([season], p, only_week=int(wk)))
                ts.append(t)
                ms.append(m)
        return pd.concat(ts, ignore_index=True), pd.concat(ms, ignore_index=True)

    def walk(self, seasons, p: PropParams, only_week: int | None = None) -> list[dict]:
        """One row per projected player-game that was actually played, with simulated distributions."""
        pg = self.inp.player_games
        act = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
        act = act.drop_duplicates(["game_id", "player_id"]).set_index(["game_id", "player_id"])
        recs = []
        for season, week, g in _weeks(self.inp.games, seasons):
            if only_week is not None and week != only_week:
                continue
            cutoff = pd.Timestamp(g["game_date"].min())
            ctx = self.ctx(cutoff, season, p.settings, week)
            ro, inj = I.week_slices(self.inp, season, week)
            need = p.settings.opp_redistribution == "depth" or p.settings.questionable_model == "split" or p.settings.share_model == "role"
            dep = DEPTH.ranks(season, week, cutoff) if need else None
            projs = M.project_games(ctx, g, ro, inj, p, seed=season * 100 + week, depth=dep)
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


def eligible_history(x: M.PlayerProjection, hist) -> bool:
    """Same bar as eligible(), judged on the player's own recent games, so every model is scored on the
    same player-games."""
    if hist is None or len(hist) == 0:
        return False
    h = hist.tail(8)
    if x.group == "QB":
        return float(h["pass_att"].mean()) >= 15
    return float(h["targets"].mean()) >= 2.5 or float(h["carries"].mean()) >= 6


def score(recs: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Threshold rows (prob, baseline prob, outcome) and mean rows (projection vs actual)."""
    trows, mrows = [], []
    for r in recs:
        x: M.PlayerProjection = r["proj"]
        if not (eligible_history(x, r["base"]) if KEEP_ALL else eligible(x)):
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
                if not KEEP_ALL and (p < 0.02 or p > 0.98):
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
        t, _ = run.scored(TUNE_SEASONS, cand)
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
    tune_t, tune_m = runner.scored(TUNE_SEASONS, p)
    cal = fit_calibration(tune_t)
    test_raw, test_m = runner.scored(TEST_SEASONS, p)
    test_t = apply_calibration(test_raw, cal)
    p = replace(p, calibration=cal)
    # Ablation on the test seasons: does each matchup input help?
    ablation = {}
    for key in ("matchup_strength", "coverage_strength", "blitz_strength", "pressure_strength", "snap_trend_strength"):
        if getattr(p.settings, key) == 0:
            continue
        q = replace(p, settings=replace(p.settings, **{key: 0.0}, sims=2000))
        tt, _ = runner.scored(TEST_SEASONS, q)
        ablation[key] = {"without": round(objective(tt), 5)}
    q = replace(p, settings=replace(p.settings, sims=2000))
    ref = round(objective(runner.scored(TEST_SEASONS, q)[0]), 5)  # uncalibrated, same sims as the ablations
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
