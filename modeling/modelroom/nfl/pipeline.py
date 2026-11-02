"""NFL production run: ratings -> projections -> ledger -> published board.

    python -m modelroom nfl project [--days 10]
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

from . import project, walkforward
from .config import MODEL_ID, MODEL_VERSION, ModelParams
from .ratings import EPARater

RECENT_DAYS = 10
TEAM_NAMES = {v: k for k, v in odds.NFL_TEAMS.items()}
DESIGNATIONS = ["Out", "Doubtful", "Questionable"]


def _markets(games: pd.DataFrame) -> dict:
    """Prefer timestamped snapshots (Odds API / manual); else nflverse's published line."""
    out: dict = {}
    snaps_f = processed_dir("nfl") / "market_snapshots.parquet"
    if snaps_f.exists():
        snaps = pd.read_parquet(snaps_f)
        if len(snaps):
            out = B.market_by_game(odds.consensus(snaps), snaps)
    lines = pd.read_parquet(processed_dir("nfl") / "market_lines.parquet")
    for gid, g in lines.groupby("game_id"):
        if gid in out:
            continue
        m = {"spread": None, "total": None, "home_ml": None, "away_ml": None, "books": 0, "captured_at": None,
             "sources": ["nflverse"]}
        for _, r in g.iterrows():
            if r["market"] == "spread":
                m["spread"] = float(r["line"])
            elif r["market"] == "total":
                m["total"] = float(r["line"])
            elif r["market"] == "moneyline":
                m["home_ml"] = None if pd.isna(r["home_price"]) else float(r["home_price"])
                m["away_ml"] = None if pd.isna(r["away_price"]) else float(r["away_price"])
        out[gid] = m
    return out


def _ratings(prep, params, cutoff, season) -> list[dict]:
    s = params.ratings
    tg = prep.tg
    overall = EPARater(tg, s).solve(cutoff, season)
    pas = EPARater(tg.assign(pv=tg["pass_epa"]), s, value="pv", weight="pass_w").solve(cutoff, season)
    rus = EPARater(tg.assign(rv=tg["rush_epa"]), s, value="rv", weight="rush_w").solve(cutoff, season)
    cur = tg[(tg["season"] == season) & (pd.to_datetime(tg["game_date"]).to_numpy().astype("datetime64[D]") < cutoff)]
    allowed = cur.groupby("opp")
    rows = []
    for t in overall.teams:
        i = overall.idx(t)
        mine = cur[cur["team"] == t]
        games = prep.games[(prep.games["season"] == season) & (prep.games["status"] == "final") &
                           ((prep.games["home_team"] == t) | (prep.games["away_team"] == t))].sort_values("start_time")
        margin = np.where(games["home_team"] == t, games["home_score"] - games["away_score"], games["away_score"] - games["home_score"])
        net = overall.off[i] - overall.deff[i]

        def rate(num, den):
            return round(float(num / den), 3) if den else None

        rows.append({
            "team_id": t, "abbr": t, "name": TEAM_NAMES.get(t, t), "games_played": int(len(games)),
            "overall": round(float(params.points.epa_coef * net), 2), "overall_unit": "net pts / game",
            "avg_margin": round(float(np.mean(margin)), 2) if len(margin) else None,
            "last10_margin": round(float(np.mean(margin[-10:])), 2) if len(margin) else None,
            "components": [
                {"key": "off", "label": "Off. EPA/play", "value": round(float(overall.mu + overall.off[i]), 3), "unit": "EPA", "higher_is_better": True},
                {"key": "def", "label": "Def. EPA/play", "value": round(float(overall.mu + overall.deff[i]), 3), "unit": "EPA", "higher_is_better": False},
                {"key": "pass", "label": "Pass EPA", "value": round(float(pas.mu + pas.off[pas.idx(t)]), 3) if t in pas.teams else None, "unit": "EPA", "higher_is_better": True},
                {"key": "rush", "label": "Rush EPA", "value": round(float(rus.mu + rus.off[rus.idx(t)]), 3) if t in rus.teams else None, "unit": "EPA", "higher_is_better": True},
                {"key": "sr", "label": "Success", "value": rate(mine["wsucc"].sum(), mine["wplays"].sum()), "unit": "share", "higher_is_better": True},
                {"key": "third", "label": "3rd down", "value": rate(mine["third_conv"].sum(), mine["third_att"].sum()), "unit": "share", "higher_is_better": True},
                {"key": "rz", "label": "Red zone TD", "value": rate(mine["rz_td"].sum(), mine["rz_drives"].sum()), "unit": "share", "higher_is_better": True},
                {"key": "to", "label": "Turnovers/gm", "value": round(float(mine["turnovers"].sum() / len(mine)), 2) if len(mine) else None, "unit": "per game", "higher_is_better": False},
            ],
            "defense_allowed_epa": round(float(allowed.get_group(t)["epa"].mean()), 3) if t in allowed.groups else None,
        })
    rows.sort(key=lambda r: -r["overall"])
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def _injuries(season: int, week: int | None) -> list[dict]:
    f = processed_dir("nfl") / "injuries.parquet"
    if not f.exists():
        return []
    inj = pd.read_parquet(f)
    inj = inj[(inj["season"] == season)]
    if week is not None and (inj["week"] == week).any():
        inj = inj[inj["week"] == week]
    else:
        inj = inj[inj["week"] == inj["week"].max()]
    inj = inj[inj["report_status"].isin(DESIGNATIONS)].copy()
    order = {s: i for i, s in enumerate(DESIGNATIONS)}
    inj["o"] = inj["report_status"].map(order)
    inj = inj.sort_values(["o", "team", "full_name"])
    return [{
        "team": r["team"], "player": r["full_name"], "position": r.get("position"), "status": r["report_status"],
        "injury": None if pd.isna(r.get("report_primary_injury")) else r["report_primary_injury"],
        "practice": None if pd.isna(r.get("practice_status")) else r["practice_status"],
        "week": int(r["week"]), "impact_points": None,
        "impact_note": "Quarterback changes are modeled through the projected starter; other absences aren't modeled yet.",
    } for _, r in inj.iterrows()]


def _game_json(r, pm, market) -> dict:
    proj = {
        "home_score": round(float(r["proj_home_score"]), 1), "away_score": round(float(r["proj_away_score"]), 1),
        "margin": round(float(r["proj_margin"]), 1), "total": round(float(r["proj_total"]), 1),
        "spread": round(float(r["model_spread"]), 1),
        "home_win_prob": round(float(r["home_win_prob"]), 4), "away_win_prob": round(1 - float(r["home_win_prob"]), 4),
        "margin_range_80": B.interval(float(r["proj_margin"]), pm.margin_sigma),
        "total_range_80": B.interval(float(r["proj_total"]), pm.total_sigma),
    }
    result = None
    if r["status"] == "final" and pd.notna(r["home_score"]):
        result = {"home_score": int(r["home_score"]), "away_score": int(r["away_score"]),
                  "margin": int(r["home_score"] - r["away_score"]), "total": int(r["home_score"] + r["away_score"])}
    return {
        "game_id": r["game_id"], "start_time": B.iso(r["start_time"]), "game_date": str(r["game_date"]),
        "status": r["status"], "season_type": r["game_type"], "week": int(r["week"]), "neutral": bool(r["neutral"]),
        "home": {"id": r["home_team"], "abbr": r["home_team"], "name": TEAM_NAMES.get(r["home_team"], r["home_team"])},
        "away": {"id": r["away_team"], "abbr": r["away_team"], "name": TEAM_NAMES.get(r["away_team"], r["away_team"])},
        "rest": {"home_days": None if pd.isna(r["home_rest"]) else int(r["home_rest"]),
                 "away_days": None if pd.isna(r["away_rest"]) else int(r["away_rest"])},
        "adjustments": {"rest_points": round(float(pm.rest_coef * r["rest_adv"]), 2), "injury_points": None,
                        "qb_points": None if pd.isna(r["qb_points"]) else round(float(r["qb_points"]), 2)},
        "quarterbacks": {"home": None if pd.isna(r["home_qb_name"]) else r["home_qb_name"],
                         "away": None if pd.isna(r["away_qb_name"]) else r["away_qb_name"]},
        "projection": proj, "market": market, "edges": B.model_vs_market(proj, market), "result": result,
    }


def run(*, days: int = 10, now: datetime | None = None, write_ledger: bool = True) -> dict:
    now = now or B.now_utc()
    params = ModelParams.load()
    prep = walkforward.prepare()
    games = prep.games
    season = int(games.loc[games["status"] == "scheduled", "season"].min()) if (games["status"] == "scheduled").any() else int(games["season"].max())
    repl = params.points.qb_replacement_epa

    proj = project.apply(walkforward.run(prep, params.ratings, repl, project_seasons={season}, include_scheduled=True), params.points)
    markets = _markets(games)
    upcoming = B.upcoming_window(proj[proj["status"] == "scheduled"], now, days)
    recent = proj[(proj["status"] == "final") & (proj["start_time"] >= pd.Timestamp(now) - pd.Timedelta(days=RECENT_DAYS))]
    done = proj[proj["status"] == "final"]
    week = int(upcoming["week"].mode().iloc[0]) if len(upcoming) else None  # most upcoming games

    last_ingest = state.read().get("nflverse_games", {}).get("last_success")
    fresh = B.freshness(games[games["season"] == season], last_ingest=last_ingest, now=now, grace_hours=5, stale_hours=36)
    cutoff = np.datetime64(pd.Timestamp(now).tz_convert("America/New_York").date(), "D") + np.timedelta64(1, "D")

    inputs_hash = hash_frame(prep.tg[prep.tg["season"] >= season - 3], ["game_id", "team", "wepa", "wplays"])
    params_hash = hash_obj(params.to_json())
    generated_at = now.isoformat(timespec="seconds")
    appended = None
    if write_ledger and len(upcoming):
        recs = [{
            "sport": "nfl", "game_id": r["game_id"], "home_team": r["home_team"], "away_team": r["away_team"],
            "game_date": str(r["game_date"]), "game_start": B.iso(r["start_time"]),
            "pred_home_score": round(float(r["proj_home_score"]), 2), "pred_away_score": round(float(r["proj_away_score"]), 2),
            "pred_margin": round(float(r["proj_margin"]), 2), "pred_total": round(float(r["proj_total"]), 2),
            "home_win_prob": round(float(r["home_win_prob"]), 4), "away_win_prob": round(1 - float(r["home_win_prob"]), 4),
            "home_qb": None if pd.isna(r["home_qb_name"]) else r["home_qb_name"],
            "away_qb": None if pd.isna(r["away_qb_name"]) else r["away_qb_name"],
            "model_id": MODEL_ID, "model_version": MODEL_VERSION, "params_hash": params_hash, "inputs_hash": inputs_hash,
            "data_through": fresh["results_through"], "data_ingested_at": last_ingest, "generated_at": generated_at,
        } for _, r in upcoming.iterrows()]
        appended = ledger.append(ledger_path("nfl"), recs)

    bt_f = backtest_report("nfl", MODEL_VERSION)
    bt = json.loads(bt_f.read_text()) if bt_f else None
    season_summary = None
    if len(done):
        am = done["actual_margin"]
        season_summary = {
            "games": int(len(done)),
            "margin_mae": round(float(np.mean(np.abs(done["proj_margin"] - am))), 2),
            "total_mae": round(float(np.mean(np.abs(done["proj_total"] - done["actual_total"]))), 2),
            "winner_correct": round(float(np.mean((done["home_win_prob"] > 0.5) == (am > 0))), 3),
            "note": "Walk-forward: each game projected with plays from earlier dates only, computed after the fact.",
        }
    injuries = _injuries(season, week)
    board = {
        "league": "nfl", "generated_at": generated_at, "season": season, "season_label": str(season), "week": week,
        "model": {
            "id": MODEL_ID, "version": MODEL_VERSION, "params_hash": params_hash,
            "status": params.provenance.get("status", "provisional"), "fitted_at": params.provenance.get("fitted_at"),
            "inputs_hash": inputs_hash,
            "uncertainty": {"margin_sigma": params.points.margin_sigma, "total_sigma": params.points.total_sigma,
                            "method": "80% range = projection ± 1.28 × out-of-sample error std. dev. (training seasons)"},
        },
        "data": {
            "sources": ["nflverse"],
            "freshness": fresh,
            "injuries": {"connected": True, "note": "nflverse injury reports", "source": "nflverse"},
            "market": {"connected": True, "sources": sorted({s for m in markets.values() for s in m["sources"]}),
                       "note": "nflverse publishes one line per game without a sportsbook or capture time."},
        },
        "upcoming": [_game_json(r, params.points, markets.get(r["game_id"])) for _, r in upcoming.iterrows()],
        "recent": [_game_json(r, params.points, markets.get(r["game_id"])) for _, r in recent.sort_values("start_time", ascending=False).iterrows()],
        "ratings": _ratings(prep, params, cutoff, season),
        "injuries": injuries,
        "performance": {
            "backtest": None if not bt else {
                "model_version": bt["model_version"], "test_seasons": bt["windows"]["test"],
                "games": bt["test"]["model"]["games"], "margin_mae": bt["test"]["model"]["margin"]["mae"],
                "total_mae": bt["test"]["model"]["total"]["mae"], "total_bias": bt["test"]["model"]["total"]["bias"],
                "brier": bt["test"]["model"]["win_probability"]["brier"],
                "winner_correct": bt["test"]["model"]["win_probability"]["accuracy"],
                "baselines": {
                    "home_court_margin_mae": bt["test"]["baselines"]["home_field_only"]["margin"]["mae"],
                    "home_court_total_mae": bt["test"]["baselines"]["home_field_only"]["total"]["mae"],
                },
                "calibration": bt["test"]["model"]["calibration"],
                "market_comparison": bt["market_comparison"],
            },
            "season_to_date": season_summary,
            "ledger": B.grade_ledger(ledger_path("nfl"), games[games["status"] == "final"][["game_id", "home_score", "away_score"]]),
        },
    }
    path = write_board(published_board_path("nfl"), board)
    state.record("nfl_model_run", model_version=MODEL_VERSION, upcoming=len(board["upcoming"]))
    return {"board": str(path), "upcoming": len(board["upcoming"]), "recent": len(board["recent"]), "week": week,
            "ledger": appended.__dict__ if appended else None, "freshness": fresh["status"]}
