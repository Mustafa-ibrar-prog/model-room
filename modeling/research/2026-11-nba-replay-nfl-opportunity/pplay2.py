import pandas as pd, numpy as np
from modelroom.nba.props import inputs as I
inp = I.load(); pg = inp.player_games.copy()
av = pd.read_pickle("/tmp/claude-0/s/audit/hist_av.pkl")
pg["game_date"] = pd.to_datetime(pg["game_date"]); pg = pg.sort_values("game_date")
pg["pid"] = pg.player_id.astype(str)
# prior-only role: mean minutes over his last 10 appearances, games missed in a row (team games), season-to-date
gp = pg[pg.played].copy()
gp["mwp10"] = gp.groupby("pid")["minutes"].transform(lambda s: s.rolling(10, min_periods=1).mean())
last = gp[["pid", "game_date", "mwp10"]].assign(game_date=lambda d: d.game_date.astype("datetime64[ns]"))
rows = []
season = {str(r.game_id): (r.season, pd.Timestamp(r.game_date)) for r in inp.games.itertuples()}
for (gid, team), a in av.items():
    for pid, x in a["players"].items():
        if x["status"] in ("available", "probable", "questionable"):
            rows.append({"gid": gid, "pid": pid, "status": x["status"], "season": season[gid][0], "date": season[gid][1]})
D = pd.DataFrame(rows); D["date"] = D["date"].astype("datetime64[ns]"); D = D.sort_values("date")
D = pd.merge_asof(D, last.sort_values("game_date").rename(columns={"game_date": "date"}), on="date", by="pid", allow_exact_matches=False)
pl = {(str(r.game_id), str(r.player_id)): bool(r.played) for r in pg.itertuples()}
D["played"] = [pl.get((g, p), False) for g, p in zip(D.gid, D.pid)]
D["role"] = pd.cut(D.mwp10.fillna(0), [-1, 0.01, 8, 16, 24, 60], labels=["none", "<8", "8-16", "16-24", "24+"])
print(D.groupby(["status", "role"]).played.agg(["size", "mean"]).round(3).to_string())
print(D.groupby(["season", "status", "role"]).played.agg(["size", "mean"]).round(3).unstack("season").to_string())
D.to_pickle("/tmp/claude-0/s/audit/pplay_rows.pkl")
