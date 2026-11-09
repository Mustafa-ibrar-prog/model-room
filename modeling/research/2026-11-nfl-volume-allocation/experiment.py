"""Walk-forward allocation experiments on NFL props 0.1.1 (research only; nothing here changes the engine).
Train on 2021..S-1, test season S in (2023, 2024, 2025). Components (each fitted on training seasons only):
  AV  availability: chance each rostered candidate plays (logistic on recent appearance rate, Questionable,
      depth rank, recent snap share, games this season); shares are conditional on playing and normalised so the
      EXPECTED total over candidates equals the share of team attempts that historically reach RB/WR/TE.
  RC  RB carry recency: blend of last-3-game carry share with the long-run share (weight fitted).
  CN  concentration within position group: share^gamma, group total preserved (gamma per position x stat).
  DP  depth-chart role: multiplier per depth rank (1, 2, 3+, unlisted) per position x stat, group total preserved.
  FI  fill-in history: games a player spent filling in for a missing teammate count 0.25 in his share history
      (the engine's existing fill_in_weight feature), so a backup's share reflects his usual role.
Fitted parameters minimise squared error of the share among players who played (unbiased for the mean).
CN/RC/DP only move volume between players of one position on one team; AV sets how much reaches players who play."""
import json, sys, numpy as np, pandas as pd
from scipy.stats import norm
from common import load, SK, H
AUD = "/home/claude/model-room/modeling/data/output/nfl/audit/"
R = load()
R = R[R.group.isin(SK) & ~R.out].copy()
R["key"] = R.game_id + "|" + R.team
R["gkey"] = R.key + "|" + R.group
R["dcat"] = np.select([R.depth == 1, R.depth == 2, R.depth >= 3], ["1", "2", "3+"], "NA")
R["pp"] = R.p_play.fillna(0.75).clip(0.02, 0.98)
R["q"] = (R.injury == "Questionable").astype(float)
R["snap3"] = R.snap_l3.fillna(0.0)
R["new_szn"] = (R.n_szn.fillna(0) == 0).astype(float)
FI = pd.concat([pd.read_pickle(H / f"data/fillin_0.25_{y}.pkl") for y in range(2021, 2026)], ignore_index=True).drop(columns="season")
R = R.merge(FI, on=["game_id", "player_id"], how="left")
R["tsh_fi"] = R.tsh_fi.fillna(R.tshare_hist); R["csh_fi"] = R.csh_fi.fillna(R.cshare_hist)
R["t_raw"] = R.tshare_hist * R.snap_mult * R.match_t
R["c_raw"] = R.cshare_hist * R.snap_mult
R["t_raw_fi"] = R.tsh_fi * R.snap_mult * R.match_t
R["c_raw_fi"] = R.csh_fi * R.snap_mult
R["a_tsh"] = R.a_tgt / R.team_pass_att
R["a_csh"] = R.a_car / R.team_carries

def av_X(d):
    return np.c_[np.ones(len(d)), np.log(d.pp / (1 - d.pp)), d.q, (d.dcat == "1"), (d.dcat == "2"), (d.dcat == "3+"), d.snap3, d.new_szn,
                 (d.group == "RB"), (d.group == "TE"), np.log((d.tshare_hist + d.cshare_hist).clip(lower=0.005)),
                 np.log((d.tshare_hist + d.cshare_hist).clip(lower=0.005)) * (d.group == "RB")].astype(float)

def fit_logit(X, y, iters=50, l2=1e-3):
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p)
        H_ = X.T @ (X * W[:, None]) + l2 * np.eye(len(b)); g = X.T @ (y - p) - l2 * b
        b += np.linalg.solve(H_, g)
    return b

def gsum(d, col):
    return d.groupby("gkey")[col].transform("sum")

def tsum(d, col):
    return d.groupby("key")[col].transform("sum")

def shares(d, cfg, prm):
    """Conditional-on-playing target and carry shares for candidate rows d under configuration cfg."""
    d = d.copy()
    p = d["p_av"] if "AV" in cfg else pd.Series(1.0, index=d.index)
    out = {}
    for stat, raw in (("t", "t_raw"), ("c", "c_raw")):
        r = d[raw + ("_fi" if "FI" in cfg else "")].copy()
        if stat == "c" and "RC" in cfg:
            w = prm["rc_w"]; rb = d.group == "RB"
            h = d.csh_fi if "FI" in cfg else d.cshare_hist
            alt = (w * d.csh_l3.fillna(h) + (1 - w) * h) * d.snap_mult
            r = r.where(~rb, alt)
        base_g = (r * p).groupby(d.gkey).transform("sum")
        if "CN" in cfg or "CNsel" in cfg:
            gam = d.group.map(prm["gamma"][stat]).fillna(1.0)
            r = r.clip(lower=1e-5) ** gam
            r = r * base_g / (r * p).groupby(d.gkey).transform("sum")
        if "DP" in cfg:
            m = pd.Series([prm["depth"][stat].get(f"{g}|{c}", 1.0) for g, c in zip(d.group, d.dcat)], index=d.index)
            r = r * m
            r = r * base_g / (r * p).groupby(d.gkey).transform("sum")
        if "AV" in cfg:
            tot = (r * p).groupby(d.key).transform("sum")
            r = r * prm["tau"][stat] / tot
        else:  # 0.1.1 scaling: shares of everyone not ruled out sum to the 0.1.1 total (incl. QB for carries)
            scale = d["t_scale"] if stat == "t" else d["c_scale"]
            r = r * scale
        out[stat] = r.fillna(0.0)
    return out["t"], out["c"]

def fit(tr, cfg):
    prm = {"gamma": {"t": {}, "c": {}}, "depth": {"t": {}, "c": {}}, "tau": {}, "rc_w": 0.0}
    if "AV" in cfg:
        b = fit_logit(av_X(tr), tr.played.astype(float).to_numpy())
        prm["av_b"] = b.tolist()
        tr = tr.assign(p_av=1 / (1 + np.exp(-av_X(tr) @ b)))
        tm = tr.drop_duplicates("key")
        prm["tau"] = {"t": float(tr.a_tgt.sum() / tm.team_pass_att.sum()), "c": float(tr.a_car.sum() / tm.team_carries.sum())}
    P = tr[tr.played]
    def loss(c2, p2, stat):  # mean abs error of share among played players, by group of interest
        ts, cs = shares(tr, c2, p2)
        s = ts if stat == "t" else cs
        y = tr.a_tsh if stat == "t" else tr.a_csh
        return s, y
    if "RC" in cfg:
        best = None
        for w in np.linspace(0, 1, 11):
            p2 = {**prm, "rc_w": float(w)}
            _, cs = shares(tr, cfg - {"CN", "DP"}, p2)
            m = tr.played & (tr.group == "RB")
            e = float(((cs[m] - tr.a_csh[m]) ** 2).mean())
            if best is None or e < best[0]:
                best = (e, w)
        prm["rc_w"] = float(best[1])
    if "CN" in cfg or "CNsel" in cfg:
        pairs = [("c", "RB"), ("t", "TE")] if "CNsel" in cfg else [("t", g) for g in SK] + [("c", "RB")]
        for stat, g in pairs:
            if True:
                best = None
                for gam in np.linspace(0.8, 1.8, 21):
                    p2 = json.loads(json.dumps(prm)); p2["gamma"][stat][g] = float(gam)
                    ts, cs = shares(tr, cfg - {"DP"}, p2)
                    s = ts if stat == "t" else cs; y = tr.a_tsh if stat == "t" else tr.a_csh
                    m = tr.played & (tr.group == g)
                    e = float(((s[m] - y[m]) ** 2).mean())
                    if best is None or e < best[0]:
                        best = (e, gam)
                prm["gamma"][stat][g] = float(best[1])
    if "DP" in cfg:
        for it in range(6):  # iterative proportional fit of depth multipliers to actual volume among those who played
            for stat in ("t", "c"):
                ts, cs = shares(tr, cfg, prm)
                s = ts if stat == "t" else cs; y = tr.a_tsh if stat == "t" else tr.a_csh
                m = tr.played
                df = pd.DataFrame({"g": tr.group[m], "c": tr.dcat[m], "s": s[m], "y": y[m]})
                for (g, c), v in df.groupby(["g", "c"]):
                    if stat == "c" and g != "RB":
                        continue
                    k = f"{g}|{c}"
                    prm["depth"][stat][k] = float(prm["depth"][stat].get(k, 1.0) * (v.y.sum() / v.s.sum()) ** 0.7)
    return prm

def apply(te, cfg, prm):
    if "AV" in cfg:
        te = te.assign(p_av=1 / (1 + np.exp(-av_X(te) @ np.array(prm["av_b"]))))
    ts, cs = shares(te, cfg, prm)
    return te.assign(n_tgt=ts * te.mu_pa, n_car=cs * te.mu_ru, n_tsh=ts, n_csh=cs)


def ll(p, y): p = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
def ece(p, y, b=10):
    i = np.clip((p * b).astype(int), 0, b - 1); return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))

AUDR = pd.concat([pd.read_pickle(AUD + "rows_2021_2022_v011_fit.pkl"), pd.read_pickle(AUD + "rows_2023_2024_2025_v011.pkl")], ignore_index=True)
AUDR = AUDR[AUDR.group.isin(SK) & AUDR.market.isin(["receptions", "receiving_yards", "rushing_attempts", "rushing_yards"])].dropna(subset=["mline", "y_mline"])

def market_probs(A, ratio_col):
    r = A[ratio_col].clip(0.3, 3).fillna(1.0)
    mu, sd = A["mean"] * r, (A.sd * np.sqrt(r)).clip(lower=0.5)
    return 1 - norm.cdf(A.mline - 0.5, mu, sd), mu

BASE_CAL = {}
def calib_eval(A_tr, A_te, ratio_col, season=None, is_base=False):
    """Per market logistic recalibration of P(over median-of-last-10 line), fitted on training seasons."""
    res = {}
    for mk, te in A_te.groupby("market"):
        tr = A_tr[A_tr.market == mk]
        p_tr, _ = market_probs(tr, ratio_col); p_te, mu = market_probs(te, ratio_col)
        lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
        b = fit_logit(np.c_[np.ones(len(tr)), lg(p_tr)], tr.y_mline.to_numpy().astype(float), l2=1e-6)
        pc = 1 / (1 + np.exp(-(b[0] + b[1] * lg(p_te))))
        if is_base:
            BASE_CAL[(season, mk)] = b
        bb = BASE_CAL[(season, mk)]
        pf = 1 / (1 + np.exp(-(bb[0] + bb[1] * lg(p_te))))  # calibration kept from the current model (not refit)
        y = te.y_mline.to_numpy().astype(float)
        res[mk] = {"n": int(len(te)), "ll": ll(pc, y), "brier": float(np.mean((pc - y) ** 2)), "ece": ece(pc, y),
                   "mae": float((mu - te.actual).abs().mean()), "bias_pct": float(100 * (mu.mean() / te.actual.mean() - 1)),
                   "ll_keepcal": ll(pf, y), "ece_keepcal": ece(pf, y)}
    return res

NAMES = ["base_0.1.1", "CNsel", "AV", "FI", "CN", "DP", "AV+FI", "AV+CN", "AV+DP", "AV+FI+CN", "AV+FI+DP", "AV+FI+CN+DP", "AV+FI+RC", "AV+FI+RC+CN+DP"]
CFGS = {n: frozenset() if n.startswith("base") else frozenset(n.split("+")) for n in NAMES}
if len(sys.argv) > 1:
    CFGS = {k: v for k, v in CFGS.items() if k in sys.argv[1].split(",") or k == "base_0.1.1"}
results, params, test_rows = {}, {}, []
for S in (2023, 2024, 2025):
    tr, te = R[(R.season < S) & (R.season >= 2021)], R[R.season == S]
    base_proj = te[["game_id", "player_id", "proj_tgt", "proj_car"]]
    for name, cfg in CFGS.items():
        prm = fit(tr, cfg) if cfg else {}
        out = apply(te, cfg, prm) if cfg else te.assign(n_tgt=te.proj_tgt, n_car=te.proj_car, n_tsh=te.t_share, n_csh=te.c_share)
        out_tr = apply(tr, cfg, prm) if cfg else tr.assign(n_tgt=tr.proj_tgt, n_car=tr.proj_car)
        if "AV" in cfg:
            pa = out[["p_av", "played"]]
            avc = {"brier": float(((pa.p_av - pa.played) ** 2).mean()), "mean_p": float(pa.p_av.mean()), "played_rate": float(pa.played.mean()),
                   "by_decile": pa.assign(b=pd.qcut(pa.p_av, 5, duplicates="drop")).groupby("b", observed=True).agg(p=("p_av", "mean"), y=("played", "mean")).round(3).values.tolist()}
            prm = {**prm, "av_calibration_test": avc}
        params[f"{S}|{name}"] = {k: v for k, v in prm.items() if k != "av_b"} | ({"av_b": [round(x, 3) for x in prm["av_b"]]} if "av_b" in prm else {})
        test_rows.append(out[["season", "game_id", "team", "player_id", "group", "dcat", "played", "a_tgt", "a_car", "proj_tgt", "proj_car", "n_tgt", "n_car", "n_tsh", "n_csh", "a_tsh", "a_csh", "t_share", "c_share"]].assign(cfg=name))
        # market effect via volume ratios, calibration refit on training seasons
        ratio = lambda o: o.assign(rt=o.n_tgt / o.proj_tgt.clip(lower=0.05), rc=o.n_car / o.proj_car.clip(lower=0.05))[["game_id", "player_id", "rt", "rc"]]
        A_te = AUDR[AUDR.season == S].merge(ratio(out), on=["game_id", "player_id"], how="left")
        A_tr = AUDR[AUDR.season < S].merge(ratio(out_tr), on=["game_id", "player_id"], how="left")
        for A_ in (A_te, A_tr):
            A_["ratio"] = np.where(A_.market.isin(["receptions", "receiving_yards"]), A_.rt, A_.rc)
        mk = calib_eval(A_tr, A_te, "ratio", S, name == "base_0.1.1")
        results[f"{S}|{name}"] = mk
    print(S, "done", flush=True)
T = pd.concat(test_rows, ignore_index=True)
T.to_pickle(H / "data/test_rows.pkl")
json.dump({"markets": results, "params": params}, open(H / "experiment.json", "w"), indent=1, default=float)
print("ok")
