"""Recent form for the props board: each player's last few games for every market's stat.

Only games before the board's cutoff are used (they are already in the past), so this adds context for
the reader and never changes a projection.
"""
from __future__ import annotations

import pandas as pd

N_GAMES = 5


def attach(games_json: list[dict], pg: pd.DataFrame, stat_of: dict[str, str], cutoff: pd.Timestamp, played: pd.Series | None = None) -> None:
    """Adds player["recent"] = {"games": [{date, opp}], "values": {market: [v, ...]}} (newest first)."""
    want = {p["player_id"] for g in games_json for p in g["players"]}
    if not want:
        return
    d = pg[pg["player_id"].astype(str).isin(want)].copy()
    if played is not None:
        d = d[played.loc[d.index]]
    dates = pd.to_datetime(d["game_date"])
    d = d[dates.dt.tz_localize(None) < cutoff.tz_localize(None) if cutoff.tzinfo else dates < cutoff]
    d = d.sort_values("game_date", ascending=False).groupby(d["player_id"].astype(str)).head(N_GAMES)
    by_player = {pid: x for pid, x in d.groupby(d["player_id"].astype(str))}
    for g in games_json:
        for p in g["players"]:
            x = by_player.get(str(p["player_id"]))
            if x is None or x.empty:
                continue
            vals = {}
            for mkey in p["markets"]:
                col = stat_of.get(mkey)
                if col and col in x.columns:
                    vals[mkey] = [None if pd.isna(v) else round(float(v), 1) for v in x[col]]
            p["recent"] = {"games": [{"date": str(r.game_date)[:10], "opp": r.opp} for r in x.itertuples()], "values": vals}
