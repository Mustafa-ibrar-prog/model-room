"""Depth-chart rank of each skill player (RB / WR / TE) as of a cutoff, for opportunity redistribution.

  through 2024  nflverse weekly depth charts (one chart per team-week, released before the games)
  2025 on       ESPN depth-chart snapshots via nflverse, timestamped: the last snapshot before the cutoff

Returns {gsis_id: rank} (1 = first on the chart at his position). Players missing from the chart get no
rank; the model then orders them by their usage. Three-receiver sets list several WRs at rank 1; the model
breaks ties by usage.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from modelroom.common.paths import raw_dir

SKILL = {"RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}


@lru_cache(maxsize=16)
def _season(season: int) -> pd.DataFrame | None:
    f = raw_dir("nfl") / f"depth_charts_{season}.parquet"
    if not f.exists():
        return None
    d = pd.read_parquet(f)
    if "dt" in d.columns:
        d = d[d["pos_abb"].isin(list(SKILL)) & d["gsis_id"].notna()]
        return pd.DataFrame({"dt": pd.to_datetime(d["dt"], utc=True), "gsis_id": d["gsis_id"],
                             "rank": pd.to_numeric(d["pos_rank"], errors="coerce")}).dropna(subset=["rank"])
    d = d[d["position"].isin(list(SKILL)) & (d.get("formation", "Offense") == "Offense") & d["gsis_id"].notna()]
    return pd.DataFrame({"week": pd.to_numeric(d["week"], errors="coerce"), "gsis_id": d["gsis_id"],
                         "rank": pd.to_numeric(d["depth_team"], errors="coerce")}).dropna(subset=["rank", "week"])


def ranks(season: int, week: int, cutoff) -> dict:
    d = _season(int(season))
    if d is None or d.empty:
        return {}
    if "dt" in d.columns:
        cut = pd.Timestamp(cutoff)
        cut = cut.tz_localize("UTC") if cut.tzinfo is None else cut.tz_convert("UTC")
        x = d[(d["dt"] < cut) & (d["dt"] >= cut - pd.Timedelta(days=14))]
        if x.empty:
            return {}
        x = x[x["dt"] == x["dt"].max()]
    else:
        x = d[d["week"] == week]
        if x.empty:  # chart not published for this week yet: the latest earlier week
            x = d[d["week"] < week]
            if x.empty:
                return {}
            x = x[x["week"] == x["week"].max()]
    return x.groupby("gsis_id")["rank"].min().astype(float).to_dict()


@lru_cache(maxsize=4)
def _history_cached(key: tuple) -> pd.DataFrame:
    rows = []
    for season, week, first_date in key:
        r = ranks(season, week, pd.Timestamp(first_date))
        rows += [(season, week, g, v) for g, v in r.items()]
    return pd.DataFrame(rows, columns=["season", "week", "player_id", "depth"])


def history(pg: pd.DataFrame) -> pd.DataFrame:
    """Depth rank of every player-week in `pg` (season, week, player_id, depth), as of before that week's
    first game: the chart the player held when those games were played."""
    wk = pg.groupby(["season", "week"])["game_date"].min().reset_index()
    key = tuple((int(s), int(w), str(d)) for s, w, d in wk.itertuples(index=False))
    return _history_cached(key)
