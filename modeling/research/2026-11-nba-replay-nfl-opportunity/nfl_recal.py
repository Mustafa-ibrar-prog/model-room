"""NFL 0.1.2 vs 0.1.1 with calibration refitted on the tune seasons (2021-22) for BOTH, same procedure
(propeval.fit_calibration, p' = σ(a + b·logit p), on the ladder probabilities). Raw probabilities are recovered by
inverting the calibration that was applied in the audit (0.1.1's, which 0.1.2's params copy). Test 2023-25."""
import json, sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/model-room/modeling")
from modelroom.common.propeval import fit_calibration
D = "/home/claude/model-room/modeling/data/output/nfl/audit/"
CAL = json.load(open("/home/claude/model-room/modeling/modelroom/nfl/props/params_0.1.1.json"))["calibration"]
def raw(p, mkt):
    a, b = CAL.get(mkt, [0.0, 1.0]); p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    z = (np.log(p / (1 - p)) - a) / b; return 1 / (1 + np.exp(-z))
def cal(p, ab):
    a, b = ab; p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); return 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))
MK = ["rushing_attempts", "rushing_yards", "rush_rec_yards", "anytime_td", "fantasy_points"]
def tune_rows(tag):
    T = pd.read_pickle(D + f"rows_2021_2022_{tag}.pkl"); T = T[T.market.isin(MK)]
    t = pd.DataFrame([(m, raw(pp, m), yy) for m, L in zip(T.market, T.ladder) for (_, pp, yy) in L], columns=["market", "p", "y"])
    return fit_calibration(t)
calA, calB = tune_rows("v011_fit"), tune_rows("v012_fit")
print("refit calibration 0.1.1:", calA); print("refit calibration 0.1.2:", calB)
A = pd.read_pickle(D + "rows_2023_2024_2025_v011.pkl"); B = pd.read_pickle(D + "rows_2023_2024_2025_v012.pkl")
key = ["game_id", "player_id", "market"]
c = A[key].merge(B[key], on=key); A = A.merge(c, on=key); B = B.merge(c, on=key)
r = A[(A.market == "rushing_attempts") & (A.group == "RB")].copy()
r["role"] = np.where(r.groupby(["game_id", "team"])["proj_car"].rank(ascending=False, method="first") == 1, "RB1", "RB2+")
role = r.set_index(["game_id", "player_id"])["role"]
for d in (A, B): d["role"] = [role.get((g, p), gr) for g, p, gr in zip(d.game_id, d.player_id, d.group)]
eps = 1e-6
def ll(p, y): p = np.clip(p, eps, 1 - eps); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
def ece(p, y, b=10):
    i = np.clip((p * b).astype(int), 0, b - 1); return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))
def met(d, calmap):
    e = d["mean"] - d.actual; mk = d.market.iloc[0]
    o = {"n": int(len(d)), "mae": round(float(e.abs().mean()), 3), "bias_pct": round(float(100 * e.mean() / max(d.actual.mean(), 1e-9)), 2)}
    t = np.array([(pp, yy) for L in d.ladder for (_, pp, yy) in L])
    p = raw(t[:, 0], mk) if calmap is not None else t[:, 0]
    if calmap is not None: p = cal(p, calmap[mk])
    y = t[:, 1]; k = (p >= .02) & (p <= .98)
    o.update(ladder_ll=round(ll(p[k], y[k]), 5), ladder_brier=round(float(np.mean((p[k] - y[k]) ** 2)), 5), ladder_ece=round(ece(p[k], y[k]), 4))
    q = d.dropna(subset=["p_mline"])
    pq = q.p_mline.to_numpy() if calmap is None else cal(raw(q.p_mline.to_numpy(), mk), calmap[mk]); yq = q.y_mline.to_numpy()
    o.update(ou_ll=round(ll(pq, yq), 5), ou_brier=round(float(np.mean((pq - yq) ** 2)), 5), ou_ece=round(ece(pq, yq), 4), ou_pred_over=round(float(pq.mean()), 4), ou_act_over=round(float(yq.mean()), 4))
    return o
out = {"calibration_0.1.1_refit": calA, "calibration_0.1.2_refit": calB}
V = (("0.1.1 active", A, None), ("0.1.1 recal", A, calA), ("0.1.2 recal", B, calB))
for mkt in MK:
    for season in (2023, 2024, 2025, "all"):
        for rl in ("RB1", "RB2+", "all RBs", "all players"):
            row = {}
            for name, d, cm in V:
                f = d[d.market == mkt]
                if season != "all": f = f[f.season == season]
                if rl == "all RBs": f = f[f.group == "RB"]
                elif rl != "all players": f = f[f.role == rl]
                if len(f) < 50: break
                row[name] = met(f, cm)
            if len(row) == 3: out[f"{mkt}|{season}|{rl}"] = row
json.dump(out, open("/tmp/claude-0/s/audit/nfl_recal.json", "w"), indent=1)
for k, v in out.items():
    if "|" not in k or k.split("|")[0] not in ("rushing_attempts", "rushing_yards"): continue
    s = f"{k:36s} n={v['0.1.1 active']['n']:5d} "
    for f in ("bias_pct", "ladder_ll", "ladder_ece", "ou_ll", "ou_ece"):
        s += f"| {f} " + " ".join(f"{v[n][f]:.4f}" if f != "bias_pct" else f"{v[n][f]:+.1f}" for n in ("0.1.1 active", "0.1.1 recal", "0.1.2 recal")) + " "
    print(s)
