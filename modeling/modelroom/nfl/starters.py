"""Projected starting quarterback for every NFL team-game, from information available before kickoff.

    python -m modelroom nfl starters        (also built by `nfl ingest`)

Why: the schedule's QB field (nflverse games.csv) is the ACTUAL starter for past games, which is look-ahead
in a backtest, and for coming games it is filled from the previous week's starter. A starter returning
from injury, a benching or a fresh injury is then missed.

Rule, as of the game's kickoff, using only what was published before it:
  1. Candidates: QBs on the team's weekly roster for that week (the latest published week for coming games)
     with status ACT or INA (game-day inactives are not used: they are announced ~90 minutes before kickoff),
     minus anyone the injury report lists as Out or Doubtful for that week.
  2. Depth chart: the candidate ranked highest at QB. From 2025, ESPN snapshots are timestamped and the last
     one before kickoff is used (live projections always use these).
     Through 2024 there is only an undated weekly chart; where it disagrees with the team's previous starter
     and that QB is still a candidate, the previous starter is used (the weekly charts lag: in 2018-24 the
     previous starter was right in 155 of the 244 disagreements, the chart in 83).
  3. No ranked candidate: the QB who threw the most passes in the team's previous game, if still a candidate.
  4. Otherwise the candidate with the most pass attempts over the team's last 8 games.
Each row records which step decided it.

Writes data/processed/nfl/starters.parquet:
  game_id, team, side, qb_id, qb_name, source, listed_qb_id, listed_qb_name, actual_qb_id
"""
from __future__ import annotations

import bisect

import numpy as np
import pandas as pd

from modelroom.common.paths import processed_dir, raw_dir

from . import ingest, player_data

ELIGIBLE = {"ACT", "INA"}
EXCLUDE_REPORT = {"Out", "Doubtful"}
FIRST_SEASON = 2018


def _depth(seasons: list[int]):
    """Weekly ranks (season, week) → {gsis: rank}, and timestamped snapshots: sorted dts + {dt: {gsis: rank}}."""
    weekly: dict = {}
    snaps: dict = {}
    for s in seasons:
        f = raw_dir("nfl") / f"depth_charts_{s}.parquet"
        if not f.exists():
            continue
        d = pd.read_parquet(f)
        if "dt" in d.columns:
            q = d[(d["pos_abb"] == "QB") & d["gsis_id"].notna()]
            q = q.assign(rank=pd.to_numeric(q["pos_rank"], errors="coerce")).dropna(subset=["rank"])
            for dt, x in q.groupby("dt"):
                snaps[pd.Timestamp(dt)] = x.groupby("gsis_id")["rank"].min().to_dict()
        else:
            q = d[(d["position"] == "QB") & (d.get("formation", "Offense") == "Offense") & d["gsis_id"].notna()]
            q = q.assign(rank=pd.to_numeric(q["depth_team"], errors="coerce")).dropna(subset=["rank", "week"])
            for (season, week), x in q.groupby(["season", "week"]):
                weekly[(int(season), int(week))] = x.groupby("gsis_id")["rank"].min().to_dict()
    times = sorted(snaps)
    return weekly, times, snaps


def build(games: pd.DataFrame | None = None) -> pd.DataFrame:
    games = games if games is not None else pd.read_parquet(processed_dir("nfl") / "games.parquet")
    games = games[games["season"] >= FIRST_SEASON].copy()
    seasons = sorted(games["season"].unique().tolist())
    ro = player_data.rosters(seasons)
    ro = ro[ro["position"] == "QB"]
    names = ro.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")["full_name"].to_dict()
    roster_weeks = {k: x for k, x in ro.groupby(["season", "team"])}
    from .props import inputs as PI

    inj = PI.injuries()
    out_ids = {(int(r.season), int(r.week), r.gsis_id) for r in inj.itertuples() if r.report_status in EXCLUDE_REPORT and pd.notna(r.week)}
    pg, _, _ = player_data.load()
    qbp = pg[pg["pass_att"].fillna(0) > 0][["game_id", "team", "player_id", "pass_att", "game_date"]].copy()
    qbp["date"] = pd.to_datetime(qbp["game_date"])
    actual = qbp.sort_values("pass_att").drop_duplicates(["game_id", "team"], keep="last").set_index(["game_id", "team"])["player_id"].to_dict()
    team_games = {t: x.sort_values("date") for t, x in qbp.groupby("team")}
    weekly, times, snaps = _depth(seasons)

    rows = []
    for g in games.itertuples():
        kick = pd.Timestamp(g.start_time) if pd.notna(g.start_time) else pd.Timestamp(g.game_date, tz="UTC")
        if kick.tzinfo is None:
            kick = kick.tz_localize("UTC")
        for side, team, listed_id, listed_name in (("home", g.home_team, g.home_qb_id, g.home_qb_name), ("away", g.away_team, g.away_qb_id, g.away_qb_name)):
            r = roster_weeks.get((g.season, team))
            cands: list[str] = []
            if r is not None and len(r):
                weeks = r["week"].dropna()
                wk = weeks[weeks <= g.week].max() if (weeks <= g.week).any() else weeks.max()
                cur = r[(r["week"] == wk) & r["status"].isin(ELIGIBLE)]
                cands = [x for x in cur["gsis_id"].unique() if (int(g.season), int(g.week), x) not in out_ids]
            qb, source = None, None
            depth_qb = last_qb = None
            timestamped = False
            if cands:
                ranks = None
                if times:
                    i = bisect.bisect_left(times, kick) - 1
                    if i >= 0 and (kick - times[i]).days <= 10:
                        ranks, timestamped = snaps[times[i]], True
                if ranks is None:
                    ranks = weekly.get((int(g.season), int(g.week)))
                if ranks:
                    ranked = sorted((ranks[c], c) for c in cands if c in ranks)
                    if ranked:
                        qb, source = ranked[0][1], "depth chart"
                        depth_qb = qb
                tg = team_games.get(team)
                if tg is not None:
                    before = tg[tg["date"] < kick.tz_convert(None).normalize()]
                    if len(before):
                        last_gid = before["game_id"].iloc[-1]
                        last = before[before["game_id"] == last_gid].sort_values("pass_att")["player_id"].iloc[-1]
                        last_qb = last if last in cands else None
                        if last_qb and not timestamped and ranks and qb != last_qb:
                            # Undated weekly charts lag; when one disagrees with last week's (still available)
                            # starter, the starter was right far more often (2018-24: 155 vs 83 games).
                            qb, source = last_qb, "last start (weekly chart disagreed)"
                        if qb is None:
                            if last in cands:
                                qb, source = last, "last start"
                            else:
                                recent_ids = before["game_id"].drop_duplicates().iloc[-8:]
                                vol = before[before["game_id"].isin(recent_ids) & before["player_id"].isin(cands)].groupby("player_id")["pass_att"].sum()
                                if len(vol):
                                    qb, source = vol.idxmax(), "recent volume"
            rows.append({"game_id": g.game_id, "team": team, "side": side, "qb_id": qb, "qb_name": names.get(qb) if qb else None,
                         "source": source or "none", "depth_qb_id": depth_qb, "last_start_qb_id": last_qb, "listed_qb_id": None if pd.isna(listed_id) else listed_id,
                         "listed_qb_name": None if pd.isna(listed_name) else listed_name,
                         "actual_qb_id": actual.get((g.game_id, team)), "status": g.status, "season": g.season, "week": g.week})
    out = pd.DataFrame(rows)
    out.to_parquet(processed_dir("nfl") / "starters.parquet", index=False)
    return out


def load() -> pd.DataFrame | None:
    f = processed_dir("nfl") / "starters.parquet"
    return pd.read_parquet(f) if f.exists() else None


def apply(games: pd.DataFrame, mode: str = "projected") -> pd.DataFrame:
    """Replace the schedule's QB columns.

    projected  the pre-game projected starter (this module's rule)
    previous   the QB who started the team's previous game (what the schedule field holds for coming games)
    """
    st = load()
    if st is None:
        return games
    if mode == "previous":
        st = st.sort_values(["team", "season", "week"]).copy()
        st["qb_id"] = st.groupby("team")["actual_qb_id"].shift(1)
        names = st.dropna(subset=["qb_name"]).drop_duplicates("qb_id").set_index("qb_id")["qb_name"]
        st["qb_name"] = st["qb_id"].map(names)
    g = games.copy()
    for side in ("home", "away"):
        s = st[st["side"] == side].set_index("game_id")
        pid, pname = g["game_id"].map(s["qb_id"]), g["game_id"].map(s["qb_name"])
        g[f"{side}_qb_id_listed"] = g[f"{side}_qb_id"]
        g[f"{side}_qb_id"] = pid.where(pid.notna(), g[f"{side}_qb_id"])
        g[f"{side}_qb_name"] = pname.where(pid.notna(), g[f"{side}_qb_name"])
    return g


def summary(st: pd.DataFrame) -> dict:
    past = st[(st["status"] == "final") & st["actual_qb_id"].notna()]
    out = {"team_games": int(len(st)), "by_source": st["source"].value_counts().to_dict()}
    if len(past):
        out["past"] = {
            "n": int(len(past)),
            "projected_matches_actual": round(float((past["qb_id"] == past["actual_qb_id"]).mean()), 4),
            "schedule_field_matches_actual": round(float((past["listed_qb_id"] == past["actual_qb_id"]).mean()), 4),
            "by_season": {int(s): round(float((x["qb_id"] == x["actual_qb_id"]).mean()), 4) for s, x in past.groupby("season")},
            "by_source": {k: {"n": int(len(x)), "correct": round(float((x["qb_id"] == x["actual_qb_id"]).mean()), 4)} for k, x in past.groupby("source")},
        }
        prev = past.sort_values(["team", "season", "week"])
        prev = prev.assign(prev_actual=prev.groupby("team")["actual_qb_id"].shift(1))
        out["past"]["previous_starter_matches_actual"] = round(float((prev["prev_actual"] == prev["actual_qb_id"]).mean()), 4)
    up = st[st["status"] == "scheduled"]
    if len(up):
        diff = up[up["listed_qb_id"].notna() & (up["qb_id"] != up["listed_qb_id"])]
        out["upcoming"] = {"n": int(len(up)), "differs_from_schedule": [
            {"game_id": r.game_id, "team": r.team, "schedule": r.listed_qb_name, "projected": r.qb_name, "source": r.source} for r in diff.itertuples()]}
    return out
