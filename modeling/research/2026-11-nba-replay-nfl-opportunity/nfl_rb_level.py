import json, numpy as np, pandas as pd, sys
sys.argv = ["x"]; exec(open("/tmp/claude-0/s/audit/nfl_vol.py").read().split("out = {}")[0])  # helpers + data
R = A[(A.market == "rushing_attempts") & (A.group == "RB")].dropna(subset=["act_car"]).copy()
R["grank"] = R.groupby(["game_id", "team"])["proj_car"].rank(ascending=False, method="first")
R["role"] = np.where(R.grank == 1, "RB1", "RB2+")
RY = A[(A.market == "rushing_yards") & (A.group == "RB")].merge(R[["game_id", "player_id", "role"]], on=["game_id", "player_id"])
out = {"bias_by_season_role": {f"{s} {r}": round(float(100 * (d.proj_car.mean() / d.act_car.mean() - 1)), 1) for (s, r), d in R.groupby(["season", "role"])}}
team = A[(A.market == "rushing_attempts")].dropna(subset=["act_car"]).groupby(["season", "game_id", "team"])[["proj_car", "act_car"]].sum()
out["team_carries_in_rows_bias"] = {int(s): round(float(100 * (d.proj_car.mean() / d.act_car.mean() - 1)), 1) for s, d in team.groupby("season")}
for test in (2024, 2025):
    tr = R[R.season < test]
    k = (tr.groupby("role").act_car.sum() / tr.groupby("role").proj_car.sum()).to_dict()
    te = R[R.season == test]; f = te.role.map(k)
    ty = RY[RY.season == test]; fy = ty.role.map(k)
    out[str(test)] = {"factors": {a: round(v, 3) for a, v in k.items()},
                      "market_rushing_attempts": market_eval(te, te["mean"] * f), "market_rushing_yards": market_eval(ty, ty["mean"] * fy)}
print(json.dumps(out, indent=1)); json.dump(out, open("/tmp/claude-0/s/audit/nfl_rb_level.json", "w"), indent=1)
