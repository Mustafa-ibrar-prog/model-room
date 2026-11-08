"""NBA 0.2.0 vs 0.2.1 vs 0.2.2(a) on IDENTICAL player-game-markets with the historical-report replay.
Breakdowns use definitions common to every version: actual starter (box score), role by prior minutes, and the number
of rotation teammates (15+ min over their last 10 games) listed Out/Doubtful on the report the model had.
Usage: analyze_hist.py out.json tag1 tag2 ..."""
import json, sys
import numpy as np, pandas as pd
outp, tags = sys.argv[1], sys.argv[2:]
D = "/home/claude/model-room/modeling/data/output/nba/audit/"
key = ["game_id", "player_id", "market"]
T = {t: pd.read_pickle(f"{D}rows_2025_2026_{t}.pkl") for t in tags}
for t in T: T[t]["game_id"] = T[t]["game_id"].astype(str); T[t]["player_id"] = T[t]["player_id"].astype(str)
common = None
for t, d in T.items():
    k = d[key]
    common = k if common is None else common.merge(k, on=key)
# only games that had a report (the replay's scope)
av = pd.read_pickle("/tmp/claude-0/s/audit/hist_av.pkl")
games_with = {g for (g, _t) in av}
common = common[common.game_id.isin(games_with)]
T = {t: d.merge(common, on=key) for t, d in T.items()}
from modelroom.nba.props import inputs as I
inp = I.load(); pg = inp.player_games.copy(); pg["pid"] = pg.player_id.astype(str); pg["gid"] = pg.game_id.astype(str)
pg = pg.sort_values("game_date")
pg["m10"] = pg[pg.played].groupby("pid")["minutes"].transform(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
pg["m10"] = pg.groupby("pid")["m10"].ffill()
lastm = pg.dropna(subset=["m10"])
starter = {(r.gid, r.pid): bool(r.starter) for r in pg.itertuples()}
m10 = {(r.gid, r.pid): r.m10 for r in lastm.itertuples()}
team_of = {(r.gid, r.pid): r.team for r in pg.itertuples()}
# rotation players listed Out/Doubtful per (game, team): use the player's latest prior m10
lm = lastm[["pid", "game_date", "m10"]].copy(); lm["game_date"] = pd.to_datetime(lm.game_date).astype("datetime64[ns]")
gdate = {str(r.game_id): pd.Timestamp(r.game_date) for r in inp.games.itertuples()}
rows = []
for (g, team), a in av.items():
    for pid, x in a["players"].items():
        if x["status"] in ("out", "doubtful"):
            rows.append({"gid": g, "team": team, "pid": pid, "date": gdate.get(g)})
O = pd.DataFrame(rows).dropna(subset=["date"]); O["date"] = O.date.astype("datetime64[ns]")
O = pd.merge_asof(O.sort_values("date"), lm.sort_values("game_date").rename(columns={"game_date": "date"}), on="date", by="pid", allow_exact_matches=False)
nout = O[O.m10 >= 15].groupby(["gid", "team"]).size().to_dict()
rows = []
for (g, team), a in av.items():
    for pid, x in a["players"].items():
        if x["status"] in ("questionable", "probable", "available"):
            rows.append({"gid": g, "team": team, "pid": pid, "date": gdate.get(g)})
Uq = pd.DataFrame(rows).dropna(subset=["date"]); Uq["date"] = Uq.date.astype("datetime64[ns]")
Uq = pd.merge_asof(Uq.sort_values("date"), lm.sort_values("game_date").rename(columns={"game_date": "date"}), on="date", by="pid", allow_exact_matches=False)
Uq = Uq[Uq.m10 >= 12]
unc_list = Uq.groupby(["gid", "team"])["pid"].agg(set).to_dict()
status = {(g, pid): x["status"] for (g, _t), a in av.items() for pid, x in a["players"].items()}
eps = 1e-6
def ll(p, y): p = np.clip(p, eps, 1 - eps); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
def ece(p, y, b=10):
    i = np.clip((p * b).astype(int), 0, b - 1); return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))
def metrics(d):
    e = d["mean"] - d["actual"]
    o = {"n": int(len(d)), "mae": round(float(e.abs().mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3), "bias_pct": round(float(100 * e.mean() / max(d["actual"].mean(), 1e-9)), 2)}
    t = [(pp, yy) for L in d["ladder"] for (_, pp, yy) in L]
    if t:
        p, y = np.array(t).T; m = (p >= .02) & (p <= .98); p, y = p[m], y[m]
        o.update(ladder_ll=round(ll(p, y), 5), ladder_brier=round(float(np.mean((p - y) ** 2)), 5), ladder_ece=round(ece(p, y), 4))
    m = d.dropna(subset=["p_mline"])
    if len(m):
        p, y = m.p_mline.to_numpy(), m.y_mline.to_numpy()
        o.update(ou_ll=round(ll(p, y), 5), ou_brier=round(float(np.mean((p - y) ** 2)), 5), ou_ece=round(ece(p, y), 4), ou_pred_over=round(float(p.mean()), 4), ou_actual_over=round(float(y.mean()), 4))
    pm = d[d.market == "points"].dropna(subset=["act_min", "proj_min"])
    if len(pm):
        o.update(min_mae=round(float((pm.proj_min - pm.act_min).abs().mean()), 3), min_bias=round(float((pm.proj_min - pm.act_min).mean()), 3))
    return o
for t, d in T.items():
    k = list(zip(d.game_id, d.player_id))
    d["act_starter"] = [starter.get(x, False) for x in k]
    d["role"] = pd.cut(pd.Series([m10.get(x, np.nan) for x in k], index=d.index), [-1, 16, 24, 30, 60], labels=["<16", "16-24", "24-30", "30+"])
    d["n_out"] = [min(nout.get((g, team_of.get((g, p))), 0), 2) for g, p in k]
    d["n_out"] = d["n_out"].map({0: "0", 1: "1", 2: "2+"})
    d["status"] = [status.get(x) or "not listed" for x in k]
    d["n_uncertain"] = [min(len(unc_list.get((g, team_of.get((g, p))), set()) - {p}), 2) for g, p in k]
    d["n_uncertain"] = d["n_uncertain"].map({0: "0", 1: "1", 2: "2+"})
out = {"rows_per_version": int(len(common))}
for sname, sv in (("2024-25", [2025]), ("2025-26", [2026]), ("combined", [2025, 2026])):
    S = {t: d[d.season.isin(sv)] for t, d in T.items()}
    o = {"overall": {t: metrics(d) for t, d in S.items()}}
    for by in ("market", "act_starter", "role", "n_out", "n_uncertain", "status"):
        o["by_" + by] = {str(g): {t: metrics(S[t][S[t][by] == g]) for t in S} for g in sorted(S[tags[0]][by].dropna().unique(), key=str) if (S[tags[0]][by] == g).sum() >= 200}
    out[sname] = o
json.dump(out, open(outp, "w"), indent=1, default=str)
print(json.dumps({k: out[k]["overall"] for k in ("2024-25", "2025-26", "combined")}, indent=1))
