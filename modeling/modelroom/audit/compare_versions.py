"""Compare two audit row sets on IDENTICAL player-game-markets. Usage: analyze.py nba|nfl base_tag new_tag out.json"""
import json
import sys

import numpy as np
import pandas as pd

lg, a, b, outp = sys.argv[1:5]
D = f"data/output/{lg}/audit/"
seas = "2025_2026" if lg == "nba" else "2023_2024_2025"
A = pd.read_pickle(f"{D}rows_{seas}_{a}.pkl")
B = pd.read_pickle(f"{D}rows_{seas}_{b}.pkl")
key = ["game_id", "player_id", "market"]
common = A[key].merge(B[key], on=key)
A = A.merge(common, on=key)
B = B.merge(common, on=key)
eps = 1e-6


def ll(p, y):
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece(p, y, bins=10):
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    return float(sum((idx == k).mean() * abs(p[idx == k].mean() - y[idx == k].mean()) for k in range(bins) if (idx == k).any()))


def lad(d):
    t = [(pp, yy) for L in d["ladder"] for (_, pp, yy) in L]
    if not t:
        return None
    p, y = np.array(t).T
    m = (p >= 0.02) & (p <= 0.98)
    return p[m], y[m]


def metrics(d):
    e = d["mean"] - d["actual"]
    out = {"n": int(len(d)), "mae": round(float(e.abs().mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
           "bias_pct": round(float(100 * e.mean() / max(d["actual"].mean(), 1e-9)), 2), "median_ae": round(float((d["median"] - d["actual"]).abs().mean()), 3)}
    L = lad(d)
    if L is not None and len(L[0]):
        out.update(ladder_ll=round(ll(*L), 5), ladder_brier=round(float(np.mean((L[0] - L[1]) ** 2)), 5), ladder_ece=round(ece(*L), 4), ladder_n=int(len(L[0])))
    m = d.dropna(subset=["p_mline"])
    if len(m):
        p, y = m["p_mline"].to_numpy(), m["y_mline"].to_numpy()
        pick = p != 0.5
        out.update(ou_n=int(len(m)), ou_ll=round(ll(p, y), 5), ou_brier=round(float(np.mean((p - y) ** 2)), 5), ou_ece=round(ece(p, y), 4),
                   ou_acc=round(float(((p[pick] > 0.5) == (y[pick] == 1)).mean()), 4), ou_over_share=round(float((p > 0.5).mean()), 4),
                   ou_actual_over=round(float(y.mean()), 4), ou_pred_over=round(float(p.mean()), 4))
    return out


def compare(fa, fb, by=None):
    if by is None:
        return {a: metrics(fa), b: metrics(fb)}
    res = {}
    for k, ga in fa.groupby(by):
        gb = fb.merge(ga[key], on=key)
        if len(ga) >= 200:
            res[str(k)] = {a: metrics(ga), b: metrics(gb)}
    return res


# opponent strength (diagnostic bucket only): how much the opponent's players beat their own last-10 average, per season/market
def opp_bucket(d):
    x = d.dropna(subset=["l10"])
    r = x.groupby(["season", "opp", "market"]).apply(lambda g: g["actual"].sum() / max(g["l10"].sum(), 1e-9)).rename("allowed").reset_index()
    r["opp_tier"] = r.groupby(["season", "market"])["allowed"].transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=["tough", "average", "soft"]))
    return d.merge(r[["season", "opp", "market", "opp_tier"]], on=["season", "opp", "market"], how="left")


A = opp_bucket(A)
B = B.merge(A[key + ["opp_tier"]], on=key, how="left")
out = {"rows": int(len(A)), "overall": compare(A, B), "by_market": compare(A, B, "market"), "by_opp_tier": compare(A, B, "opp_tier")}
if lg == "nba":
    for c in ("starter", "teammates_out", "group"):
        out[f"by_{c}"] = compare(A, B, c)
    B2 = B.copy()
    if "returning" in B2:
        Bm = B2[B2["returning"] == True]  # noqa: E712
        Am = A.merge(Bm[key], on=key)
        out["returning_players"] = {a: metrics(Am), b: metrics(Bm)} if len(Bm) else None
    # minutes: error decomposition (points)
    for name, d in ((a, A), (b, B)):
        p = d[(d["market"] == "points")].dropna(subset=["act_min"])
        me = p["proj_min"] - p["act_min"]
        e = p["mean"] - p["actual"]
        beta = float(np.polyfit(me, e, 1)[0])
        r2 = float(np.corrcoef(me, e)[0, 1] ** 2)
        big = (p["act_min"] == 0) | (me.abs() > 8)
        out[f"minutes_{name}"] = {"n": int(len(p)), "minutes_mae": round(float(me.abs().mean()), 2), "minutes_bias": round(float(me.mean()), 2),
                                  "points_err_per_minute_err": round(beta, 3), "share_of_points_error_variance_from_minutes": round(r2, 3),
                                  "big_minutes_miss_share": round(float(big.mean()), 4),
                                  "points_mae_when_minutes_within_3": round(float(e[me.abs() <= 3].abs().mean()), 3),
                                  "points_mae_when_minutes_off_8plus": round(float(e[me.abs() > 8].abs().mean()), 3)}
else:
    out["by_group"] = compare(A, B, "group")
    qb = B.dropna(subset=["qb_career_att"]).drop_duplicates(["game_id", "team"])[["game_id", "team", "qb_career_att"]]
    for d in (A, B):
        pass
    A2 = A.merge(qb, on=["game_id", "team"], how="left", suffixes=("_x", ""))
    B2 = B.drop(columns=["qb_career_att"]).merge(qb, on=["game_id", "team"], how="left")
    A2["qb_exp"] = pd.cut(A2["qb_career_att"], [-1, 149, 499, 1e9], labels=["<150", "150-499", "500+"])
    B2["qb_exp"] = pd.cut(B2["qb_career_att"], [-1, 149, 499, 1e9], labels=["<150", "150-499", "500+"])
    out["by_qb_experience"] = compare(A2, B2, "qb_exp")
    # opportunity vs efficiency decomposition: receiving yards error explained by target error
    for name, d in ((a, A), (b, B)):
        r = d[(d["market"] == "receiving_yards")].dropna(subset=["act_tgt"])
        te = r["proj_tgt"] - r["act_tgt"]
        e = r["mean"] - r["actual"]
        out[f"opportunity_{name}"] = {"n": int(len(r)), "targets_mae": round(float(te.abs().mean()), 3), "targets_bias": round(float(te.mean()), 3),
                                      "share_of_rec_yards_error_variance_from_targets": round(float(np.corrcoef(te, e)[0, 1] ** 2), 3)}
        q = d[(d["market"] == "passing_yards")].dropna(subset=["act_att"])
        ae = q["proj_att"] - q["act_att"]
        out[f"qb_volume_{name}"] = {"n": int(len(q)), "attempts_mae": round(float(ae.abs().mean()), 2), "attempts_bias": round(float(ae.mean()), 2),
                                    "share_of_pass_yards_error_variance_from_attempts": round(float(np.corrcoef(ae, q["mean"] - q["actual"])[0, 1] ** 2), 3)}
        c = d[(d["market"] == "rushing_attempts") & d["group"].isin(["RB"])].dropna(subset=["act_car"])
        out[f"rb_carries_{name}"] = {"n": int(len(c)), "carries_mae": round(float((c["proj_car"] - c["act_car"]).abs().mean()), 2),
                                     "carries_bias": round(float((c["proj_car"] - c["act_car"]).mean()), 2)}
json.dump(out, open(outp, "w"), indent=1, default=str)
print(json.dumps(out["overall"], indent=1))
