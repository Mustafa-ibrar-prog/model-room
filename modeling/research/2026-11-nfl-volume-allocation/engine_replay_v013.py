"""In-engine replay: NFL props 0.1.3 vs 0.1.1 on identical player-games and markets (props_audit rows, 1,500 sims,
same seeds). 2023-25 test seasons; calibration either as shipped (0.1.3 keeps 0.1.1's) or refit on 2021-22 for BOTH
with propeval.fit_calibration on raw ladder probabilities (raw recovered by inverting 0.1.1's calibration)."""
import json, numpy as np, pandas as pd
from pathlib import Path
from modelroom.common.propeval import fit_calibration
D = "/home/claude/model-room/modeling/data/output/nfl/audit/"
CAL = json.load(open("/home/claude/model-room/modeling/modelroom/nfl/props/params_0.1.1.json"))["calibration"]
def raw(p, mkt):
    a, b = CAL.get(mkt, [0.0, 1.0]); p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return 1 / (1 + np.exp(-((np.log(p / (1 - p)) - a) / b)))
def cal(p, ab):
    a, b = ab; p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); return 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))
def ll(p, y): p = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
def ece(p, y, b=10):
    i = np.clip((p * b).astype(int), 0, b - 1); return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))
def refit(tag):
    T = pd.read_pickle(D + f"rows_2021_2022_{tag}.pkl")
    t = pd.DataFrame([(m, raw(pp, m), yy) for m, L in zip(T.market, T.ladder) for (_, pp, yy) in L], columns=["market", "p", "y"])
    return fit_calibration(t)
A = pd.read_pickle(D + "rows_2023_2024_2025_v011.pkl"); B = pd.read_pickle(D + "rows_2023_2024_2025_v013.pkl")
key = ["game_id", "player_id", "market"]
common = A[key].merge(B[key], on=key)
out = {"rows": {"0.1.1": len(A), "0.1.3": len(B), "common": len(common)}}
A = A.merge(common, on=key); B = B.merge(common, on=key)
calA, calB = refit("v011_fit"), refit("v013_fit")
# roles from 0.1.1's projection (same groups for both versions)
role = {}
for mk, st in (("rushing_attempts", "RB"), ("receptions", "TE")):
    r = A[(A.market == mk) & (A.group == st)].copy()
    r["rk"] = r.groupby(["game_id", "team"])["mean"].rank(ascending=False, method="first")
    for g, p, k in zip(r.game_id, r.player_id, r.rk):
        role[(g, p, st)] = f"{st}{int(min(k, 3))}"
for d in (A, B):
    d["role"] = [role.get((g, p, gr), gr) for g, p, gr in zip(d.game_id, d.player_id, d.group)]
def met(d, mk, cmap):
    e = d["mean"] - d.actual
    o = {"n": int(len(d)), "mae": round(float(e.abs().mean()), 3), "bias_pct": round(float(100 * e.mean() / max(d.actual.mean(), 1e-9)), 2)}
    t = np.array([(pp, yy) for L in d.ladder for (_, pp, yy) in L])
    p = t[:, 0] if cmap is None else cal(raw(t[:, 0], mk), cmap[mk]); y = t[:, 1]; k = (p >= .02) & (p <= .98)
    o.update(ladder_ll=round(ll(p[k], y[k]), 5), ladder_brier=round(float(np.mean((p[k] - y[k]) ** 2)), 5), ladder_ece=round(ece(p[k], y[k]), 4))
    q = d.dropna(subset=["p_mline"])
    if len(q):
        pq = q.p_mline.to_numpy() if cmap is None else cal(raw(q.p_mline.to_numpy(), mk), cmap[mk]); yq = q.y_mline.to_numpy().astype(float)
        o.update(ou_ll=round(ll(pq, yq), 5), ou_ece=round(ece(pq, yq), 4))
    return o
V = (("0.1.1", A, None), ("0.1.3", B, None), ("0.1.1 refit", A, calA), ("0.1.3 refit", B, calB))
res = {}
for mk in sorted(A.market.unique()):
    for season in (2023, 2024, 2025):
        for grp in ("all", "QB", "WR", "TE", "RB", "RB1", "RB2", "RB3", "TE1", "TE2", "TE3"):
            row = {}
            for name, d, cm in V:
                f = d[(d.market == mk) & (d.season == season)]
                if grp != "all":
                    f = f[f.group == grp] if len(grp) == 2 else f[f.role == grp]
                if len(f) < 40:
                    break
                row[name] = met(f, mk, cm)
            if len(row) == 4:
                res[f"{mk}|{season}|{grp}"] = row
out["results"] = res
# identity check: WR/QB means and probabilities, same seeds -> differences are simulation noise only (shared draws)
for grp in ("WR", "QB"):
    a = A[A.group == grp].set_index(key)["mean"]; b = B[B.group == grp].set_index(key)["mean"]
    out[f"{grp}_mean_diff"] = {"mean": round(float((b - a).mean()), 4), "mean_abs": round(float((b - a).abs().mean()), 4)}
json.dump(out, open(Path(__file__).with_name("engine_replay_v013.json"), "w"), indent=1)
print(json.dumps(out["rows"]), out["WR_mean_diff"], out["QB_mean_diff"])
