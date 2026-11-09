"""Market metrics split by position for the recommended candidate (CNsel) vs 0.1.1, walk-forward, calibration either
refit on training seasons (pooled positions, as the engine does) or kept from 0.1.1's fit."""
import json, numpy as np, pandas as pd, sys
sys.argv = ["x", "none"]
exec(open("experiment.py").read().split("CFGS = {")[0].split("NAMES = ")[0])
res = {}
for S in (2023, 2024, 2025):
    tr, te = R[R.season < S], R[R.season == S]
    prm = fit(tr, frozenset({"CNsel"}))
    o_te, o_tr = apply(te, frozenset({"CNsel"}), prm), apply(tr, frozenset({"CNsel"}), prm)
    rat = lambda o: o.assign(rt=o.n_tgt / o.proj_tgt.clip(lower=0.05), rc=o.n_car / o.proj_car.clip(lower=0.05))[["game_id", "player_id", "rt", "rc"]]
    for mk in ("receptions", "receiving_yards", "rushing_attempts", "rushing_yards"):
        Atr = AUDR[(AUDR.season < S) & (AUDR.market == mk)].merge(rat(o_tr), on=["game_id", "player_id"], how="left")
        Ate = AUDR[(AUDR.season == S) & (AUDR.market == mk)].merge(rat(o_te), on=["game_id", "player_id"], how="left")
        col = "rt" if mk.startswith("rec") else "rc"
        lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
        Atr["one"] = 1.0; Ate["one"] = 1.0
        cal = {}
        for c in ("one", col):
            p, _ = market_probs(Atr, c)
            cal[c] = fit_logit(np.c_[np.ones(len(Atr)), lg(p)], Atr.y_mline.to_numpy().astype(float), l2=1e-6)
        for g in ("RB", "WR", "TE"):
            d = Ate[Ate.group == g]
            if len(d) < 100:
                continue
            y = d.y_mline.to_numpy().astype(float); out = {"n": int(len(d))}
            for lab, c, cb in (("base", "one", "one"), ("cand_refit", col, col), ("cand_keepcal", col, "one")):
                p, mu = market_probs(d, c); b = cal[cb]
                pc = 1 / (1 + np.exp(-(b[0] + b[1] * lg(p))))
                out[lab] = {"ll": round(ll(pc, y), 4), "brier": round(float(np.mean((pc - y) ** 2)), 4), "ece": round(ece(pc, y), 4),
                            "mae": round(float((mu - d.actual).abs().mean()), 3), "bias_pct": round(float(100 * (mu.mean() / d.actual.mean() - 1)), 1)}
            res[f"{S}|{mk}|{g}"] = out
json.dump(res, open(H / "by_group_markets.json", "w"), indent=1)
for k, v in res.items():
    print(k, v["n"], "LL", v["base"]["ll"], v["cand_refit"]["ll"], v["cand_keepcal"]["ll"], "ECE", v["base"]["ece"], v["cand_refit"]["ece"], v["cand_keepcal"]["ece"], "bias", v["base"]["bias_pct"], v["cand_refit"]["bias_pct"], "MAE", v["base"]["mae"], v["cand_refit"]["mae"])
