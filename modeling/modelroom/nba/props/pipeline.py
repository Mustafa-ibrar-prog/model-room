"""NBA props production run: projections → (optional) stored market prices → ledger → published board.

    python -m modelroom nba props [--days 3]
"""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime

import numpy as np
import pandas as pd

from modelroom.common import board as B
from modelroom.common import ledger
from modelroom.common.hashing import hash_frame, hash_obj
from modelroom.common.paths import MODELING_ROOT, data_root, ensure, ledger_path, output_dir
from modelroom.common.publish import write_board
from modelroom.markets import compare as C
from modelroom.markets import prices
from modelroom.markets.teams import NBA_TEAMS
from modelroom.sources import state

from . import inputs as I
from . import model as M
from .backtest import eligible
from .config import MARKETS, MODEL_ID, MODEL_VERSION, PropParams

TEAM_NAMES = {}
for _name, _code in NBA_TEAMS.items():
    TEAM_NAMES.setdefault(_code, _name)
STEP = {"pts": 5, "pra": 5}


def published_path():
    return data_root() / "published" / "nba_props.json"


def backtest_summary() -> dict | None:
    local = output_dir("nba") / "props_backtest.json"
    f = local if local.exists() and json.loads(local.read_text()).get("model_version") == MODEL_VERSION else None
    if f is None:
        c = MODELING_ROOT.parent / "docs" / "models" / "results" / f"nba-props-backtest-{MODEL_VERSION}.json"
        f = c if c.exists() else None
    if f is None:
        return None
    r = json.loads(f.read_text())
    t = r["test"]
    return {
        "model_version": r["model_version"], "test_seasons": r["test_seasons"], "thresholds": t["thresholds"],
        "overall": t.get("overall"), "overall_vs_baseline": t.get("overall_vs_baseline"),
        "by_market": {k: {"log_loss": v["model"]["log_loss"], "brier": v["model"]["brier"], "n": v["model"]["n"], "ece": v.get("ece"),
                          "baseline_log_loss": (v.get("baseline_same_rows") or {}).get("baseline", {}).get("log_loss"),
                          "model_log_loss_same_rows": (v.get("baseline_same_rows") or {}).get("model", {}).get("log_loss"),
                          "mean_mae": v["mean_projection"]["model_mae"], "recent_avg_mae": v["mean_projection"]["recent_avg_mae"]}
                      for k, v in t["markets"].items()},
        "calibration": t.get("calibration"), "by_confidence": t.get("by_confidence"), "by_support": t.get("by_support"),
        "notes": r.get("notes", []),
    }


def display_thresholds(x: M.PlayerProjection, stat: str) -> list[float]:
    sims = x.sims[stat]
    step = STEP.get(stat, 1)
    out = set()
    for q in (0.25, 0.5, 0.75):
        out.add(float(max(step, round(float(np.quantile(sims, q)) / step) * step)))
    return sorted(out)


def player_entry(x: M.PlayerProjection, p: PropParams, quotes: list, now: datetime, reliability: dict) -> dict:
    support, note = x.support()
    markets = {}
    for mkey, m in MARKETS.items():
        stat = m["stat"]
        sims = x.sims[stat]
        rows = {(">=", k, None): [] for k in display_thresholds(x, stat)}
        for q in quotes:
            if q.market == mkey:
                rows.setdefault((q.op, float(q.threshold), q.variant), []).append(q)
        th = []
        for (op, k, variant), qs in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2] or "")):
            raw = x.prob(stat, k, op)
            prob = p.calibrate(mkey, raw)
            views = [C.view(q, prob, now) for q in qs]
            best = C.best(views) if views else None
            th.append({"op": op, "threshold": k, "variant": variant, "model_prob": round(prob, 4), "model_prob_raw": round(raw, 4),
                       "quotes": [asdict(v) for v in views], "best": best, "edge_grade": C.grade(best, support, reliability.get(mkey))})
        markets[mkey] = {"label": m["label"], "mean": round(float(np.mean(sims)), 2), "median": round(float(np.median(sims)), 1),
                         "sd": round(float(np.std(sims)), 2),
                         "range_80": [round(float(np.quantile(sims, 0.1)), 1), round(float(np.quantile(sims, 0.9)), 1)],
                         "support": support, "support_note": note, "thresholds": th}
    return {"player_id": x.player_id, "name": x.name, "team": x.team, "opp": x.opp, "position": x.group, "game_id": x.game_id,
            "injury_status": None, "markets": markets, "inputs": {k: v for k, v in x.inputs.items() if k != "sample"}}


def run(*, days: int = 3, now: datetime | None = None, write_ledger: bool = True, sims: int | None = None) -> dict:
    now = now or B.now_utc()
    p = PropParams.load()
    p = replace(p, settings=replace(p.settings, sims=sims or 10000))
    inp = I.load()
    gp = inp.games
    upcoming = B.upcoming_window(gp[gp["status"] == "scheduled"], now, days)
    season = int(upcoming["season"].max()) if len(upcoming) else int(gp["season"].max())
    today = pd.Timestamp(pd.Timestamp(now).tz_convert("America/New_York").date())
    ctx = M.build(inp.player_games, inp.pace, today, season, p.settings)
    projs, seeds = [], {}
    for day, g in upcoming.groupby("game_date"):
        seeds[str(day)] = int(str(day).replace("-", ""))
        projs += M.project_games(ctx, g, p, seed=seeds[str(day)])
    projs = [x for x in projs if eligible(x)]

    games_df = upcoming.rename(columns={"home_abbr": "home_team", "away_abbr": "away_team"})[["game_id", "game_date", "home_team", "away_team"]]
    plist = pd.DataFrame([{"game_id": x.game_id, "player_id": x.player_id, "name": x.name, "team": x.team, "sportradar_id": None} for x in projs])
    idx_pub, idx_all, info, unmatched = prices.load("nba", games_df, plist)

    bt = backtest_summary()
    reliability = (bt or {}).get("by_market", {})
    by_game, local_games = {}, {}
    local_only = any(i["enabled"] and not i["publishable"] for i in info)
    for x in projs:
        by_game.setdefault(x.game_id, []).append(player_entry(x, p, idx_pub.get((x.game_id, x.player_id), []), now, reliability))
        if local_only and idx_all.get((x.game_id, x.player_id)):
            local_games.setdefault(x.game_id, []).append(player_entry(x, p, idx_all[(x.game_id, x.player_id)], now, reliability))
    games_json = []
    for _, g in upcoming.iterrows():
        players = sorted(by_game.get(g["game_id"], []), key=lambda e: (e["team"], -e["markets"]["points"]["mean"]))
        games_json.append({"game_id": g["game_id"], "start_time": B.iso(g["start_time"]), "game_date": str(g["game_date"]), "week": None,
                           "home": {"abbr": g["home_abbr"], "name": TEAM_NAMES.get(g["home_abbr"], g["home_abbr"])},
                           "away": {"abbr": g["away_abbr"], "name": TEAM_NAMES.get(g["away_abbr"], g["away_abbr"])},
                           "players": players})

    pg = inp.player_games
    inputs_hash = hash_frame(pg[pg["season"] >= season - 2], ["game_id", "player_id", "minutes", "pts"])
    params_hash = hash_obj(p.to_json())
    generated_at = now.isoformat(timespec="seconds")
    appended = None
    if write_ledger and projs:
        starts = upcoming.set_index("game_id")["start_time"]
        dates = upcoming.set_index("game_id")["game_date"].astype(str)
        recs = []
        for x in projs:
            probs = {mkey: {**{str(k): round(p.calibrate(mkey, x.prob(m["stat"], k)), 4) for k in m["ladder"]},
                            "mean": round(x.mean(m["stat"]), 2), "sd": round(x.sd(m["stat"]), 2)} for mkey, m in MARKETS.items()}
            recs.append({"sport": "nba", "kind": "player_props", "game_id": f"{x.game_id}|{x.player_id}", "nba_game_id": x.game_id,
                         "player_id": x.player_id, "player": x.name, "team": x.team, "game_start": B.iso(starts[x.game_id]),
                         "probabilities": probs, "support": x.support()[0], "projected_minutes": x.inputs["projected_minutes"],
                         "model_id": MODEL_ID, "model_version": MODEL_VERSION, "params_hash": params_hash, "inputs_hash": inputs_hash,
                         "generated_at": generated_at, "sims": p.settings.sims, "seed": seeds.get(dates[x.game_id])})
        appended = ledger.append(ledger_path("nba_props"), recs)

    board = {
        "league": "nba", "kind": "player_props", "generated_at": generated_at, "season": season, "week": None,
        "model": {"id": MODEL_ID, "version": MODEL_VERSION, "params_hash": params_hash, "inputs_hash": inputs_hash,
                  "status": p.provenance.get("status", "provisional"), "fitted_at": p.provenance.get("fitted_at"),
                  "sims": p.settings.sims, "seeds": seeds,
                  "independence": "Uses only box scores, minutes, pace and the game engine. Exchange prices are never an input; they are compared afterwards.",
                  "injuries": "No NBA injury feed is connected. A rotation player who missed his team's last two games is treated as out; anyone else is assumed available."},
        "data": {"last_ingest": state.read().get("hoopr_schedule", {}).get("last_success"),
                 "results_through": str(pg.loc[pg["played"], "game_date"].max()),
                 "markets": [i for i in info if i["publishable"] or i["provider"] == "manual"],
                 "markets_not_published": [{"provider": i["provider"], "reason": i["reason"]} for i in info if not i["publishable"] and i["provider"] != "manual"],
                 "unmatched_quotes": unmatched,
                 "comparison_rules": {"max_age_min": C.MAX_AGE_MIN, "max_spread": C.MAX_SPREAD, "min_size": C.MIN_SIZE, "min_ev": C.MIN_EV}},
        "performance": {"backtest": bt},
        "games": games_json,
    }
    path = write_board(published_path(), board)
    if local_games:
        write_board(ensure(output_dir("nba")) / "props_compare_local.json",
                    {**board, "games": [{"game_id": k, "players": v} for k, v in local_games.items()], "note": "Local only."})
    state.record("nba_props_run", model_version=MODEL_VERSION, players=len(projs))
    return {"board": str(path), "games": len(games_json), "players": len(projs),
            "quotes_matched": sum(len(v) for v in idx_all.values()), "ledger": appended.__dict__ if appended else None}
