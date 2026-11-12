"""Recent form for the props board: each player's last games and this season's averages, for display only.

Only games before the board's cutoff are used (they are already in the past). This runs after every projection and
ledger record is written and only adds a "recent" block to the published board, so it never changes a projection.

player["recent"] = {
  "games":  [{date, opp, season, <opportunity per game>}, ...]      newest first, up to N_GAMES played games
  "values": {market: [v, ...]}                                       the market's stat in those games
  "season": {season, games, avg: {market: v}, opportunity: {...}}   regular-season games this season, or null
  "opportunity": [{key, label}]                                      which opportunity fields the games carry
}
Opportunity (minutes, attempts, snaps, targets...) is kept apart from the stat values so a reader never mixes a
per-game result with the chance a player had to produce it.
"""
from __future__ import annotations

import pandas as pd

N_GAMES = 10


def _num(v) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v), 1)


def attach(games_json: list[dict], pg: pd.DataFrame, stat_of: dict[str, str], cutoff: pd.Timestamp, played: pd.Series | None = None,
           *, season: int | None = None, regular: pd.Series | None = None, opportunity: dict[str, str] | None = None) -> None:
    """Adds player["recent"] (see module doc). `regular` marks regular-season rows (for the season average);
    `opportunity` maps a column to its label, e.g. {"minutes": "Minutes"}."""
    want = {str(p["player_id"]) for g in games_json for p in g["players"]}
    if not want:
        return
    opportunity = {c: lab for c, lab in (opportunity or {}).items() if c in pg.columns}
    pid = pg["player_id"].astype(str)
    d = pg[pid.isin(want)].copy()
    if played is not None:
        d = d[played.loc[d.index].astype(bool)]
    dates = pd.to_datetime(d["game_date"])
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    cut = cutoff.tz_localize(None) if cutoff.tzinfo else cutoff
    d = d[dates < cut]
    d = d.sort_values("game_date", ascending=False)
    d["_pid"] = d["player_id"].astype(str)
    last = d.groupby("_pid").head(N_GAMES)
    by_player = {k: x for k, x in last.groupby("_pid")}
    seas = d
    if season is not None and "season" in d.columns:
        seas = d[d["season"].astype(int) == int(season)]
        if regular is not None:
            seas = seas[regular.loc[seas.index].astype(bool)]
    by_season = {k: x for k, x in seas.groupby("_pid")} if season is not None else {}
    opp_keys = [{"key": c, "label": lab} for c, lab in opportunity.items()]
    for g in games_json:
        for p in g["players"]:
            k = str(p["player_id"])
            x = by_player.get(k)
            if x is None or x.empty:
                continue
            vals = {}
            for mkey in p["markets"]:
                col = stat_of.get(mkey)
                if col and col in x.columns:
                    vals[mkey] = [_num(v) for v in x[col]]
            games = []
            for _, r in x.iterrows():
                row = {"date": str(r["game_date"])[:10], "opp": r["opp"]}
                if "season" in x.columns and not pd.isna(r["season"]):
                    row["season"] = int(r["season"])
                for c in opportunity:
                    row[c] = _num(r[c])
                games.append(row)
            block = {"games": games, "values": vals, "opportunity": opp_keys, "season": None}
            s = by_season.get(k)
            if season is not None:
                if s is None or s.empty:
                    block["season"] = {"season": int(season), "games": 0, "avg": {}, "opportunity": {}}
                else:
                    avg = {}
                    for mkey in p["markets"]:
                        col = stat_of.get(mkey)
                        if col and col in s.columns and s[col].notna().any():
                            avg[mkey] = round(float(s[col].mean()), 2)
                    block["season"] = {"season": int(season), "games": int(len(s)), "avg": avg,
                                       "opportunity": {c: round(float(s[c].mean()), 2) for c in opportunity if s[c].notna().any()}}
            p["recent"] = block
