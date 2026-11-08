"""Opponent strength from PRIOR games only (no hindsight): for each row, how much the opponent's previous opponents
beat their own last-10 averages, in this season, before this game. Then bias / calibration by tier.
Usage: opp_prior.py nba|nfl tag [tag2]"""
import json
import sys

import numpy as np
import pandas as pd

lg, tags = sys.argv[1], sys.argv[2:]
D = f"data/output/{lg}/audit/"
seas = "2025_2026" if lg == "nba" else "2023_2024_2025"
tcol = "date" if lg == "nba" else "week"
eps = 1e-6


def ll(L):
    t = np.array([(p, y) for l in L for (_, p, y) in l])
    if not len(t):
        return np.nan, np.nan, np.nan
    t = t[(t[:, 0] >= .02) & (t[:, 0] <= .98)]
    p = np.clip(t[:, 0], eps, 1 - eps)
    y = t[:, 1]
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), float(p.mean()), float(y.mean())


out = {}
base = None
for tag in tags:
    A = pd.read_pickle(f"{D}rows_{seas}_{tag}.pkl")
    if base is None:
        g = A.dropna(subset=["l10"]).groupby(["season", "opp", "market", tcol]).agg(act=("actual", "sum"), l10=("l10", "sum")).reset_index()
        g = g.sort_values(tcol)
        g["c_act"] = g.groupby(["season", "opp", "market"])["act"].cumsum() - g["act"]
        g["c_l10"] = g.groupby(["season", "opp", "market"])["l10"].cumsum() - g["l10"]
        g["n_prior"] = g.groupby(["season", "opp", "market"]).cumcount()
        g = g[g["n_prior"] >= (5 if lg == "nba" else 3)]
        g["allowed_prior"] = g["c_act"] / g["c_l10"].clip(lower=1e-9)
        g["tier"] = g.groupby(["season", "market", tcol])["allowed_prior"].transform(
            lambda s: pd.qcut(s.rank(method="first"), 3, labels=["tough", "average", "soft"]) if len(s) >= 3 else np.nan)
        base = g[["season", "opp", "market", tcol, "tier", "allowed_prior"]]
    A = A.merge(base, on=["season", "opp", "market", tcol], how="inner")
    res = {}
    for t, d in A.groupby("tier"):
        e = d["mean"] - d["actual"]
        l = ll(d["ladder"])
        res[str(t)] = {"n": int(len(d)), "bias_pct": round(float(100 * e.mean() / d["actual"].mean()), 2), "mae": round(float(e.abs().mean()), 3),
                       "ladder_ll": round(l[0], 5), "ladder_mean_p": round(l[1], 4), "ladder_hit": round(l[2], 4)}
    # residual slope: does the prior-allowed ratio still predict the error after the model's own matchup term?
    A["rel_err"] = (A["actual"] - A["mean"]) / A["mean"].clip(lower=0.5)
    sl = {}
    for mk, d in A.groupby("market"):
        x = np.log(d["allowed_prior"].clip(0.5, 2))
        sl[mk] = round(float(np.polyfit(x, d["rel_err"].clip(-3, 3), 1)[0]), 3)
    out[tag] = {"by_prior_tier": res, "residual_slope_on_log_allowed": sl}
print(json.dumps(out, indent=1))
json.dump(out, open(f"data/output/{lg}_opp_prior.json", "w"), indent=1)
