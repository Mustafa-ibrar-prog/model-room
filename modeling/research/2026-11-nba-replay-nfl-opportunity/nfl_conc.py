"""Target concentration test: within each team-game, reshape projected targets s_i ∝ s_i^gamma (team total kept),
optionally plus a level scale. gamma fitted walk-forward on prior seasons (grid), tested on 2024 / 2025."""
import json, numpy as np, pandas as pd
D = "/home/claude/model-room/modeling/data/"
A = pd.read_pickle(D + "output/nfl/audit/rows_2023_2024_2025_v011.pkl")
R = A[A.market == "receptions"].dropna(subset=["act_tgt"])[["season", "game_id", "player_id", "group", "team", "proj_tgt", "act_tgt"]].copy()
R["grank"] = R.groupby(["game_id", "team", "group"])["proj_tgt"].rank(ascending=False, method="first")
R["grole"] = R["group"] + R["grank"].clip(upper=3).astype(int).astype(str).replace({"3": "3+"})
tot = R.groupby(["game_id", "team"])["proj_tgt"].transform("sum")
def reshape(d, gm):
    w = d.proj_tgt.clip(lower=0.01) ** gm
    return w / w.groupby([d.game_id, d.team]).transform("sum") * d.groupby(["game_id", "team"])["proj_tgt"].transform("sum")
grid = np.round(np.arange(0.9, 1.41, 0.02), 2)
out = {}
for test in (2024, 2025):
    tr, te = R[R.season < test], R[R.season == test]
    best = min(grid, key=lambda gm: float((reshape(tr, gm) - tr.act_tgt).abs().mean()))
    bestr = min(grid, key=lambda gm: float(((reshape(tr, gm) - tr.act_tgt) ** 2).mean()))
    row = {"gamma_mae_fit": float(best), "gamma_rmse_fit": float(bestr)}
    for name, gm in (("base", 1.0), ("gamma", bestr)):
        p = reshape(te, gm); e = p - te.act_tgt
        row[name] = {"mae": round(float(e.abs().mean()), 4), "rmse": round(float(np.sqrt((e ** 2).mean())), 4),
                     "bias_by_role": {k: round(float(100 * (p[te.grole == k].mean() / te.act_tgt[te.grole == k].mean() - 1)), 1) for k in ("WR1", "WR2", "WR3+", "TE1", "RB1", "RB2")}}
    out[str(test)] = row
print(json.dumps(out, indent=1)); json.dump(out, open("/tmp/claude-0/s/audit/nfl_conc.json", "w"), indent=1)
