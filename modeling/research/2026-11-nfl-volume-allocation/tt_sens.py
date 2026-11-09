"""(1) Coaching tendency: team-level RB concentration (lead back's share of RB carries over the team's previous 8 games)
as a modifier of the RB carry concentration exponent. (2) Sensitivity of results to the exponent. Walk-forward."""
import json, numpy as np, pandas as pd, sys
sys.argv = ["x", "none"]
src = open("experiment.py").read()
exec(src.split("CFGS = {")[0].split("NAMES = ")[0])
from modelroom.nfl.props import inputs as I
pg = I.load(set(range(2019, 2026))).player_games
rb = pg[pg.position.isin(["RB", "FB"]) if "position" in pg else pg.group.eq("RB")]
g = rb.groupby(["game_id", "team"]).agg(top=("carries", "max"), tot=("carries", "sum"), gd=("game_date", "first")).reset_index()
g = g[g.tot > 0].assign(conc=lambda d: d.top / d.tot).sort_values("gd")
g["conc8"] = g.groupby("team").conc.transform(lambda s: s.shift(1).rolling(8, min_periods=3).mean())
R2 = R.merge(g[["game_id", "team", "conc8"]], on=["game_id", "team"], how="left")
R2["cz"] = (R2.conc8 - R2.conc8.mean()).fillna(0.0)
def shares_tt(d, gam, delta):
    r = d.c_raw.copy(); rb = d.group == "RB"
    G = r.groupby(d.gkey).transform("sum")
    e = np.where(rb, gam + delta * d.cz * 10, 1.0)  # delta per 0.1 of concentration
    r2 = r.clip(lower=1e-5) ** e
    r2 = r2 * G / r2.groupby(d.gkey).transform("sum")
    return r2 * d.c_scale
res = {}
for S in (2023, 2024, 2025):
    tr, te = R2[(R2.season < S)], R2[R2.season == S]
    m = tr.played & (tr.group == "RB")
    best = None
    for gam in np.linspace(1.0, 1.5, 11):
        for delta in (-0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2):
            e = float(((shares_tt(tr, gam, delta)[m] - tr.a_csh[m]) ** 2).mean())
            if best is None or e < best[0]:
                best = (e, gam, delta)
    mt = te.played & (te.group == "RB")
    out = {"fitted_gamma": round(best[1], 3), "fitted_delta_per_0.1_conc": best[2]}
    for lab, gam, delta in (("base", 1.0, 0.0), ("CN_fit", None, 0.0), ("CN+TT_fit", best[1], best[2]), ("g1.10", 1.1, 0.0), ("g1.20", 1.2, 0.0), ("g1.30", 1.3, 0.0), ("g1.40", 1.4, 0.0)):
        if lab == "CN_fit":
            bb = min(((float(((shares_tt(tr, gg, 0)[m] - tr.a_csh[m]) ** 2).mean()), gg) for gg in np.linspace(1.0, 1.5, 11)))
            gam = bb[1]; out["CN_only_gamma"] = round(gam, 3)
        s_ = shares_tt(te, gam, delta)[mt]; y = te.a_csh[mt]; tp = te.team_carries[mt]
        rk = te[mt].groupby("gkey").c_share.rank(ascending=False, method="first")
        o = {"share_mae_pp": round(float((s_ - y).abs().mean() * 100), 3), "share_rmse_pp": round(float(np.sqrt(((s_ - y) ** 2).mean()) * 100), 3),
             "bias_pct": round(float(100 * (s_.sum() / y.sum() - 1)), 1)}
        for k in (1, 2, 3):
            mm = (rk == k).to_numpy()
            o[f"RB{k}_bias_pct"] = round(float(100 * (s_[mm].sum() / y[mm].sum() - 1)), 1)
        out[lab] = o
    res[str(S)] = out
json.dump(res, open(H / "tt_sens.json", "w"), indent=1)
print(json.dumps(res, indent=1))
