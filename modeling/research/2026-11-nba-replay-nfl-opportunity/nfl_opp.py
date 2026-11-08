"""NFL opportunity experiment (no activation): are WR1/TE1 targets underprojected, and do prior-only
air-yards share / red-zone target share / snap share explain the target residual out of sample?
Walk-forward: fit on seasons before the test season, test on 2024 and 2025."""
import json
import numpy as np, pandas as pd
D = "/home/claude/model-room/modeling/data/"
A = pd.read_pickle(D + "output/nfl/audit/rows_2023_2024_2025_v011.pkl")
R = A[A.market == "receptions"].dropna(subset=["act_tgt"])[["season", "week", "game_id", "player_id", "group", "team", "proj_tgt", "act_tgt"]].copy()
R["rank"] = R.groupby(["game_id", "team"])["proj_tgt"].rank(ascending=False, method="first")
R["role"] = R["group"] + np.where(R["rank"] <= 1, "1", np.where(R["rank"] <= 3, "2-3", "4+"))
# per-group rank
R["grank"] = R.groupby(["game_id", "team", "group"])["proj_tgt"].rank(ascending=False, method="first")
R["grole"] = R["group"] + R["grank"].clip(upper=3).astype(int).astype(str).replace({"3": "3+"})
pg = pd.read_parquet(D + "processed/nfl/player_games.parquet")
pp = pd.read_parquet(D + "processed/nfl/pass_plays.parquet")
rz = pp[(pp.yardline_100 <= 20) & pp.receiver_player_id.notna()]
rzp = rz.groupby(["game_id", "posteam", "receiver_player_id"]).size().rename("rz_tgt").reset_index().rename(columns={"posteam": "team", "receiver_player_id": "player_id"})
rzt = rz.groupby(["game_id", "posteam"]).size().rename("team_rz").reset_index().rename(columns={"posteam": "team"})
deep = pp[(pp.air_yards >= 15) & pp.receiver_player_id.notna()].groupby(["game_id", "posteam", "receiver_player_id"]).size().rename("deep_tgt").reset_index().rename(columns={"posteam": "team", "receiver_player_id": "player_id"})
g = pg[pg.season_type.eq("REG") | pg.season_type.eq("POST")].merge(rzp, on=["game_id", "team", "player_id"], how="left").merge(rzt, on=["game_id", "team"], how="left").merge(deep, on=["game_id", "team", "player_id"], how="left")
for c in ("rz_tgt", "team_rz", "deep_tgt", "targets", "air_yds"):
    g[c] = g[c].fillna(0)
g["game_date"] = pd.to_datetime(g["game_date"])
g = g.sort_values("game_date")
# prior-only rolling sums over the player's last 8 games (shifted: this game excluded)
cols = ["targets", "team_pass_att", "air_yds", "team_air", "rz_tgt", "team_rz", "offense_pct", "deep_tgt"]
gg = g.groupby("player_id")
for c in cols:
    g["p_" + c] = gg[c].transform(lambda s: s.shift(1).rolling(8, min_periods=3).sum() if c != "offense_pct" else s.shift(1).rolling(3, min_periods=1).mean())
g["p_ng"] = gg["targets"].transform(lambda s: s.shift(1).rolling(8, min_periods=3).count())
g["tsh"] = g.p_targets / g.p_team_pass_att
g["aysh"] = (g.p_air_yds / g.p_team_air.where(g.p_team_air > 0)).clip(-0.2, 0.8)
g["rzsh"] = g.p_rz_tgt / g.p_team_rz.where(g.p_team_rz > 0)
g["wopr"] = 1.5 * g.tsh + 0.7 * g.aysh
F = R.merge(g[["game_id", "player_id", "tsh", "aysh", "rzsh", "wopr", "p_offense_pct", "team_pass_att"]], on=["game_id", "player_id"], how="left")
F = F.dropna(subset=["tsh", "aysh"])
F["rzsh"] = F["rzsh"].fillna(F["tsh"])
F["x_ay"] = F.aysh - F.tsh
F["x_rz"] = F.rzsh - F.tsh
F["x_snap"] = (F.p_offense_pct.fillna(0) / 100 if F.p_offense_pct.max() > 1.5 else F.p_offense_pct.fillna(0))
F["res"] = F.act_tgt - F.proj_tgt
out = {"n": len(F)}
out["bias_by_role"] = {k: {"n": int(len(d)), "proj": round(d.proj_tgt.mean(), 2), "act": round(d.act_tgt.mean(), 2), "bias_pct": round(100 * (d.proj_tgt.mean() / d.act_tgt.mean() - 1), 1)} for k, d in F.groupby("grole") if len(d) > 300}
feats = {"base": [], "air": ["x_ay"], "rz": ["x_rz"], "air+rz": ["x_ay", "x_rz"], "air+rz+role": ["x_ay", "x_rz", "r1"]}
F["r1"] = ((F.grank == 1) & F.group.isin(["WR", "TE"])).astype(float)
res = {}
for test in (2024, 2025):
    tr, te = F[F.season < test], F[F.season == test]
    row = {}
    for name, fs in feats.items():
        if fs:
            X = np.c_[tr[fs].to_numpy() * tr[["proj_tgt"]].to_numpy(), tr.proj_tgt]  # multiplicative: residual scales with volume
            b = np.linalg.lstsq(X, tr.res.to_numpy(), rcond=None)[0]
            Xt = np.c_[te[fs].to_numpy() * te[["proj_tgt"]].to_numpy(), te.proj_tgt]
            pred = te.proj_tgt + Xt @ b
        else:
            b, pred = [], te.proj_tgt
        e = pred - te.act_tgt
        r1 = te.r1 == 1
        row[name] = {"coef": [round(float(x), 3) for x in b], "tgt_mae": round(float(e.abs().mean()), 4), "tgt_rmse": round(float(np.sqrt((e ** 2).mean())), 4),
                     "top_wr_te_bias": round(float(e[r1].mean()), 3), "top_wr_te_mae": round(float(e[r1].abs().mean()), 4)}
    res[str(test)] = row
out["walk_forward"] = res
print(json.dumps(out, indent=1))
json.dump(out, open("/tmp/claude-0/s/audit/nfl_opp.json", "w"), indent=1)
