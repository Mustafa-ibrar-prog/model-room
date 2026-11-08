import json, numpy as np, pandas as pd
D = "/home/claude/model-room/modeling/data/output/nfl/audit/"
A = pd.read_pickle(D + "rows_2023_2024_2025_v011.pkl"); B = pd.read_pickle(D + "rows_2023_2024_2025_v012.pkl")
key = ["game_id", "player_id", "market"]
c = A[key].merge(B[key], on=key); A = A.merge(c, on=key); B = B.merge(c, on=key)
# role from the BASE projection (common to both): RB1 = most projected carries among the team's graded RBs
r = A[(A.market == "rushing_attempts") & (A.group == "RB")].copy()
r["role"] = np.where(r.groupby(["game_id", "team"])["proj_car"].rank(ascending=False, method="first") == 1, "RB1", "RB2+")
role = r.set_index(["game_id", "player_id"])["role"]
for d in (A, B):
    d["role"] = [role.get((g, p), d_g) for g, p, d_g in zip(d.game_id, d.player_id, d.group)]
eps = 1e-6
def ll(p, y): p = np.clip(p, eps, 1 - eps); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
def ece(p, y, b=10):
    i = np.clip((p * b).astype(int), 0, b - 1); return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))
def m(d):
    e = d["mean"] - d.actual
    o = {"n": int(len(d)), "mae": round(float(e.abs().mean()), 3), "bias_pct": round(float(100 * e.mean() / max(d.actual.mean(), 1e-9)), 2)}
    t = [(pp, yy) for L in d.ladder for (_, pp, yy) in L]
    if t:
        p, y = np.array(t).T; k = (p >= .02) & (p <= .98); p, y = p[k], y[k]
        o.update(ladder_ll=round(ll(p, y), 5), ladder_brier=round(float(np.mean((p - y) ** 2)), 5), ladder_ece=round(ece(p, y), 4))
    q = d.dropna(subset=["p_mline"])
    if len(q):
        p, y = q.p_mline.to_numpy(), q.y_mline.to_numpy()
        o.update(ou_ll=round(ll(p, y), 5), ou_brier=round(float(np.mean((p - y) ** 2)), 5), ou_ece=round(ece(p, y), 4), ou_pred_over=round(float(p.mean()), 4), ou_act_over=round(float(y.mean()), 4))
    return o
out = {}
mk = ["rushing_attempts", "rushing_yards", "rush_rec_yards", "anytime_td", "fantasy_points"]
for mkt in mk + ["receiving_yards", "receptions"]:
    for season in (2023, 2024, 2025, "all"):
        for rl in ("RB1", "RB2+", "all RBs", "all players"):
            fa = A[A.market == mkt]; fb = B[B.market == mkt]
            if season != "all": fa, fb = fa[fa.season == season], fb[fb.season == season]
            if rl == "all RBs": fa, fb = fa[fa.group == "RB"], fb[fb.group == "RB"]
            elif rl != "all players": fa, fb = fa[fa.role == rl], fb[fb.role == rl]
            if len(fa) >= 50:
                out[f"{mkt}|{season}|{rl}"] = {"0.1.1": m(fa), "0.1.2": m(fb)}
# carries accuracy
for season in (2023, 2024, 2025, "all"):
    for rl in ("RB1", "RB2+"):
        fa = A[(A.market == "rushing_attempts") & (A.role == rl)]; fb = B[(B.market == "rushing_attempts") & (B.role == rl)]
        if season != "all": fa, fb = fa[fa.season == season], fb[fb.season == season]
        out[f"carries|{season}|{rl}"] = {v: {"proj_car_mae": round(float((d.proj_car - d.act_car).abs().mean()), 3), "proj_car_bias_pct": round(float(100 * (d.proj_car.mean() / d.act_car.mean() - 1)), 2)} for v, d in (("0.1.1", fa), ("0.1.2", fb))}
# unaffected markets must be identical
same = {mkt: bool(np.allclose(A[A.market == mkt].sort_values(key)["mean"].to_numpy(), B[B.market == mkt].sort_values(key)["mean"].to_numpy())) for mkt in ("passing_yards", "receptions", "receiving_yards", "interceptions")}
out["unaffected_markets_identical"] = same
json.dump(out, open("/tmp/claude-0/s/audit/nfl_012_cmp.json", "w"), indent=1)
for k in [f"carries|{s}|{r}" for s in (2023, 2024, 2025, "all") for r in ("RB1", "RB2+")]:
    print(k, out[k])
print(same)
for k, v in out.items():
    if k.split("|")[0] in ("rushing_attempts", "rushing_yards") and not k.startswith("carries"):
        a, b = v["0.1.1"], v["0.1.2"]
        print(f"{k:38s} n={a['n']:5d} mae {a['mae']:.3f}->{b['mae']:.3f} bias {a['bias_pct']:+.1f}->{b['bias_pct']:+.1f} | LL {a.get('ladder_ll',0):.4f}->{b.get('ladder_ll',0):.4f} ECE {a.get('ladder_ece',0):.3f}->{b.get('ladder_ece',0):.3f} | ouLL {a.get('ou_ll',0):.4f}->{b.get('ou_ll',0):.4f} ouECE {a.get('ou_ece',0):.3f}->{b.get('ou_ece',0):.3f}")
