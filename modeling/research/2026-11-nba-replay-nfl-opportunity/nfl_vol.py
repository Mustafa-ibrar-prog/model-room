"""NFL experiments (no model changes), walk-forward: fit on seasons before the test season, test 2024 and 2025.
Base = NFL props 0.1.1 audit rows (2023-25). Corrections are applied on top of the model's projections and judged on
attempts/carries error AND on the effect on the prop market (passing / rushing yards and attempts): MAE, and log loss /
Brier / calibration of P(over the median-of-last-10 line) under a matched normal approximation (same approximation for
base and corrected, so only the shift differs).
  A. Team volume: prior-only team neutral-situation pass rate over expected (PROE) and plays per game.
  B. Thin-history QBs: yards per attempt by career experience, shrunk.
  C. RB game script: player carry share when leading vs trailing x closing spread (closing line = mild optimism)."""
import json, numpy as np, pandas as pd
from scipy.stats import norm
D = "/home/claude/model-room/modeling/data/"
A = pd.read_pickle(D + "output/nfl/audit/rows_2023_2024_2025_v011.pkl")
cols = ["game_id", "play_id", "season", "week", "season_type", "posteam", "defteam", "pass", "rush", "xpass", "pass_oe", "wp", "down", "qtr",
        "score_differential", "qb_dropback", "rusher_player_id", "game_seconds_remaining", "play_type", "epa", "passer_player_id", "spread_line", "home_team"]
P = pd.concat([pd.read_parquet(D + f"raw/nfl/play_by_play_{s}.parquet", columns=cols) for s in range(2020, 2026)], ignore_index=True)
P = P[(P.season_type == "REG") & P.posteam.notna()]
G = P.drop_duplicates("game_id")[["game_id", "season", "week"]]
eps = 1e-6
def ll(p, y): p = np.clip(p, eps, 1 - eps); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
def ece(p, y, b=10):
    i = np.clip((p * b).astype(int), 0, b - 1); return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))
def market_eval(d, mean_new):
    """d: rows of one market with mean, sd, actual, mline, y_mline. Normal approx with sd scaled by the mean ratio."""
    d = d.dropna(subset=["mline", "y_mline"])
    mn = mean_new.loc[d.index]
    r = (mn / d["mean"]).clip(0.3, 3)
    p0 = 1 - norm.cdf(d.mline - 0.5, d["mean"], d.sd.clip(lower=0.5))
    p1 = 1 - norm.cdf(d.mline - 0.5, mn, (d.sd * r).clip(lower=0.5))
    y = d.y_mline.to_numpy()
    return {"n": int(len(d)), "mae": [round(float((d["mean"] - d.actual).abs().mean()), 3), round(float((mn - d.actual).abs().mean()), 3)],
            "bias_pct": [round(float(100 * (d["mean"].mean() / d.actual.mean() - 1)), 2), round(float(100 * (mn.mean() / d.actual.mean() - 1)), 2)],
            "ou_ll": [round(ll(p0, y), 5), round(ll(p1, y), 5)], "ou_brier": [round(float(np.mean((p0 - y) ** 2)), 5), round(float(np.mean((p1 - y) ** 2)), 5)],
            "ou_ece": [round(ece(p0, y), 4), round(ece(p1, y), 4)]}
out = {}
# ---------------- A. team volume
nt = P[(P.down.isin([1, 2])) & (P.qtr <= 3) & P.wp.between(0.2, 0.8) & P.xpass.notna() & (P["pass"] + P["rush"] > 0)]
tg = nt.groupby(["season", "week", "game_id", "posteam"]).agg(proe=("pass_oe", "mean"), n=("pass_oe", "size")).reset_index()
plays = P[(P["pass"] + P["rush"]) > 0].groupby(["season", "week", "game_id", "posteam"]).size().rename("plays").reset_index()
tg = tg.merge(plays, on=["season", "week", "game_id", "posteam"]).sort_values(["season", "week"])
def prior(df, col, carry=0.5):
    # season-to-date mean before this week + carry x previous season mean, shrunk with 4 pseudo-games of the league mean
    res = []
    for (team), d in df.groupby("posteam"):
        d = d.sort_values(["season", "week"])
        vals = []
        for i, r in enumerate(d.itertuples()):
            cur = d[(d.season == r.season) & (d.week < r.week)][col]
            prev = d[d.season == r.season - 1][col]
            w = len(cur) + carry * min(len(prev), 8) + 4
            lg = df[col].mean()
            v = (cur.sum() + carry * min(len(prev), 8) * (prev.mean() if len(prev) else lg) + 4 * lg) / w
            vals.append(v)
        res.append(pd.Series(vals, index=d.index))
    return pd.concat(res)
tg["p_proe"] = prior(tg, "proe"); tg["p_plays"] = prior(tg, "plays")
tg["p_plays_c"] = tg.p_plays - tg.plays.mean()
Q = A[A.market == "passing_attempts"].dropna(subset=["act_att"]).merge(tg[["game_id", "posteam", "p_proe", "p_plays_c"]].rename(columns={"posteam": "team"}), on=["game_id", "team"], how="left").dropna(subset=["p_proe"])
Y = A[A.market == "passing_yards"].drop(columns=["proj_att"]).merge(Q[["game_id", "team", "p_proe", "p_plays_c", "proj_att"]].rename(columns={"proj_att": "pa"}), on=["game_id", "team"], how="inner")
resA = {}
for test in (2024, 2025):
    tr, te = Q[Q.season < test], Q[Q.season == test]
    X = np.c_[tr.p_proe * 100, tr.p_plays_c]; b = np.linalg.lstsq(np.c_[X, np.ones(len(X))], tr.act_att - tr.proj_att, rcond=None)[0]
    adj = lambda d: d.proj_att + np.c_[d.p_proe * 100, d.p_plays_c, np.ones(len(d))] @ b
    newa = adj(te)
    r = {"coef_per_pct_proe_per_play_const": [round(float(x), 3) for x in b],
         "attempts": {"mae": [round(float((te.proj_att - te.act_att).abs().mean()), 3), round(float((newa - te.act_att).abs().mean()), 3)],
                      "rmse": [round(float(np.sqrt(((te.proj_att - te.act_att) ** 2).mean())), 3), round(float(np.sqrt(((newa - te.act_att) ** 2).mean())), 3)]}}
    # market effect: passing_attempts market and passing_yards (scaled by attempts ratio)
    qa = A[(A.market == "passing_attempts")].loc[lambda d: d.index.isin(te.index) | True]
    tq = Q[Q.season == test].copy(); tq_mean = tq["mean"] * (adj(tq) / tq.proj_att.clip(lower=1))
    r["market_passing_attempts"] = market_eval(tq, tq_mean)
    ty = Y[Y.season == test].copy(); ty_mean = ty["mean"] * (adj(ty.rename(columns={"pa": "proj_att"})) / ty.pa.clip(lower=1))
    r["market_passing_yards"] = market_eval(ty, ty_mean)
    resA[str(test)] = r
out["A_team_volume"] = resA
# ---------------- B. thin-history QBs: yards per attempt by experience (fitted ratio actual/proj yards, shrunk)
Yq = A[A.market == "passing_yards"].dropna(subset=["qb_career_att"]).copy()
Yq["exp"] = pd.cut(Yq.qb_career_att, [-1, 149, 499, 1e9], labels=["<150", "150-499", "500+"])
resB = {}
for test in (2024, 2025):
    tr, te = Yq[Yq.season < test], Yq[Yq.season == test].copy()
    k = {}
    for e, d in tr.groupby("exp", observed=True):
        raw = d.actual.sum() / d["mean"].sum(); n = len(d)
        k[e] = float((raw * n + 1.0 * 30) / (n + 30))  # shrink toward 1 with 30 pseudo-games
    te_mean = te["mean"] * te.exp.map(k).astype(float)
    r = {"factors": {str(a): round(v, 3) for a, v in k.items()}}
    for e in ("<150", "150-499", "500+"):
        m = te.exp == e
        if m.sum() >= 20:
            r[e] = market_eval(te[m], te_mean[m])
    resB[str(test)] = r
out["B_thin_qb"] = resB
# ---------------- C. RB carries by script
ru = P[(P.rush == 1) & P.rusher_player_id.notna()].copy()
ru["state"] = np.where(ru.score_differential >= 7, "lead", np.where(ru.score_differential <= -7, "trail", "close"))
tc = ru.groupby(["season", "week", "game_id", "posteam", "state"]).size().rename("team_c").reset_index()
pc = ru.groupby(["season", "week", "game_id", "posteam", "rusher_player_id", "state"]).size().rename("c").reset_index()
pc = pc.merge(tc, on=["season", "week", "game_id", "posteam", "state"])
w = pc.pivot_table(index=["season", "week", "game_id", "posteam", "rusher_player_id"], columns="state", values=["c", "team_c"], aggfunc="sum", fill_value=0)
w.columns = [f"{a}_{b}" for a, b in w.columns]; w = w.reset_index().sort_values(["season", "week"])
for c in [x for x in w.columns if x.startswith(("c_", "team_c_"))]:
    w["p_" + c] = w.groupby("rusher_player_id")[c].transform(lambda s: s.shift(1).rolling(12, min_periods=4).sum())
w = w.dropna(subset=["p_c_close"])
for s in ("lead", "trail", "close"):
    w[f"sh_{s}"] = (w[f"p_c_{s}"] + 2 * 0.3) / (w[f"p_team_c_{s}"] + 2)
w["tilt"] = (w.sh_lead - w.sh_trail) / ((w.sh_lead + w.sh_trail) / 2).clip(lower=0.02)  # >0: carries rise when leading
sp = P.drop_duplicates("game_id")[["game_id", "spread_line", "home_team"]]
R = A[(A.market == "rushing_attempts") & (A.group == "RB")].dropna(subset=["act_car"]).merge(w[["game_id", "rusher_player_id", "tilt"]].rename(columns={"rusher_player_id": "player_id"}), on=["game_id", "player_id"], how="inner").merge(sp, on="game_id", how="left")
R["fav"] = np.where(R.team == R.home_team, R.spread_line, -R.spread_line) / 7.0  # + = team favoured, in touchdowns
R["x"] = R.tilt.clip(-1.5, 1.5) * R.fav.clip(-2, 2)
RY = A[(A.market == "rushing_yards") & (A.group == "RB")].merge(R[["game_id", "player_id", "x", "proj_car"]].rename(columns={"proj_car": "pc"}), on=["game_id", "player_id"], how="inner")
resC = {}
for test in (2024, 2025):
    tr, te = R[R.season < test], R[R.season == test].copy()
    b = float(np.sum(tr.x * tr.proj_car * (tr.act_car - tr.proj_car)) / np.sum((tr.x * tr.proj_car) ** 2))
    newc = te.proj_car * (1 + b * te.x)
    r = {"coef": round(b, 4), "carries": {"mae": [round(float((te.proj_car - te.act_car).abs().mean()), 3), round(float((newc - te.act_car).abs().mean()), 3)],
                                         "rmse": [round(float(np.sqrt(((te.proj_car - te.act_car) ** 2).mean())), 3), round(float(np.sqrt(((newc - te.act_car) ** 2).mean())), 3)]}}
    r["market_rushing_attempts"] = market_eval(te, te["mean"] * (1 + b * te.x))
    ty = RY[RY.season == test]
    r["market_rushing_yards"] = market_eval(ty, ty["mean"] * (1 + b * ty.x))
    resC[str(test)] = r
out["C_rb_script"] = resC
print(json.dumps(out, indent=1)); json.dump(out, open("/tmp/claude-0/s/audit/nfl_vol.json", "w"), indent=1)
