"""NFL validation: tune on 2021-22, fit coefficients there, score 2023-25 once.

Seasons 2018-2020 serve only as rating history (3-season window).
"""
from __future__ import annotations

import itertools
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common.hashing import hash_frame
from modelroom.common.metrics import against_line, calibration_table, error_summary, probability_summary
from modelroom.common.paths import ensure, output_dir, processed_dir

from . import project, qb, walkforward
from .config import MODEL_VERSION, ModelParams, RatingSettings

HISTORY = [2018, 2019, 2020]
TUNE = [2021, 2022]
TEST = [2023, 2024, 2025]

GRID = {
    "half_life_games": [4.0, 8.0, 16.0, 32.0],
    "season_carry": [0.3, 0.5, 0.7],
    "prior_games": [1.0, 3.0, 8.0],
}
QB_GRID = [100.0, 250.0, 600.0]


def _market(games_ids: pd.Series) -> pd.DataFrame:
    """nflverse market lines as home margin (−spread) and total. Missing stays NaN."""
    m = pd.read_parquet(processed_dir("nfl") / "market_lines.parquet")
    sp = m[m["market"] == "spread"].set_index("game_id")["line"]
    to = m[m["market"] == "total"].set_index("game_id")["line"]
    return pd.DataFrame({"game_id": games_ids, "market_margin": -games_ids.map(sp), "market_total": games_ids.map(to)})


def _mae(q: pd.DataFrame) -> float:
    return float(np.mean(np.abs(q["proj_margin"] - q["actual_margin"])))


def tune(prep, repl, log=print) -> RatingSettings:
    base = RatingSettings()
    best, best_score = base, np.inf
    for values in itertools.product(*GRID.values()):
        s = replace(base, **dict(zip(GRID, values)))
        p = walkforward.run(prep, s, repl, project_seasons=set(TUNE))
        score = _mae(project.apply(p, project.fit(p, repl)))
        if score < best_score:
            best, best_score = s, score
    log(f"  rating settings: {dict((k, getattr(best, k)) for k in GRID)}  margin MAE {best_score:.3f}")
    best_q, q_score = best, np.inf
    for k in QB_GRID:
        s = replace(best, qb_shrink_dropbacks=k)
        p = walkforward.run(prep, s, repl, project_seasons=set(TUNE))
        score = _mae(project.apply(p, project.fit(p, repl)))
        if score < q_score:
            best_q, q_score = s, score
    log(f"  QB shrinkage: {best_q.qb_shrink_dropbacks} dropbacks  margin MAE {q_score:.3f}")
    return best_q


def evaluate(q: pd.DataFrame) -> dict:
    s = q[q["actual_margin"].notna()]
    home_won = (s["actual_margin"] > 0).astype(float)
    ties = s["actual_margin"] == 0
    by_team = {}
    for team in sorted(set(s["home_team"]) | set(s["away_team"])):
        g = s[(s["home_team"] == team) | (s["away_team"] == team)]
        by_team[team] = round(float(np.mean(np.abs(g["proj_margin"] - g["actual_margin"]))), 2)
    return {
        "games": int(len(s)),
        "margin": error_summary(s["proj_margin"], s["actual_margin"]),
        "total": error_summary(s["proj_total"], s["actual_total"]),
        "home_score": error_summary(s["proj_home_score"], s["home_score"]),
        "away_score": error_summary(s["proj_away_score"], s["away_score"]),
        "win_probability": probability_summary(s.loc[~ties, "home_win_prob"], home_won[~ties]),
        "calibration": calibration_table(s.loc[~ties, "home_win_prob"], home_won[~ties]),
        "by_season": {int(k): {"margin": error_summary(g["proj_margin"], g["actual_margin"]),
                               "total": error_summary(g["proj_total"], g["actual_total"])} for k, g in s.groupby("season")},
        "by_team_margin_mae": by_team,
    }


def market_comparison(q: pd.DataFrame) -> dict:
    s = q[q["actual_margin"].notna()].merge(_market(q["game_id"]), on="game_id", how="left")
    sp = s.dropna(subset=["market_margin"])
    to = s.dropna(subset=["market_total"])
    return {
        "note": "nflverse lines; capture time undocumented, so this compares accuracy, not a betting record.",
        "spread": {
            "games": int(len(sp)),
            "model_mae": round(float(np.mean(np.abs(sp["proj_margin"] - sp["actual_margin"]))), 3),
            "market_mae": round(float(np.mean(np.abs(sp["market_margin"] - sp["actual_margin"]))), 3),
            "model_vs_market_corr": round(float(sp["proj_margin"].corr(sp["market_margin"])), 3),
            "side_record_all": against_line(sp["proj_margin"], sp["market_margin"], sp["actual_margin"]),
            "side_record_edge_3plus": against_line(sp["proj_margin"], sp["market_margin"], sp["actual_margin"], min_edge=3.0),
        },
        "total": {
            "games": int(len(to)),
            "model_mae": round(float(np.mean(np.abs(to["proj_total"] - to["actual_total"]))), 3),
            "market_mae": round(float(np.mean(np.abs(to["market_total"] - to["actual_total"]))), 3),
            "side_record_all": against_line(to["proj_total"], to["market_total"], to["actual_total"]),
        },
    }


def run(log=print) -> dict:
    prep = walkforward.prepare()
    repl = qb.replacement_level(prep.qbd, HISTORY + TUNE)
    log(f"QB replacement level (2018-2022 non-primary passers): {repl:.4f} EPA/dropback")
    log("Tuning on 2021-2022 (walk-forward)...")
    settings = tune(prep, repl, log=log)

    train = walkforward.run(prep, settings, repl, project_seasons=set(TUNE))
    pm = project.fit(train, repl)
    log(f"  points model: {pm}")
    test = project.apply(walkforward.run(prep, settings, repl, project_seasons=set(TEST)), pm)
    train_q = project.apply(train, pm)

    hca = float(train_q["actual_margin"].mean())
    avg_total = float(train_q["actual_total"].mean())
    t = test[test["actual_margin"].notna()]
    mc = market_comparison(test)
    report = {
        "model_id": "nfl-game", "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": {"history": HISTORY, "tuning": TUNE, "test": TEST},
        "settings": asdict(settings), "points_model": asdict(pm),
        "data": {"source": "nflverse", "games_hash": hash_frame(prep.games[prep.games["status"] == "final"], ["game_id", "home_score", "away_score"])},
        "test": {
            "model": evaluate(test),
            "baselines": {
                "home_field_only": {"margin": error_summary(np.full(len(t), hca), t["actual_margin"]),
                                    "total": error_summary(np.full(len(t), avg_total), t["actual_total"])},
            },
        },
        "market_comparison": mc,
        "tuning_in_sample": evaluate(train_q),
        "notes": [
            "Starting QBs for past games come from games.csv (the actual starter); projected starters are used live.",
            "Stadium roof type is taken from each stadium's usual roof across the data.",
        ],
    }
    params = ModelParams(settings, pm, {
        "fitted_at": report["generated_at"], "tuning_seasons": TUNE, "test_seasons": TEST,
        "games_hash": report["data"]["games_hash"], "status": "provisional: first NFL version",
    })
    params.save()
    out = ensure(output_dir("nfl"))
    (out / "backtest.json").write_text(json.dumps(report, indent=2, default=str))
    return report
