"""NBA production run: current ratings -> projections -> ledger -> published board.

    python -m modelroom nba project [--days 7]
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from modelroom.common import board as B
from modelroom.common import ledger
from modelroom.common.hashing import hash_frame, hash_obj
from modelroom.common.paths import backtest_report, ledger_path, output_dir, processed_dir, published_board_path
from modelroom.common.publish import write_board
from modelroom.sources import odds, state

from . import ingest, walkforward
from .backtest import apply
from .config import MODEL_ID, MODEL_VERSION, ModelParams
from .project import total_offsets

RECENT_DAYS = 10


def _team_table(ratings, games: pd.DataFrame, season: int) -> list[dict]:
    """Current ratings plus schedule strength and unweighted season / last-10 form."""
    t = ratings.table()
    names = {}
    for side in ("home", "away"):
        for tid, abbr, name in games[[f"{side}_id", f"{side}_abbr", f"{side}_name"]].drop_duplicates().itertuples(index=False):
            names[int(tid)] = (abbr, name)
    net = dict(zip(t["team_id"], t["net_rating"]))
    played = games[(games["season"] == season) & games["has_box"]]
    rows = []
    for _, r in t.iterrows():
        tid = int(r["team_id"])
        mine = played[(played["home_id"] == tid) | (played["away_id"] == tid)].sort_values("start_time")
        opp = np.where(mine["home_id"] == tid, mine["away_id"], mine["home_id"])
        margin = np.where(mine["home_id"] == tid, mine["home_score"] - mine["away_score"], mine["away_score"] - mine["home_score"])
        rows.append(
            {
                "team_id": tid, "abbr": names.get(tid, ("", ""))[0], "name": names.get(tid, ("", ""))[1],
                "off_rating": round(float(r["off_rating"]), 2), "def_rating": round(float(r["def_rating"]), 2),
                "net_rating": round(float(r["net_rating"]), 2), "pace": round(float(r["pace"]), 2),
                "games_played": int(len(mine)),
                "schedule_strength": round(float(np.mean([net[o] for o in opp])), 2) if len(opp) else None,
                "avg_margin": round(float(np.mean(margin)), 2) if len(margin) else None,
                "last10_margin": round(float(np.mean(margin[-10:])), 2) if len(margin) else None,
            }
        )
        row = rows[-1]
        row["overall"] = row["net_rating"]
        row["overall_unit"] = "net pts / 100 poss"
        row["components"] = [
            {"key": "off", "label": "Off. rating", "value": row["off_rating"], "unit": "pts/100", "higher_is_better": True},
            {"key": "def", "label": "Def. rating", "value": row["def_rating"], "unit": "pts/100", "higher_is_better": False},
            {"key": "pace", "label": "Pace", "value": row["pace"], "unit": "poss/48", "higher_is_better": None},
            {"key": "sos", "label": "Schedule", "value": row["schedule_strength"], "unit": "opp net", "higher_is_better": None},
        ]
    rows.sort(key=lambda x: -x["net_rating"])
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def _game_json(r, params, market: dict | None) -> dict:
    adj = params.adjustments
    proj = {
        "home_score": round(float(r["proj_home_score"]), 1),
        "away_score": round(float(r["proj_away_score"]), 1),
        "margin": round(float(r["proj_margin"]), 1),
        "total": round(float(r["proj_total"]), 1),
        "spread": round(float(r["model_spread"]), 1),
        "home_win_prob": round(float(r["home_win_prob"]), 4),
        "away_win_prob": round(1 - float(r["home_win_prob"]), 4),
        "margin_range_80": B.interval(float(r["proj_margin"]), adj.margin_sigma),
        "total_range_80": B.interval(float(r["proj_total"]), adj.total_sigma),
        "pace": round(float(r["proj_pace"]), 1),
    }
    result = None
    if r["status"] == "final" and pd.notna(r["home_score"]):
        result = {"home_score": int(r["home_score"]), "away_score": int(r["away_score"]),
                  "margin": int(r["home_score"] - r["away_score"]), "total": int(r["home_score"] + r["away_score"])}
    return {
        "game_id": str(r["game_id"]), "start_time": B.iso(r["start_time"]), "game_date": str(r["game_date"]),
        "status": r["status"], "season_type": r["season_type"], "neutral": bool(r["neutral"]),
        "home": {"id": int(r["home_id"]), "abbr": r["home_abbr"], "name": r["home_name"], "net_rating": round(float(r["home_net"]), 2)},
        "away": {"id": int(r["away_id"]), "abbr": r["away_abbr"], "name": r["away_name"], "net_rating": round(float(r["away_net"]), 2)},
        "rest": {"home_days": int(r["home_rest"]), "away_days": int(r["away_rest"]),
                 "home_b2b": bool(r["home_b2b"]), "away_b2b": bool(r["away_b2b"])},
        "adjustments": {"rest_points": round(float(r["rest_adj"]), 2),
                        "injury_points": None if pd.isna(r.get("injury_adj", np.nan)) else round(float(r["injury_adj"]), 2)},
        "projection": proj,
        "market": market,
        "edges": B.model_vs_market(proj, market),
        "result": result,
    }


def run(*, days: int = 7, now: datetime | None = None, write_ledger: bool = True) -> dict:
    now = now or B.now_utc()
    params = ModelParams.load()
    games, team_games = ingest.load()
    games = games.copy()
    season = int(games.loc[games["status"].isin(["scheduled", "final"]), "season"].max())

    history = set(range(int(games["season"].min()) + 1, season + 1))  # needed for the chronological total offset
    proj, finals, ctx = walkforward.run(games, team_games, params.ratings, project_seasons=history, include_scheduled=True)
    if params.adjustments.total_rolling_games:
        proj["total_offset"] = total_offsets(proj, params.adjustments.total_rolling_games)
    proj = proj[proj["season"] == season]
    proj = proj.merge(games[["game_id", "home_name", "away_name"]], on="game_id", how="left")
    proj = apply(proj, params.adjustments, use_injuries=False)  # no NBA injury feed connected
    current = finals[season]

    # Market lines (optional): consensus of stored snapshots.
    snaps_f = processed_dir("nba") / "market_snapshots.parquet"
    snaps = pd.read_parquet(snaps_f) if snaps_f.exists() else None
    markets = B.market_by_game(odds.consensus(snaps), snaps) if snaps is not None and len(snaps) else {}

    upcoming = B.upcoming_window(proj[proj["status"] == "scheduled"], now, days)
    recent = proj[(proj["status"] == "final") & (proj["start_time"] >= pd.Timestamp(now) - pd.Timedelta(days=RECENT_DAYS))]
    season_done = proj[proj["status"] == "final"]

    st = state.read()
    last_ingest = st.get("hoopr_schedule", {}).get("last_success")
    fresh = B.freshness(games[games["season"] == season], last_ingest=last_ingest, now=now, grace_hours=4, stale_hours=36)

    played = games[(games["season"] == season) & games["has_box"]]
    inputs_hash = hash_frame(team_games[team_games["game_id"].isin(played["game_id"])], ["game_id", "team_id", "pts", "fga", "fta", "oreb", "tov"])
    params_hash = hash_obj(params.to_json())
    generated_at = now.isoformat(timespec="seconds")

    if write_ledger and len(upcoming):
        recs = []
        for _, r in upcoming.iterrows():
            recs.append({
                "sport": "nba", "game_id": str(r["game_id"]), "home_team": r["home_abbr"], "away_team": r["away_abbr"],
                "game_date": str(r["game_date"]), "game_start": B.iso(r["start_time"]),
                "pred_home_score": round(float(r["proj_home_score"]), 2), "pred_away_score": round(float(r["proj_away_score"]), 2),
                "pred_margin": round(float(r["proj_margin"]), 2), "pred_total": round(float(r["proj_total"]), 2),
                "home_win_prob": round(float(r["home_win_prob"]), 4), "away_win_prob": round(1 - float(r["home_win_prob"]), 4),
                "model_id": MODEL_ID, "model_version": MODEL_VERSION, "params_hash": params_hash,
                "inputs_hash": inputs_hash, "data_through": fresh["results_through"], "data_ingested_at": last_ingest,
                "generated_at": generated_at,
            })
        appended = ledger.append(ledger_path("nba"), recs)
    else:
        appended = None

    results = games[games["has_box"]][["game_id", "home_score", "away_score"]]
    report_f = backtest_report("nba", MODEL_VERSION)
    backtest = json.loads(report_f.read_text()) if report_f else None
    s_err = season_done
    season_summary = None
    if len(s_err):
        am = s_err["home_score"] - s_err["away_score"]
        hw = (am > 0).astype(float)
        season_summary = {
            "games": int(len(s_err)),
            "margin_mae": round(float(np.mean(np.abs(s_err["proj_margin"] - am))), 2),
            "total_mae": round(float(np.mean(np.abs(s_err["proj_total"] - (s_err["home_score"] + s_err["away_score"])))), 2),
            "winner_correct": round(float(np.mean((s_err["home_win_prob"] > 0.5) == (hw == 1))), 3),
            "note": "Walk-forward: each game projected with ratings from earlier games only, computed after the fact.",
        }

    board = {
        "league": "nba",
        "generated_at": generated_at,
        "season": season,
        "season_label": f"{season - 1}-{str(season)[2:]}",
        "model": {
            "id": MODEL_ID, "version": MODEL_VERSION, "params_hash": params_hash,
            "status": params.provenance.get("status", "provisional"),
            "fitted_at": params.provenance.get("fitted_at"),
            "inputs_hash": inputs_hash,
            "ratings_through_games": int(current.games_used),
            "uncertainty": {"margin_sigma": params.adjustments.margin_sigma, "total_sigma": params.adjustments.total_sigma,
                            "method": "80% range = projection ± 1.28 × out-of-sample error std. dev. (training seasons)"},
        },
        "data": {
            "sources": ["hoopR / sportsdataverse (ESPN)"],
            "freshness": fresh,
            "injuries": {"connected": False, "note": "No NBA injury feed connected; injury adjustments are not applied."},
            "market": {"connected": bool(markets), "sources": sorted({s for m in markets.values() for s in m["sources"]}),
                       "note": None if markets else "No NBA sportsbook lines connected (optional Odds API key or manual CSV)."},
        },
        "upcoming": [_game_json(r, params, markets.get(r["game_id"]) or markets.get(str(r["game_id"]))) for _, r in upcoming.iterrows()],
        "recent": [_game_json(r, params, markets.get(r["game_id"]) or markets.get(str(r["game_id"]))) for _, r in recent.sort_values("start_time", ascending=False).iterrows()],
        "ratings": _team_table(current, games, season),
        "performance": {
            "backtest": None if not backtest else {
                "model_version": backtest.get("model_version"),
                "test_seasons": backtest["windows"]["test"],
                "games": backtest["test"]["without_injuries"]["games"],
                "margin_mae": backtest["test"]["without_injuries"]["margin"]["mae"],
                "total_mae": backtest["test"]["without_injuries"]["total"]["mae"],
                "total_bias": backtest["test"]["without_injuries"]["total"]["bias"],
                "brier": backtest["test"]["without_injuries"]["win_probability"]["brier"],
                "winner_correct": backtest["test"]["without_injuries"]["win_probability"]["accuracy"],
                "baselines": {
                    "home_court_margin_mae": backtest["test"]["baselines"]["home_court_only"]["margin"]["mae"],
                    "season_to_date_margin_mae": backtest["test"]["baselines"]["season_to_date_margin"]["margin"]["mae"],
                    "home_court_total_mae": backtest["test"]["baselines"]["home_court_only"]["total"]["mae"],
                },
                "calibration": backtest["test"]["without_injuries"]["calibration"],
                "market_comparison": backtest.get("market_comparison"),
            },
            "season_to_date": season_summary,
            "ledger": B.grade_ledger(ledger_path("nba"), results),
        },
    }
    path = write_board(published_board_path("nba"), board)
    state.record("nba_model_run", model_version=MODEL_VERSION, upcoming=len(board["upcoming"]))
    return {"board": str(path), "upcoming": len(board["upcoming"]), "recent": len(board["recent"]),
            "ledger": appended.__dict__ if appended else None, "freshness": fresh["status"]}
