"""Results history for the website: what the model said before each game, and what happened.

    python -m modelroom history            (run after the projection commands)

Projections come only from the prediction ledgers, which are written before kickoff and never edited.
Nothing here re-projects a past game. Dates before the ledger began show results only.

Writes (data/published/history/<league>/):
  index.json        dates available, with counts
  <YYYY-MM-DD>.json  that day's games (final score, recorded pre-game projection, error) and recorded
                    prop projections (mean, sd, threshold probabilities) with the actual stat and Hit/Miss
and data/published/performance_<league>.json: graded accuracy of everything recorded so far.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.paths import data_root, ensure, ledger_path
from modelroom.common.publish import write_board

SEASONS_BACK = 1  # results-only dates: the current season and the one before


def _out(league: str):
    return ensure(data_root() / "published" / "history" / league)


def _pregame(records: list[dict], start_key: str = "game_start") -> dict:
    """Latest record per key made before its game started (the ledger only accepts pre-game records)."""
    best: dict = {}
    for r in records:
        k = r["game_id"]
        if r["generated_at"] >= r[start_key]:
            continue
        if k not in best or r["generated_at"] > best[k]["generated_at"]:
            best[k] = r
    return best


def _games_table(league: str) -> pd.DataFrame:
    if league == "nfl":
        from modelroom.nfl.ingest import load_games

        g = load_games()
        g = g[g["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])]
        return pd.DataFrame({"game_id": g["game_id"].astype(str), "season": g["season"], "game_date": g["game_date"].astype(str),
                             "start_time": g["start_time"], "home": g["home_team"], "away": g["away_team"],
                             "home_score": g["home_score"], "away_score": g["away_score"], "status": g["status"]})
    from modelroom.nba import ingest

    g, _ = ingest.load()
    return pd.DataFrame({"game_id": g["game_id"].astype(str), "season": g["season"], "game_date": g["game_date"].astype(str),
                         "start_time": g["start_time"], "home": g["home_abbr"], "away": g["away_abbr"],
                         "home_score": g["home_score"], "away_score": g["away_score"],
                         "status": g["status"].replace({"final_no_box": "final"})})


def _player_stats(league: str) -> dict:
    """(game_id, player_id) → {stat: value} for players who played."""
    if league == "nfl":
        from modelroom.nfl import player_data

        pg, _, _ = player_data.load()
        pg = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
        pg = pg.assign(rush_rec_yds=pg["rush_yds"] + pg["rec_yds"], td_any=pg["rush_td"] + pg["rec_td"])
        from modelroom.nfl.props.config import MARKETS
    else:
        from modelroom.nba.props import data

        pg = data.load()
        pg = pg[pg["played"]]
        from modelroom.nba.props.config import MARKETS
    stats = {m["stat"] for m in MARKETS.values()}
    cols = [c for c in stats if c in pg.columns]
    out = {}
    for row in pg[["game_id", "player_id", *cols]].itertuples(index=False):
        out[(str(row[0]), str(row[1]))] = dict(zip(cols, row[2:]))
    return out, {k: m["stat"] for k, m in MARKETS.items()}, {k: m["label"] for k, m in MARKETS.items()}


def _f(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def build(league: str) -> dict:
    games = _games_table(league)
    season_now = int(games.loc[games["status"].isin(["final", "scheduled"]), "season"].max())
    games = games[games["season"] >= season_now - SEASONS_BACK]
    game_recs = _pregame(ledger.read(ledger_path(league)))
    prop_recs = _pregame(ledger.read(ledger_path(f"{league}_props")))
    stats, stat_of, label_of = _player_stats(league)
    gid_key = "nfl_game_id" if league == "nfl" else "nba_game_id"
    props_by_game: dict = {}
    for r in prop_recs.values():
        props_by_game.setdefault(str(r[gid_key]), []).append(r)

    today = datetime.now(timezone.utc).date().isoformat()
    out = _out(league)
    index, grades_games, grades_props = [], [], []
    for day, g in games.groupby("game_date"):
        if day > today:
            continue
        day_games, day_props = [], []
        for _, x in g.sort_values("start_time").iterrows():
            final = x["status"] == "final" and pd.notna(x["home_score"])
            rec = game_recs.get(x["game_id"])
            pre = None
            if rec:
                pre = {k: rec.get(k) for k in ("generated_at", "model_version", "pred_home_score", "pred_away_score", "pred_margin", "pred_total", "home_win_prob")}
            err = None
            if final and pre:
                margin = float(x["home_score"] - x["away_score"])
                total = float(x["home_score"] + x["away_score"])
                err = {"margin_error": round(pre["pred_margin"] - margin, 1), "total_error": round(pre["pred_total"] - total, 1),
                       "winner_correct": None if margin == 0 else bool((pre["home_win_prob"] > 0.5) == (margin > 0))}
                grades_games.append({"date": day, "p": pre["home_win_prob"], "y": float(margin > 0), "margin_err": abs(err["margin_error"]),
                                     "total_err": abs(err["total_error"]), "correct": err["winner_correct"]})
            day_games.append({"game_id": x["game_id"], "start_time": None if pd.isna(x["start_time"]) else pd.Timestamp(x["start_time"]).isoformat(),
                              "home": x["home"], "away": x["away"], "status": x["status"],
                              "final": {"home": int(x["home_score"]), "away": int(x["away_score"])} if final else None,
                              "pregame": pre, "result": err})
            for r in props_by_game.get(x["game_id"], []):
                actual = stats.get((x["game_id"], str(r["player_id"]))) if final else None
                markets = {}
                for mkey, probs in r["probabilities"].items():
                    stat = stat_of.get(mkey)
                    a = _f(actual.get(stat)) if actual and stat in actual else None
                    th = []
                    for k, p in probs.items():
                        if k in ("mean", "sd", "support"):
                            continue
                        hit = None if a is None else bool(a >= float(k))
                        th.append({"k": float(k), "p": p, "hit": hit})
                        if hit is not None:
                            grades_props.append({"date": day, "market": mkey, "player": r["player"], "player_id": str(r["player_id"]),
                                                 "p": p, "y": float(hit)})
                    markets[mkey] = {"label": label_of.get(mkey, mkey), "mean": probs.get("mean"), "sd": probs.get("sd"),
                                     "support": probs.get("support") or r.get("support"), "actual": a,
                                     "thresholds": sorted(th, key=lambda t: t["k"])}
                day_props.append({"game_id": x["game_id"], "player_id": str(r["player_id"]), "player": r["player"], "team": r["team"],
                                  "generated_at": r["generated_at"], "model_version": r["model_version"],
                                  "played": actual is not None if final else None, "markets": markets})
        write_board(out / f"{day}.json", {"league": league, "kind": "history", "date": day, "games": day_games, "props": day_props})
        index.append({"date": day, "games": len(day_games), "with_projection": sum(1 for x in day_games if x["pregame"]),
                      "props": len(day_props)})
    first = min((r["generated_at"][:10] for r in game_recs.values()), default=None)
    write_board(out / "index.json", {"league": league, "kind": "history_index", "first_recorded": first,
                                     "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dates": index})
    perf = performance(league, grades_games, grades_props)
    write_board(data_root() / "published" / f"performance_{league}.json", perf)
    return {"dates": len(index), "graded_games": len(grades_games), "graded_thresholds": len(grades_props)}


def _prob_block(d: pd.DataFrame) -> dict:
    p = np.clip(d["p"].to_numpy(float), 1e-4, 1 - 1e-4)
    y = d["y"].to_numpy(float)
    return {"n": int(len(d)), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
            "avg_predicted": round(float(p.mean()), 3), "hit_rate": round(float(y.mean()), 3)}


def _calibration(d: pd.DataFrame) -> list[dict]:
    edges = np.linspace(0, 1, 11)
    b = pd.cut(d["p"], edges, include_lowest=True)
    return [{"bin": f"{iv.left:.1f}-{iv.right:.1f}", "n": int(len(g)), "predicted": round(float(g["p"].mean()), 3), "actual": round(float(g["y"].mean()), 3)}
            for iv, g in d.groupby(b, observed=True)]


def performance(league: str, games: list[dict], props: list[dict]) -> dict:
    out = {"league": league, "kind": "performance", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": "Graded from projections recorded before each game (prediction ledger). Small samples are noisy; see n."}
    g = pd.DataFrame(games)
    if len(g):
        out["games"] = {"n": int(len(g)), "margin_mae": round(float(g["margin_err"].mean()), 2), "total_mae": round(float(g["total_err"].mean()), 2),
                        "winner_correct": round(float(g["correct"].dropna().mean()), 3) if g["correct"].notna().any() else None,
                        "win_prob": _prob_block(g), "by_date": [{"date": d, **_prob_block(x), "margin_mae": round(float(x["margin_err"].mean()), 2)}
                                                               for d, x in g.groupby("date")]}
    p = pd.DataFrame(props)
    if len(p):
        top = p.groupby("player_id").size().sort_values(ascending=False).head(60).index
        out["props"] = {
            "overall": _prob_block(p), "calibration": _calibration(p),
            "by_market": {k: _prob_block(x) for k, x in p.groupby("market")},
            "by_date": [{"date": d, **_prob_block(x)} for d, x in p.groupby("date")],
            "by_player": sorted([{"player": x["player"].iloc[0], **_prob_block(x)} for pid, x in p[p["player_id"].isin(top)].groupby("player_id")],
                                key=lambda r: -r["n"]),
        }
    return out


def run() -> dict:
    return {lg: build(lg) for lg in ("nfl", "nba")}
