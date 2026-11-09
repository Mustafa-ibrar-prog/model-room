import json, numpy as np, pandas as pd
from common import H
T = pd.read_pickle(H / "data/test_rows.pkl")
E = json.load(open(H / "experiment.json"))
T["team_pa_"] = T.a_tgt / T.a_tsh.replace(0, np.nan); T["team_ru_"] = T.a_car / T.a_csh.replace(0, np.nan)
T["team_pa_"] = T.groupby(["game_id", "team"]).team_pa_.transform("max"); T["team_ru_"] = T.groupby(["game_id", "team"]).team_ru_.transform("max")
P = T[T.played].copy()
b = P[P.cfg == "base_0.1.1"]
# fixed role groups: rank by base projection within team-game-position (same players in every config)
b = b.assign(rk_t=b.groupby(["game_id", "team", "group"]).proj_tgt.rank(ascending=False, method="first"),
             rk_c=b.groupby(["game_id", "team", "group"]).proj_car.rank(ascending=False, method="first"))
P = P.merge(b[["game_id", "player_id", "rk_t", "rk_c"]], on=["game_id", "player_id"])
pct = lambda a, c: round(float(100 * (a / c - 1)), 1)
def slices(d):
    out = {}
    for g in ("RB", "WR", "TE"):
        x = d[d.group == g]
        out[f"{g} targets"] = (x.n_tgt, x.a_tgt)
        out[f"{g} target share (team att. known)"] = (x.n_tsh * x.team_pa_, x.a_tgt)
        if g == "RB":
            out["RB carries"] = (x.n_car, x.a_car)
            out["RB carry share (team att. known)"] = (x.n_csh * x.team_ru_, x.a_car)
        for k in (1, 2, 3):
            y = x[x.rk_t == k]; out[f"{g}{k} targets"] = (y.n_tgt, y.a_tgt)
            if g == "RB":
                y = x[x.rk_c == k]; out[f"RB{k} carries"] = (y.n_car, y.a_car)
    return out
rows = []
for (cfg, s), d in P.groupby(["cfg", "season"]):
    for k, (p, a) in slices(d).items():
        rows.append({"cfg": cfg, "season": s, "slice": k, "n": len(a), "bias": pct(p.sum(), a.sum()), "mae": round(float((p - a).abs().mean()), 3)})
    for k, (p, a) in slices(d).items():
        pass
Z = pd.DataFrame(rows)
Z.to_csv(H / "slices.csv", index=False)
order = ["base_0.1.1", "CNsel", "CN", "DP", "AV", "AV+CN", "AV+DP", "FI", "AV+FI+RC", "AV+FI+CN+DP"]
for sl in ["RB carries", "RB1 carries", "RB2 carries", "RB3 carries", "RB targets", "WR targets", "WR1 targets", "WR2 targets", "WR3 targets", "TE targets", "TE1 targets", "TE2 targets", "TE3 targets"]:
    z = Z[Z.slice == sl].pivot(index="cfg", columns="season", values=["bias", "mae"]).reindex(order)
    print("==", sl, "n", Z[(Z.slice == sl) & (Z.cfg == "base_0.1.1")].n.tolist())
    print(z.to_string())
M = []
for k, v in E["markets"].items():
    s, cfg = k.split("|")
    for mk, r in v.items():
        M.append({"season": int(s), "cfg": cfg, "market": mk, **r})
M = pd.DataFrame(M); M.to_csv(H / "markets.csv", index=False)
for mk in ("receptions", "receiving_yards", "rushing_attempts", "rushing_yards"):
    z = M[M.market == mk].pivot(index="cfg", columns="season", values=["ll", "ece", "mae"]).reindex(order)
    print("== market", mk, "n", M[(M.market == mk) & (M.cfg == "base_0.1.1")].n.tolist()); print(z.round(4).to_string())
