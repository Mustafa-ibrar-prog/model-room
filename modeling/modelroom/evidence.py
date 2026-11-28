"""Evidence for the AI analysis (TEST, Moose 2026-11-28).

Builds data/published/evidence_{nba,nfl}.json from data the refresh has ALREADY collected (no new sources, no API calls):

  defense    per opponent, per position group and stat: average allowed per game this season and its league rank
             (1 = allows the most), with the number of games behind it
  players    for every player on the props board: last 15 played games (values, minutes / snaps, home or away, date),
             season averages and spread, home / away splits (only when each side has at least MIN_SPLIT games)
  weather    NFL only: the stored NWS GFS MOS wind forecast for open-air games (preview-ledger/nfl_weather_week_*),
             plus roof type from the schedule

Every section carries its source and as-of time. Nothing here is a model input or changes a prediction; it's read by
the site's evidence pack for Gemini, which may only quote it. Box scores: hoopR / ESPN (NBA), nflverse (NFL).
Run by the TEST refresh after the props boards (python -m modelroom.evidence).
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEDGER = ROOT / "preview-ledger"
MIN_SPLIT = 5          # games on each side before a home / away split is shown
MIN_DEF_GAMES = 6      # opponent games before a defensive rank is shown
LAST_N = 15

NBA_STATS = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m", "pra": "pra", "steals": "stl", "blocks": "blk"}
NBA_OPP = {"minutes": "minutes", "fga": "fga", "fg3a": "fg3a", "fta": "fta"}
NFL_STATS = {"passing_yards": "pass_yds", "passing_attempts": "pass_att", "passing_completions": "pass_cmp", "passing_tds": "pass_td",
             "interceptions": "ints", "rushing_yards": "rush_yds", "rushing_attempts": "carries", "receiving_yards": "rec_yds",
             "receptions": "receptions", "rush_rec_yards": "rush_rec_yds", "anytime_td": "td_any", "longest_reception": "long_rec",
             "fantasy_points": "fantasy_ppr"}
NFL_OPP = {"snaps": "offense_snaps", "snap_pct": "offense_pct", "targets": "targets", "carries": "carries", "pass_att": "pass_att"}
NFL_GROUPS = ("QB", "RB", "WR", "TE")


def r1(x) -> float | None:
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 1)


def defense(pg: pd.DataFrame, stats: dict[str, str], group_col: str, groups, team_col: str, opp_col: str, relevant=None) -> dict:
    """Allowed per game by opponent, position group and stat, ranked within the league (1 = allows the most)."""
    out: dict[str, dict] = {}
    teams = sorted(pg[opp_col].dropna().unique())
    for grp in groups:
        sub = pg[pg[group_col] == grp]
        per_game = sub.groupby([opp_col, "game_id"])[list(stats.values())].sum()
        g = per_game.groupby(level=0)
        avg, n = g.mean(), g.size()
        for key, col in stats.items():
            if relevant and grp not in relevant.get(key, (grp,)):
                continue
            s = avg[col].reindex(teams)
            ok = n.reindex(teams).fillna(0) >= MIN_DEF_GAMES
            ranked = s[ok].rank(ascending=False, method="min")
            lg = float(s[ok].mean()) if ok.any() else None
            for t in teams:
                if not ok.get(t, False):
                    continue
                out.setdefault(t, {}).setdefault(grp, {})[key] = {"allowed": r1(s[t]), "rank": int(ranked[t]), "of": int(ok.sum()),
                                                                  "league_avg": r1(lg), "games": int(n.get(t, 0))}
    return out


def player_block(h: pd.DataFrame, stats: dict[str, str], opp: dict[str, str], home_col: str) -> dict:
    h = h.sort_values("game_date", ascending=False)
    last = h.head(LAST_N)
    games = [{"date": str(r["game_date"])[:10], "opp": r["opp"], "home": bool(r[home_col]),
              **{k: r1(r[c]) for k, c in opp.items() if c in r}} for _, r in last.iterrows()]
    vals = {k: [r1(v) for v in last[c].tolist()] for k, c in stats.items() if c in last}
    season = {k: {"avg": r1(h[c].mean()), "sd": r1(h[c].std(ddof=0)) if len(h) > 1 else None} for k, c in stats.items() if c in h}
    splits = {}
    hm, aw = h[h[home_col].astype(bool)], h[~h[home_col].astype(bool)]
    if len(hm) >= MIN_SPLIT and len(aw) >= MIN_SPLIT:
        splits = {"home_games": len(hm), "away_games": len(aw),
                  **{k: {"home": r1(hm[c].mean()), "away": r1(aw[c].mean())} for k, c in stats.items() if c in h}}
    usage = {k: {"last5": r1(last.head(5)[c].mean()), "season": r1(h[c].mean())} for k, c in opp.items() if c in h}
    return {"games": games, "values": vals, "season_games": int(len(h)), "season": season, "splits": splits or None, "usage": usage}


def build_nba(board: dict) -> dict:
    pg = pd.read_parquet(DATA / "processed" / "nba" / "prop_player_games.parquet")
    season = int(board["season"])
    pg = pg[(pg["season"] == season) & pg["played"].astype(bool)].copy()
    pg["player_id"] = pg["player_id"].astype(str)
    pg["game_date"] = pd.to_datetime(pg["game_date"])
    through = str(pg["game_date"].max().date()) if len(pg) else None
    want = {str(p["player_id"]) for g in board["games"] for p in g["players"]}
    players = {pid: player_block(h, NBA_STATS, NBA_OPP, "is_home") for pid, h in pg[pg["player_id"].isin(want)].groupby("player_id")}
    return {"league": "nba", "season": season, "results_through": through,
            "sources": {"box_scores": "hoopR / sportsdataverse (ESPN)", "defense": "derived from the same box scores"},
            "defense_groups": ["G", "F", "C"],
            "defense": defense(pg, NBA_STATS, "group", ("G", "F", "C"), "team", "opp"), "players": players}


def build_nfl(board: dict) -> dict:
    pg = pd.read_parquet(DATA / "processed" / "nfl" / "player_games.parquet")
    season = int(board["season"])
    pg = pg[(pg["season"] == season) & (pg["season_type"] == "REG")].copy()
    pg["player_id"] = pg["player_id"].astype(str)
    pg["game_date"] = pd.to_datetime(pg["game_date"])
    pg["rush_rec_yds"] = pg["rush_yds"].fillna(0) + pg["rec_yds"].fillna(0)
    pg["td_any"] = pg["rush_td"].fillna(0) + pg["rec_td"].fillna(0)
    pg["is_home"] = pg["team"] == pg["home_team"]
    played = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].fillna(0).sum(axis=1) > 0)]
    through = str(played["game_date"].max().date()) if len(played) else None
    want = {str(p["player_id"]) for g in board["games"] for p in g["players"]}
    mk = {str(p["player_id"]): set(p["markets"]) for g in board["games"] for p in g["players"]}
    players = {pid: player_block(h, {k: c for k, c in NFL_STATS.items() if k in mk.get(pid, ())}, NFL_OPP, "is_home")
               for pid, h in played[played["player_id"].isin(want)].groupby("player_id")}
    weather = nfl_weather(board)
    return {"league": "nfl", "season": season, "results_through": through,
            "sources": {"box_scores": "nflverse", "defense": "derived from the same box scores", "weather": "NWS GFS MOS (Iowa Environmental Mesonet)"},
            "defense_groups": list(NFL_GROUPS),
            "defense": defense(played, NFL_STATS, "position", NFL_GROUPS, "team", "opp", relevant=_nfl_positions()), "players": players, "weather": weather}


def _nfl_positions() -> dict[str, tuple]:
    from modelroom.nfl.props.config import MARKETS
    return {k: tuple(v["positions"]) for k, v in MARKETS.items()}


def nfl_weather(board: dict) -> dict:
    """Latest stored wind forecast per upcoming game (open-air games only), with its issue time; roof from the schedule."""
    sched = DATA / "processed" / "nfl" / "games.parquet"
    roof = {}
    if sched.exists():
        s = pd.read_parquet(sched, columns=["game_id", "roof"])
        roof = dict(zip(s["game_id"].astype(str), s["roof"].astype(str)))
    latest: dict[str, dict] = {}
    for f in sorted(glob.glob(str(LEDGER / "nfl_weather_week_*.jsonl"))):
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            gid = r.get("nfl_game_id")
            if gid and (gid not in latest or r.get("issued_at", "") >= latest[gid].get("issued_at", "")):
                latest[gid] = r
    out = {}
    for g in board["games"]:
        gid = str(g["game_id"])
        rf = roof.get(gid)
        w = latest.get(gid)
        rf = rf if rf and rf not in ("None", "nan") else None
        entry: dict = {"roof": rf}
        if w and rf not in ("dome", "closed"):
            start = pd.Timestamp(g["start_time"])
            near = [x for x in w.get("rows", []) if abs((pd.Timestamp(x["valid"]) - start).total_seconds()) <= 3 * 3600 and x.get("wind_kt") is not None]
            if near:
                kt = max(float(x["wind_kt"]) for x in near)
                entry.update({"wind_mph": r1(kt * 1.15078), "forecast_issued": w.get("issued_at"), "source": "NWS GFS MOS"})
        out[gid] = entry
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="modelroom evidence")
    ap.add_argument("--league", default="nba,nfl")
    a = ap.parse_args(argv)
    done = {}
    for lg in a.league.split(","):
        bf = DATA / "published" / f"{lg}_props.json"
        if not bf.exists():
            continue
        board = json.loads(bf.read_text())
        ev = build_nba(board) if lg == "nba" else build_nfl(board)
        ev["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ev["board_generated_at"] = board.get("generated_at")
        (DATA / "published" / f"evidence_{lg}.json").write_text(dumps(ev))
        done[lg] = {"players": len(ev["players"]), "defense_teams": len(ev["defense"]), "results_through": ev["results_through"]}
    print(json.dumps(done))
    return 0


def sanitize(x):
    """NaN / inf -> None, numpy -> Python, recursively (the site reads strict JSON)."""
    if isinstance(x, dict):
        return {str(k): sanitize(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [sanitize(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def dumps(ev: dict) -> str:
    return json.dumps(sanitize(ev), separators=(",", ":"), allow_nan=False, default=_clean)


def _clean(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return str(x)


if __name__ == "__main__":
    raise SystemExit(main())
