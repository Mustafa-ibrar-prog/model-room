import sys, json, pandas as pd
sys.path.insert(0, ".")
from pathlib import Path
from modelroom.nba.props import inputs as I
from modelroom.audit import hist_reports as H
inp = I.load()
P = Path("/tmp/claude-0/s/probe")
av, st = H.build(inp, [P / "hist", P / "hist2", P / "hist3"])
print(st)
pg = inp.player_games
pl = {(str(r.game_id), str(r.player_id)): bool(r.played) for r in pg.itertuples()}
season = {str(r.game_id): r.season for r in inp.games.itertuples()}
rows = []
for (gid, team), a in av.items():
    for pid, x in a["players"].items():
        rows.append({"season": season.get(gid), "status": x["status"], "played": pl.get((gid, pid), False), "in_box": (gid, pid) in pl, "restr": x["restriction"]})
D = pd.DataFrame(rows)
print(D.groupby(["season", "status"]).agg(n=("played", "size"), p_play=("played", "mean"), in_box=("in_box", "mean")).round(3))
print(D[D.status.isin(["available", "probable"])].groupby(["season", "restr"]).played.agg(["size", "mean"]).round(3))
pd.to_pickle(av, "/tmp/claude-0/s/audit/hist_av.pkl")
