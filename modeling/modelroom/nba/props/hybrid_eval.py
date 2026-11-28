"""Shadow hybrid evaluation (TEST research, Moose 2026-11-28). Read-only toward every model; nothing activated.

Question: does the evidence the AI analysis shows (recent form, opponent defense vs position, minutes trend, home/away
split, back-to-back, blowout risk) carry information the active NBA props model 0.2.0 has NOT already used? If it does,
a small, fixed, testable adjustment should improve out-of-sample log loss; if not, the evidence is context only.

  1. Original prediction   0.2.0 replayed walk-forward (each day built only from games before it), P(stat >= K) at
                           K = ceil(median of his last 10), calibrated exactly as published
  2. Evidence assessment   the same evidence kinds the site shows, as numbers computed from pre-game data only
                           (the AI's text is not an input: it may only quote these facts, and free text isn't testable)
  3. Refinement            logit(p') = logit(p) + sum(beta_k * x_k); beta fitted by L2 logistic regression on EARLIER
                           games only, refitted at the start of each test month; |adjustment| capped at 0.5 logit
  4. Hybrid prediction     p', recorded beside p
  5. Comparison            test months only: log loss, Brier, calibration (ECE), accuracy, by stat, with a 95% interval
                           on the log-loss gain from resampling whole game days

Market comparison: historical prop prices aren't stored (Odds API points lines only from Nov 2026; Polymarket prices
are never stored), so the historical test is model vs model. The forward shadow ledger adds stored lines as they come.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import model as M
from .config import MARKETS, PropParams
from .injury_eval import ece, ll

PARAMS = Path(__file__).resolve().parent
EPS = 1e-6
FEATURES = ["form10", "form5", "matchup", "minutes_trend", "split", "b2b", "blowout"]
CAP = 0.5
L2 = 2.0
MIN_DEF_GAMES = 6
STAT_OF = {k: v["stat"] for k, v in MARKETS.items()}


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigm(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, float)))


def fit(X: np.ndarray, off: np.ndarray, y: np.ndarray, lam: float = L2, iters: int = 30) -> np.ndarray:
    """L2 logistic regression with an offset (Newton). No intercept: the model's own calibration is left alone."""
    b = np.zeros(X.shape[1])
    n = max(len(y), 1)
    for _ in range(iters):
        p = sigm(off + X @ b)
        g = X.T @ (p - y) / n + lam * b / n
        H = (X * (p * (1 - p))[:, None]).T @ X / n + lam * np.eye(X.shape[1]) / n
        step = np.linalg.solve(H, g)
        b -= step
        if np.abs(step).max() < 1e-8:
            break
    return b


def adjust(p: np.ndarray, X: np.ndarray, b: np.ndarray) -> np.ndarray:
    return sigm(logit(p) + np.clip(X @ b, -CAP, CAP))


def defense_table(rows: pd.DataFrame) -> dict:
    """Season-to-date allowed per game by (opp, group) for each stat, as z-scores across teams (>= MIN_DEF_GAMES)."""
    out = {}
    if rows.empty:
        return out
    stats = sorted(set(STAT_OF.values()))
    per = rows.groupby(["opp", "group", "game_id"])[stats].sum()
    g = per.groupby(level=[0, 1])
    avg, n = g.mean(), g.size()
    ok = n >= MIN_DEF_GAMES
    for grp in avg.index.get_level_values(1).unique():
        a = avg.xs(grp, level=1)[ok.xs(grp, level=1)]
        if len(a) < 10:
            continue
        z = (a - a.mean()) / a.std(ddof=0).replace(0, np.nan)
        for opp, r in z.iterrows():
            out[(opp, grp)] = r.to_dict()
    return out


def features(h: pd.DataFrame, season_rows: pd.DataFrame, K: float, stat: str, p: float, is_home: bool, b2b: bool, margin: float,
             dz: dict | None) -> dict:
    """Pre-game evidence as numbers, oriented so positive favours 'K or more'. h: his played games before the day, newest first."""
    last10, last5 = h.head(10), h.head(5)
    r10 = float((last10[stat] >= K).mean())
    r5 = float((last5[stat] >= K).mean())
    ref = season_rows if len(season_rows) >= 5 else h.head(20)       # early season: his last 20 games instead
    m_season = float(ref["minutes"].mean()) if len(ref) else float("nan")
    m5 = float(last5["minutes"].mean())
    split = 0.0
    hm, aw = season_rows[season_rows["is_home"]], season_rows[~season_rows["is_home"]]
    if len(hm) >= 5 and len(aw) >= 5:
        d = float(hm[stat].mean() - aw[stat].mean())
        split = (d if is_home else -d) / max(K, 1.0)
    return {"form10": r10 - p, "form5": r5 - r10, "matchup": float(dz.get(stat, 0.0)) if dz else 0.0,
            "minutes_trend": (m5 - m_season) / max(m_season, 10.0) if math.isfinite(m_season) else 0.0,
            "split": float(np.clip(split, -1, 1)), "b2b": 1.0 if b2b else 0.0, "blowout": max(0.0, abs(margin) - 8.0) / 10.0}


def replay(seasons: list[int], sims: int, max_days: int | None = None, log=print) -> pd.DataFrame:
    from . import inputs as I
    inp = I.load()
    pg = inp.player_games.copy()
    pg["player_id"] = pg["player_id"].astype(str)
    pg["gd"] = pd.to_datetime(pg["game_date"])
    pg["is_home"] = pg["is_home"].astype(bool)
    games = inp.games
    games = games[games["season"].isin(seasons) & (games["status"] == "final")].copy()
    games["game_id"] = games["game_id"].astype(str)
    gi = games.set_index("game_id")
    p0 = PropParams.load(PARAMS / "params_0.2.0.json")
    p0 = replace(p0, settings=replace(p0.settings, sims=sims))
    played = pg[pg["played"]]
    box = played.set_index(["game_id", "player_id"])
    days = sorted(games["game_date"].astype(str).unique())[: max_days or None]
    rows, t0 = [], time.time()
    for di, day in enumerate(days):
        dg = games[games["game_date"].astype(str) == day]
        season = int(dg["season"].iloc[0])
        cutoff = pd.Timestamp(day)
        before = played[played["gd"] < cutoff]
        this = before[before["season"] == season]
        dz = defense_table(this)
        ctx = M.build(inp.player_games, inp.pace, cutoff, season, p0.settings)
        projs = M.project_games(ctx, dg, p0, seed=int(day.replace("-", "")), avail=None)
        hist_by = {k: v.sort_values("gd", ascending=False) for k, v in before[before["player_id"].isin({str(x.player_id) for x in projs})].groupby("player_id")}
        for x in projs:
            k = (str(x.game_id), str(x.player_id))
            if k not in box.index:
                continue
            a = box.loc[k]
            h = hist_by.get(str(x.player_id))
            if h is None or len(h) < 5:
                continue
            g = gi.loc[str(x.game_id)]
            home = a["team"] == g["home_abbr"]
            b2b = bool(g["home_b2b"] if home else g["away_b2b"])
            margin = float(g["proj_margin"]) if pd.notna(g.get("proj_margin")) else 0.0
            srows = h[h["season"] == season]
            grp = a["group"]
            for mk, m in MARKETS.items():
                st = m["stat"]
                K = float(max(1, math.ceil(float(np.median(h.head(10)[st])))))
                p = float(p0.calibrate(mk, x.prob(st, K)))
                if not (0.03 <= p <= 0.97):
                    continue
                f = features(h, srows, K, st, p, bool(home), b2b, margin, dz.get((a["opp"], grp)))
                rows.append({"date": day, "season": season, "market": mk, "pg": f"{k[0]}|{k[1]}", "K": K, "p": p, "y": float(a[st] >= K), **f})
        if di % 20 == 0:
            log(f"{day}: {di + 1}/{len(days)} days, {len(rows)} rows, {time.time() - t0:.0f}s")
    return pd.DataFrame(rows)


def metric(p, y) -> dict:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return {"n": int(len(p)), "log_loss": round(ll(p, y), 5), "brier": round(float(np.mean((p - y) ** 2)), 5), "ece": round(ece(p, y), 4),
            "accuracy": round(float(np.mean((p >= 0.5) == (y == 1))), 4), "mean_p": round(float(p.mean()), 4), "hit_rate": round(float(y.mean()), 4)}


def walk_forward(R: pd.DataFrame, warmup_days: int = 75, seed: int = 7) -> dict:
    R = R.sort_values("date").reset_index(drop=True)
    R["month"] = R["date"].str[:7]
    first = pd.Timestamp(R["date"].min()) + pd.Timedelta(days=warmup_days)
    months = sorted(m for m in R["month"].unique() if pd.Timestamp(m + "-01") >= first)
    R["p_hybrid"] = np.nan
    coefs = []
    for mo in months:
        tr = R[R["date"] < mo + "-01"]
        te = R["month"] == mo
        if len(tr) < 2000:
            continue
        b = fit(tr[FEATURES].to_numpy(), logit(tr["p"]), tr["y"].to_numpy())
        coefs.append({"month": mo, **{f: round(float(v), 4) for f, v in zip(FEATURES, b)}, "train_n": int(len(tr))})
        R.loc[te, "p_hybrid"] = adjust(R.loc[te, "p"].to_numpy(), R.loc[te, FEATURES].to_numpy(), b)
    T = R.dropna(subset=["p_hybrid"])
    if T.empty:
        return {"test_rows": 0, "verdict": "not enough history for a chronological test"}
    out = {"test_rows": int(len(T)), "test_months": sorted(T["month"].unique().tolist()), "monthly_coefficients": coefs,
           "overall": {"original": metric(T["p"], T["y"]), "hybrid": metric(T["p_hybrid"], T["y"])}, "by_market": {}, "by_season": {}}
    for mk, g in T.groupby("market"):
        out["by_market"][mk] = {"original": metric(g["p"], g["y"]), "hybrid": metric(g["p_hybrid"], g["y"]), "ll_gain": gain_ci(g, seed)}
    for s, g in T.groupby("season"):
        out["by_season"][str(s)] = {"original": metric(g["p"], g["y"]), "hybrid": metric(g["p_hybrid"], g["y"]), "ll_gain": gain_ci(g, seed)}
    out["overall"]["ll_gain"] = gain_ci(T, seed)
    adj = np.abs(logit(T["p_hybrid"]) - logit(T["p"]))
    out["adjustment_size"] = {"median_logit": round(float(np.median(adj)), 4), "share_capped": round(float(np.mean(adj >= CAP - 1e-9)), 4),
                              "median_prob_points": round(float(np.median(np.abs(T["p_hybrid"] - T["p"])) * 100), 2)}
    # which evidence carries information: each feature alone, same protocol
    solo = {}
    for f in FEATURES:
        ph = pd.Series(np.nan, index=R.index)
        for mo in months:
            tr = R[R["date"] < mo + "-01"]
            if len(tr) < 2000:
                continue
            b = fit(tr[[f]].to_numpy(), logit(tr["p"]), tr["y"].to_numpy())
            te = R["month"] == mo
            ph[te] = adjust(R.loc[te, "p"].to_numpy(), R.loc[te, [f]].to_numpy(), b)
        g = R.assign(p_hybrid=ph).dropna(subset=["p_hybrid"])
        solo[f] = gain_ci(g, seed)
    out["single_feature_ll_gain"] = solo
    full = fit(R[FEATURES].to_numpy(), logit(R["p"]), R["y"].to_numpy())
    out["final_coefficients"] = {"features": FEATURES, "beta": [round(float(v), 5) for v in full], "cap_logit": CAP, "l2": L2,
                                 "fitted_rows": int(len(R)), "through": str(R["date"].max())}
    ci = out["overall"]["ll_gain"]["ci95"]
    out["verdict"] = ("hybrid improves out-of-sample log loss (95% interval above zero)" if ci[0] > 0 else
                      "hybrid makes log loss worse (95% interval below zero)" if ci[1] < 0 else
                      "no measurable improvement: the interval includes zero, so the evidence stays context only")
    return out


def gain_ci(g: pd.DataFrame, seed: int) -> dict:
    """Original log loss minus hybrid log loss per row (positive = hybrid better), 95% interval over whole days."""
    y = g["y"].to_numpy()
    la = -(y * np.log(np.clip(g["p"], EPS, 1 - EPS)) + (1 - y) * np.log(np.clip(1 - g["p"], EPS, 1)))
    lb = -(y * np.log(np.clip(g["p_hybrid"], EPS, 1 - EPS)) + (1 - y) * np.log(np.clip(1 - g["p_hybrid"], EPS, 1)))
    d = pd.DataFrame({"d": (la - lb).to_numpy(), "day": g["date"].to_numpy()}).groupby("day")["d"].agg(["sum", "count"]).to_numpy()
    if not len(d):
        return {"n": 0}
    rng = np.random.default_rng(seed)
    bs = [(lambda t: t[0] / t[1])(d[rng.integers(0, len(d), len(d))].sum(axis=0)) for _ in range(1000)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"n": int(len(g)), "gain": round(float(d[:, 0].sum() / d[:, 1].sum()), 5), "ci95": [round(float(lo), 5), round(float(hi), 5)], "days": int(len(d))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m modelroom.nba.props.hybrid_eval")
    ap.add_argument("--seasons", default="2025,2026,2027")
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--max-days", type=int, default=None)
    ap.add_argument("--rows", default=None, help="save the replayed rows (parquet) for re-analysis")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    R = replay([int(s) for s in a.seasons.split(",")], a.sims, a.max_days)
    if a.rows:
        R.to_parquet(a.rows)
    res = {"model": "nba-props 0.2.0 (active)", "seasons": a.seasons, "sims": a.sims, "rows": int(len(R)), "features": FEATURES,
           **walk_forward(R)}
    Path(a.out).write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: res[k] for k in ("rows", "test_rows", "overall", "verdict", "final_coefficients")}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
