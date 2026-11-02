"""NBA validation: tune on early seasons, fit adjustments, score held-out seasons once.

Windows (seasons named by end year):
  burn-in 2016 | tuning 2017-2022 | test 2023-2026 | live 2027
No projection uses data from its own game date or later (walk-forward).
"""
from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common.hashing import hash_frame
from modelroom.common.metrics import calibration_table, error_summary, probability_summary
from modelroom.common.paths import ensure, output_dir

from . import walkforward
from .config import MODEL_VERSION, FittedAdjustments, ModelParams, RatingSettings
from .injuries import absence_values, fit_injury_coefficient
from .project import REST_ADV_CAP, finalize

BURN_IN = 2016
TUNE = list(range(2017, 2023))
TEST = list(range(2023, 2027))

GRID_EFF = {
    "half_life_days": [60.0, 120.0, 240.0, 480.0],
    "prior_games": [6.0, 12.0, 24.0],
    "prior_retention": [0.5, 0.7, 0.85],
}
GRID_PACE = {"pace_prior_games": [1.0, 2.5, 5.0, 10.0], "pace_retention": [0.2, 0.4, 0.6, 0.8]}


def _scored(p: pd.DataFrame) -> pd.DataFrame:
    return p[p["actual_margin"].notna()].copy()


def tune(games, team_games, *, log=print) -> RatingSettings:
    best, best_score = None, np.inf
    base = RatingSettings()
    for values in itertools.product(*GRID_EFF.values()):
        s = replace(base, **dict(zip(GRID_EFF, values)))
        p, _, _ = walkforward.run(games, team_games, s, project_seasons=set(TUNE), until_season=TUNE[-1])
        p = _scored(p)
        score = float(np.mean(np.abs(p["margin_raw"] - p["actual_margin"])))
        if score < best_score:
            best, best_score = s, score
    log(f"  efficiency settings: {dict((k, getattr(best, k)) for k in GRID_EFF)}  margin MAE {best_score:.3f}")

    best_pace, pace_score = best, np.inf
    for values in itertools.product(*GRID_PACE.values()):
        s = replace(best, **dict(zip(GRID_PACE, values)))
        p, _, _ = walkforward.run(games, team_games, s, project_seasons=set(TUNE), until_season=TUNE[-1])
        p = _scored(p)
        resid = p["actual_total"] - p["total_raw"]
        score = float(np.mean(np.abs(resid - resid.mean())))  # after the fitted total offset
        if score < pace_score:
            best_pace, pace_score = s, score
    log(f"  pace settings: {dict((k, getattr(best_pace, k)) for k in GRID_PACE)}  total MAE {pace_score:.3f}")
    return best_pace


def fit_adjustments(p: pd.DataFrame, injury_k: float | None) -> FittedAdjustments:
    """Least squares on tuning-season residuals. No intercept for margin (home edge is in the ratings)."""
    p = _scored(p)
    b2b = p["away_b2b"].astype(float) - p["home_b2b"].astype(float)
    rest_adv = p["home_rest"].clip(upper=REST_ADV_CAP) - p["away_rest"].clip(upper=REST_ADV_CAP)
    inj = p["injury_value_diff"].fillna(0.0) * (injury_k or 0.0) if "injury_value_diff" in p else 0.0
    y = p["actual_margin"] - p["margin_raw"] - inj
    X = np.column_stack([b2b, rest_adv])
    coef, *_ = np.linalg.lstsq(X, y.to_numpy(), rcond=None)
    total_points = float(np.mean(p["actual_total"] - p["total_raw"]))
    resid = y.to_numpy() - X @ coef
    return FittedAdjustments(
        b2b_points=round(float(coef[0]), 4),
        rest_points=round(float(coef[1]), 4),
        total_points=round(total_points, 4),
        margin_sigma=round(float(np.std(resid)), 4),
        injury_points_per_value=None if injury_k is None else round(float(injury_k), 5),
    )


def apply(p: pd.DataFrame, adj: FittedAdjustments, *, use_injuries: bool) -> pd.DataFrame:
    q = p.copy()
    b2b = q["away_b2b"].astype(float) - q["home_b2b"].astype(float)
    rest_adv = q["home_rest"].clip(upper=REST_ADV_CAP) - q["away_rest"].clip(upper=REST_ADV_CAP)
    q["rest_adj"] = adj.b2b_points * b2b + adj.rest_points * rest_adv
    k = adj.injury_points_per_value
    q["injury_adj"] = q["injury_value_diff"] * k if (use_injuries and k is not None and "injury_value_diff" in q) else np.nan
    return finalize(q, adj)


def baselines(train: pd.DataFrame, test: pd.DataFrame, games: pd.DataFrame) -> dict:
    """Simple comparisons, each fit on training seasons only."""
    hca = float(train["actual_margin"].mean())
    avg_total = float(train["actual_total"].mean())
    out = {
        "home_court_only": {
            "margin": error_summary(np.full(len(test), hca), test["actual_margin"]),
            "total": error_summary(np.full(len(test), avg_total), test["actual_total"]),
        }
    }
    # Season-to-date average point margin for each team, using only earlier games.
    g = games[games["has_box"]][["game_id", "season", "game_date", "home_id", "away_id", "home_score", "away_score"]]
    long = pd.concat(
        [
            g.assign(team=g["home_id"], m=g["home_score"] - g["away_score"]),
            g.assign(team=g["away_id"], m=g["away_score"] - g["home_score"]),
        ]
    ).sort_values(["team", "season", "game_date", "game_id"])
    long["prior_avg"] = long.groupby(["team", "season"])["m"].transform(lambda s: s.shift(1).expanding().mean()).fillna(0.0)
    look = long.set_index(["game_id", "team"])["prior_avg"]
    mh = look.reindex(list(zip(test["game_id"], test["home_id"]))).to_numpy()
    ma = look.reindex(list(zip(test["game_id"], test["away_id"]))).to_numpy()
    out["season_to_date_margin"] = {"margin": error_summary(mh - ma + hca, test["actual_margin"])}
    return out


def evaluate(p: pd.DataFrame) -> dict:
    s = _scored(p)
    by_season = {}
    for season, g in s.groupby("season"):
        by_season[int(season)] = {
            "margin": error_summary(g["proj_margin"], g["actual_margin"]),
            "total": error_summary(g["proj_total"], g["actual_total"]),
        }
    home_won = (s["actual_margin"] > 0).astype(float)
    return {
        "games": int(len(s)),
        "margin": error_summary(s["proj_margin"], s["actual_margin"]),
        "total": error_summary(s["proj_total"], s["actual_total"]),
        "win_probability": probability_summary(s["home_win_prob"], home_won),
        "calibration": calibration_table(s["home_win_prob"], home_won),
        "by_season": by_season,
    }


def run(games, team_games, *, log=print, player_box=None) -> dict:
    """Full validation. Returns the report and writes params.json + report files."""
    log("Tuning rating settings on 2016-17 to 2021-22 (walk-forward)...")
    settings = tune(games, team_games, log=log)

    log("Projecting tuning and test seasons with chosen settings...")
    proj, _, _ = walkforward.run(games, team_games, settings, project_seasons=set(TUNE + TEST), until_season=TEST[-1])

    injury_k = None
    if player_box is not None:
        vals = absence_values(games, player_box)
        proj = proj.merge(vals, on="game_id", how="left")
        train_raw = _scored(proj[proj["season"].isin(TUNE)])
        injury_k = fit_injury_coefficient(train_raw)
        log(f"  injury coefficient k = {injury_k:.4f} points per unit of absent value")

    train = proj[proj["season"].isin(TUNE)]
    adj = fit_adjustments(train, injury_k)
    log(f"  adjustments: {adj}")

    test = proj[proj["season"].isin(TEST)]
    report = {
        "model_id": "nba-game",
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": {"burn_in": BURN_IN, "tuning": TUNE, "test": TEST},
        "settings": settings.__dict__,
        "adjustments": adj.__dict__,
        "data": {
            "source": "hoopR / sportsdataverse (ESPN)",
            "games_hash": hash_frame(games[games["has_box"]], ["game_id", "home_score", "away_score"]),
        },
        "test": {
            "without_injuries": evaluate(apply(test, adj, use_injuries=False)),
            "baselines": baselines(_scored(train), _scored(test), games),
        },
        "tuning_in_sample": evaluate(apply(train, adj, use_injuries=False)),
        "market_comparison": "Not run: no historical NBA lines are connected (see docs/data-sources.md).",
    }
    if injury_k is not None:
        report["test"]["with_known_absences"] = evaluate(apply(test, adj, use_injuries=True))
        report["test"]["with_known_absences"]["note"] = (
            "Uses players actually absent from each box score. That assumes the injury report "
            "was known before tip-off, so treat this as an upper bound."
        )

    params = ModelParams(
        ratings=settings,
        adjustments=adj,
        provenance={
            "fitted_at": report["generated_at"],
            "tuning_seasons": TUNE,
            "test_seasons": TEST,
            "games_hash": report["data"]["games_hash"],
        },
    )
    params.save()
    out = ensure(output_dir("nba"))
    (out / "backtest.json").write_text(json.dumps(report, indent=2, default=str))
    return report
