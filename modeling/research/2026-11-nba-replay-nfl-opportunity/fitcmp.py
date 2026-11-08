import json, sys, numpy as np, pandas as pd
D = "/home/claude/model-room/modeling/data/output/nba/audit/"
season_tag, tags = sys.argv[1], sys.argv[2:]
T = {t: pd.read_pickle(f"{D}rows_{season_tag}_{t}.pkl") for t in tags}
key = ["game_id", "player_id", "market"]
c = None
for d in T.values():
    d["game_id"] = d.game_id.astype(str); d["player_id"] = d.player_id.astype(str)
    c = d[key] if c is None else c.merge(d[key], on=key)
T = {t: d.merge(c, on=key) for t, d in T.items()}
eps = 1e-6
def ll(p, y): p = np.clip(p, eps, 1 - eps); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
def ece(p, y, b=10):
    i = np.clip((p * b).astype(int), 0, b - 1); return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))
def met(d):
    e = d["mean"] - d.actual
    t = np.array([(pp, yy) for L in d.ladder for (_, pp, yy) in L]); k = (t[:, 0] >= .02) & (t[:, 0] <= .98)
    q = d.dropna(subset=["p_mline"]); pm = d[d.market == "points"].dropna(subset=["act_min"])
    return {"n": len(d), "min_mae": round(float((pm.proj_min - pm.act_min).abs().mean()), 3), "min_bias": round(float((pm.proj_min - pm.act_min).mean()), 3),
            "stat_mae": round(float(e.abs().mean()), 3), "bias_pct": round(float(100 * e.mean() / d.actual.mean()), 2),
            "ladder_ll": round(ll(t[k, 0], t[k, 1]), 5), "ladder_brier": round(float(np.mean((t[k, 0] - t[k, 1]) ** 2)), 5), "ladder_ece": round(ece(t[k, 0], t[k, 1]), 4),
            "ou_ll": round(ll(q.p_mline.to_numpy(), q.y_mline.to_numpy()), 5), "ou_ece": round(ece(q.p_mline.to_numpy(), q.y_mline.to_numpy()), 4),
            "pred_over": round(float(q.p_mline.mean()), 4), "act_over": round(float(q.y_mline.mean()), 4)}
out = {t: met(d) for t, d in T.items()}
print(pd.DataFrame(out).to_string())
json.dump(out, open(f"/tmp/claude-0/s/audit/fitcmp_{season_tag}.json", "w"), indent=1)
