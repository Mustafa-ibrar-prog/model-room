"""Diagnostics of NFL props 0.1.1 opportunity allocation, 2023-25 (2021-22 shown for reference). Read-only."""
import json, numpy as np, pandas as pd
from common import load, SK, H
R = load()
R = R[R.group.isin(SK + ["QB"])]
S = R[R.group.isin(SK)].copy()
out = {}
pct = lambda a, b: round(float(100 * (a / b - 1)), 1)
for yr in (2021, 2022, 2023, 2024, 2025):
    d = S[S.season == yr]; o = {}
    tm = d.drop_duplicates(["game_id", "team"])
    o["team_games"] = len(tm)
    # team totals: projected share sums vs actual share of team attempts going to tracked RB/WR/TE
    o["targets_to_skill_per_pass_att_actual"] = round(float(d.a_tgt.sum() / tm.team_pass_att.sum()), 4)
    o["carries_to_skill_per_carry_actual"] = round(float(d.a_car.sum() / tm.team_carries.sum()), 4)
    o["proj_target_share_sum_per_team"] = round(float(d.t_share.sum() / len(tm)), 4)
    o["proj_carry_share_sum_skill_per_team"] = round(float(d.c_share.sum() / len(tm)), 4)
    o["mu_pa_vs_actual_pct"] = pct(tm.mu_pa.sum(), tm.team_pass_att.sum())
    o["mu_ru_vs_actual_pct"] = pct(tm.mu_ru.sum(), tm.team_carries.sum())
    act = d[~d.out]
    o["proj_tgt_to_nonplayers_pct"] = round(float(100 * act.loc[~act.played, "proj_tgt"].sum() / act.proj_tgt.sum()), 1)
    o["proj_car_to_nonplayers_pct"] = round(float(100 * act.loc[~act.played, "proj_car"].sum() / act.proj_car.sum()), 1)
    out[str(yr)] = o
# --- who are the non-players (2023-25): by injury status, p_play bucket, depth, recent snaps
T = S[(S.season >= 2023) & ~S.out].copy()
T["vol"] = T.proj_tgt + T.proj_car
np_ = T[~T.played]
def bucket_table(col, bins=None, labels=None):
    x = T[col] if bins is None else pd.cut(T[col], bins, labels=labels)
    g = T.assign(b=x.astype(str)).groupby("b")
    return {k: {"n": int(len(v)), "played_rate": round(float(v.played.mean()), 3), "share_of_ghost_volume_pct": round(float(100 * v.loc[~v.played, "vol"].sum() / np_.vol.sum()), 1)} for k, v in g}
out["nonplayers_by_injury"] = bucket_table("injury")
out["nonplayers_by_p_play"] = bucket_table("p_play", [-0.01, 0.3, 0.6, 0.85, 0.95, 1.01], ["<0.3", "0.3-0.6", "0.6-0.85", "0.85-0.95", "0.95+"])
out["nonplayers_by_depth"] = bucket_table("depth", [0, 1, 2, 3, 99], ["1", "2", "3", "4+"])
T["depth_na"] = T.depth.isna()
out["nonplayers_by_depth_missing"] = bucket_table("depth_na")
out["nonplayers_by_last3_snap"] = bucket_table("snap_l3", [-0.01, 0.15, 0.4, 0.7, 1.01], ["<15%", "15-40%", "40-70%", "70%+"])
# --- among players who played: bias by within-team role (rank by projection) per position, and by depth rank
P = S[(S.season >= 2023) & S.played & ~S.out].copy()
P["rk_t"] = P.groupby(["game_id", "team", "group"]).proj_tgt.rank(ascending=False, method="first")
P["rk_c"] = P.groupby(["game_id", "team", "group"]).proj_car.rank(ascending=False, method="first")
role = {}
for grp in SK:
    for k in (1, 2, 3, 4):
        d = P[(P.group == grp) & (P.rk_t == k)]
        if len(d) > 50:
            role[f"{grp}{k}_targets"] = {"n": int(len(d)), "bias_pct": pct(d.proj_tgt.sum(), d.a_tgt.sum()), "mae": round(float((d.proj_tgt - d.a_tgt).abs().mean()), 3)}
    if grp == "RB":
        for k in (1, 2, 3):
            d = P[(P.group == grp) & (P.rk_c == k)]
            role[f"RB{k}_carries"] = {"n": int(len(d)), "bias_pct": pct(d.proj_car.sum(), d.a_car.sum()), "mae": round(float((d.proj_car - d.a_car).abs().mean()), 3)}
out["played_bias_by_projection_rank_2023_25"] = role
# --- flatness: slope of actual share on projected share, within position (team-game), played players
fl = {}
for grp, a, pr, den in (("RB", "a_car", "c_share", "team_carries"), ("RB", "a_tgt", "t_share", "team_pass_att"), ("WR", "a_tgt", "t_share", "team_pass_att"), ("TE", "a_tgt", "t_share", "team_pass_att")):
    d = P[(P.group == grp)]
    y = d[a] / d[den]; x = d[pr]
    b = np.polyfit(x, y, 1)
    fl[f"{grp}_{a}"] = {"slope": round(float(b[0]), 3), "intercept": round(float(b[1]), 4), "n": int(len(d))}
out["actual_vs_projected_share_slope_played"] = fl
# --- recency: which history predicts actual share best (played players, 2023-25), MAE of share
rc = {}
for grp, a, den, cols in (("RB", "a_car", "team_carries", ["cshare_hist", "csh_l3", "csh_szn"]), ("WR", "a_tgt", "team_pass_att", ["tshare_hist", "tsh_l3", "tsh_szn"]),
                          ("TE", "a_tgt", "team_pass_att", ["tshare_hist", "tsh_l3", "tsh_szn"]), ("RB", "a_tgt", "team_pass_att", ["tshare_hist", "tsh_l3", "tsh_szn"])):
    d = P[(P.group == grp)].dropna(subset=cols)
    y = d[a] / d[den]
    rc[f"{grp}_{a}"] = {"n": int(len(d)), **{c: round(float((d[c] - y).abs().mean() * 100), 3) for c in cols},
                        "corr": {c: round(float(np.corrcoef(d[c], y)[0, 1]), 3) for c in cols}}
out["recency_share_mae_pctpts_played_with_season_history"] = rc
# --- depth rank vs projected rank among played: bias by depth rank
dp = {}
for grp in SK:
    for k, lab in ((1, "1"), (2, "2"), (3, "3+")):
        d = P[(P.group == grp) & ((P.depth == k) if k < 3 else (P.depth >= 3))]
        dp[f"{grp}_depth{lab}"] = {"n": int(len(d)), "targets_bias_pct": pct(d.proj_tgt.sum(), d.a_tgt.sum()),
                                   **({"carries_bias_pct": pct(d.proj_car.sum(), d.a_car.sum())} if grp == "RB" else {})}
    d = P[(P.group == grp) & P.depth.isna()]
    dp[f"{grp}_unlisted"] = {"n": int(len(d)), "targets_bias_pct": pct(d.proj_tgt.sum(), d.a_tgt.sum()), **({"carries_bias_pct": pct(d.proj_car.sum(), d.a_car.sum())} if grp == "RB" else {})}
out["played_bias_by_depth_rank_2023_25"] = dp
# --- fill-in contamination: share history includes games played while a teammate was out; proxy: hist share vs season l3
# --- where does the actual volume go that was not projected: actual to non-candidates
json.dump(out, open(H / "diag.json", "w"), indent=1)
print(json.dumps(out, indent=1))
