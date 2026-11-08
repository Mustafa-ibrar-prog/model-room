import pandas as pd, numpy as np
from modelroom.nba.props import inputs as I
inp = I.load(); pg = inp.player_games.copy()
av = pd.read_pickle("/tmp/claude-0/s/audit/hist_av.pkl")
pg["pid"] = pg.player_id.astype(str); pg["game_date"] = pd.to_datetime(pg["game_date"])
tg = pg.drop_duplicates(["game_id", "team"])[["game_id", "team", "game_date", "season"]].sort_values("game_date")
tg["k"] = tg.groupby(["season", "team"]).cumcount()
kmap = {(str(r.game_id), r.team): (r.k, r.season, r.game_date) for r in tg.itertuples()}
gp = pg[pg.played].merge(tg[["game_id", "team", "k"]], on=["game_id", "team"])
rows = []
by_team = {k: d for k, d in gp.groupby(["season", "team"])}
for (gid, team), a in av.items():
    if (gid, team) not in kmap or not a["submitted"]:
        continue
    k, season, date = kmap[(gid, team)]
    h = by_team.get((season, team))
    if h is None: continue
    h = h[h.k < k]
    if h.empty: continue
    last = h.groupby("pid").agg(lastk=("k", "max"), lastd=("game_date", "max"))
    mw = h.sort_values("k").groupby("pid")["minutes"].apply(lambda s: s.tail(10).mean())
    last["mwp"] = mw; last["miss"] = k - 1 - last["lastk"]
    c = last[(last.miss >= 3) & (last.mwp >= 12) & ((date - last.lastd).dt.days <= 60)]
    for pid, x in c.iterrows():
        rows.append({"season": season, "listed": a["players"].get(pid, {}).get("status"), "miss": x.miss, "mwp": x.mwp,
                     "played": bool(((pg.game_id.astype(str) == gid) & (pg.pid == pid) & pg.played).any())})
D = pd.DataFrame(rows)
D["listed"] = D["listed"].fillna("NOT LISTED")
print(D.groupby(["season", "listed"]).played.agg(["size", "mean"]).round(3).to_string())
