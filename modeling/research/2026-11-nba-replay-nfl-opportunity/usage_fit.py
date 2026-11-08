"""Stage 1 offline fit (2023-24 only): refit the freed-usage rule from the recorded ingredients.
For a candidate rule (absence fade half-life h in games, denominator weighted/unweighted, boost b) each row's
usage factor uf' replaces the recorded uf: points/threes scale with uf'/uf, assists with sqrt, PRA = pts'+reb+ast'.
Score = squared error of points and assists means vs actual, plus |bias| by freed bucket (reported)."""
import json, sys, itertools, numpy as np, pandas as pd
D = "/home/claude/model-room/modeling/data/output/nba/audit/"
A = pd.read_pickle(D + "rows_2024_v022a_fit.pkl")
A = A[A.usage_parts.notna()].copy()
key = ["game_id", "player_id"]
W = A.pivot_table(index=key, columns="market", values="mean", aggfunc="first")
Y = A.pivot_table(index=key, columns="market", values="actual", aggfunc="first")
P = A.drop_duplicates(key).set_index(key)[["usage_parts", "usage_f_mean"]]
W, Y = W.loc[P.index], Y.loc[P.index]
def freed_of(parts, h, denom, fresh_k, nonrot):
    out = 0.0
    for (U, a, w, k, st) in parts["out"]:
        kk = 0.0 if k < 0 else k
        if fresh_k is not None and kk > fresh_k:
            continue
        g = 0.5 ** (kk / h) if h else 1.0
        out += U * a * w * g
    T = parts["T_w"] if denom == "weighted" else parts["T_u"]
    return out / (T + out) if T + out > 0 else 0.0
cur_b = 0.5
res = []
pts_act, ast_act = Y["points"].to_numpy(), Y["assists"].to_numpy()
uf0 = P.usage_f_mean.to_numpy()
grid = []
for h in (20.0, 10.0, 5.0, 3.0, 2.0, 1.0):
    for denom in ("weighted", "unweighted"):
        fr = np.array([freed_of(p, h, denom, None, True) for p in P.usage_parts])
        for b in np.round(np.arange(0.0, 0.81, 0.05), 2):
            uf = 1 + b * fr
            r = uf / uf0
            pts = W["points"].to_numpy() * r; ast = W["assists"].to_numpy() * np.sqrt(r)
            e_p = pts - pts_act; e_a = ast - ast_act
            grid.append({"h": h, "denom": denom, "b": float(b), "mean_freed": round(float(fr.mean()), 4),
                         "pts_mse": float((e_p ** 2).mean()), "ast_mse": float((e_a ** 2).mean()),
                         "pts_bias_pct": round(float(100 * e_p.mean() / pts_act.mean()), 2), "ast_bias_pct": round(float(100 * e_a.mean() / ast_act.mean()), 2),
                         "_fr": fr})
G = pd.DataFrame(grid)
G["score"] = G.pts_mse / G.pts_mse.min() + G.ast_mse / G.ast_mse.min()
best = G.sort_values("score").head(12).drop(columns="_fr")
print(best.to_string())
cur = G[(G.h == 20.0) & (G.denom == "weighted") & (G.b == 0.5)].drop(columns="_fr")
print("current rule:\n", cur.to_string())
nob = G[(G.b == 0.0)].drop(columns="_fr").head(1); print("no boost:\n", nob.to_string())
# bias by freed bucket for current vs best
bst = G.sort_values("score").iloc[0]
def buckets(fr, b):
    r = (1 + b * fr) / uf0; pts = W["points"].to_numpy() * r
    cut = pd.cut(pd.Series(G.iloc[0]._fr * 0 + fr), [-0.01, 0.02, 0.08, 0.15, 0.25, 1])
    df = pd.DataFrame({"c": cut, "p": pts, "y": pts_act})
    return df.groupby("c", observed=True).apply(lambda d: round(float(100 * (d.p.mean() / d.y.mean() - 1)), 2)).to_dict()
print("bias by freed bucket, current:", buckets(cur.iloc[0:1].index.map(lambda i: 0).size and G.loc[cur.index[0], "_fr"], 0.5))
print("bias by freed bucket, best   :", buckets(bst._fr, bst.b))
json.dump({"best": best.to_dict("records"), "current": cur.to_dict("records")}, open("/tmp/claude-0/s/audit/usage_fit.json", "w"), indent=1, default=float)
