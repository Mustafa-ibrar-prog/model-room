"""Scoring and calibration for player-prop probabilities (shared by the NFL and NBA prop backtests).

No model code: these only take predicted probabilities and outcomes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import calibration_table, probability_summary


def ece(p, y, bins: int = 10) -> float:
    """Expected calibration error: average |predicted − actual| over probability bins, weighted by count."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    if not p.size:
        return float("nan")
    idx = np.minimum((p * bins).astype(int), bins - 1)
    tot = 0.0
    for b in range(bins):
        s = idx == b
        if s.any():
            tot += s.sum() * abs(p[s].mean() - y[s].mean())
    return round(float(tot / p.size), 4)


def fit_calibration(t: pd.DataFrame) -> dict:
    """Per market, p' = σ(a + b·logit(p)) by Newton's method on log loss. Fit on tuning seasons only."""
    out = {}
    for mkey, d in t.groupby("market"):
        p = np.clip(d["p"].to_numpy(float), 1e-4, 1 - 1e-4)
        y = d["y"].to_numpy(float)
        X = np.column_stack([np.ones_like(p), np.log(p / (1 - p))])
        w = np.array([0.0, 1.0])
        for _ in range(25):
            q = 1 / (1 + np.exp(-(X @ w)))
            g = X.T @ (q - y)
            h = (X * (q * (1 - q))[:, None]).T @ X + 1e-6 * np.eye(2)
            step = np.linalg.solve(h, g)
            w = w - step
            if np.max(np.abs(step)) < 1e-7:
                break
        out[mkey] = [round(float(w[0]), 4), round(float(w[1]), 4)]
    return out


def apply_calibration(t: pd.DataFrame, cal: dict) -> pd.DataFrame:
    t = t.copy()
    p = np.clip(t["p"].to_numpy(float), 1e-4, 1 - 1e-4)
    a = t["market"].map(lambda m: cal.get(m, [0.0, 1.0])[0]).to_numpy(float)
    b = t["market"].map(lambda m: cal.get(m, [0.0, 1.0])[1]).to_numpy(float)
    t["p_raw"] = t["p"]
    t["p"] = 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))
    return t


def fixed_rows(t: pd.DataFrame, lo: float = 0.05, hi: float = 0.95) -> pd.DataFrame:
    """Rows chosen independently of the model being scored: thresholds where the player's own recent hit
    rate is between lo and hi. Comparing models on rows filtered by their own probabilities is unfair (a
    wider model keeps more easy rows and looks better)."""
    b = t["baseline_p"]
    return t[b.notna() & (b >= lo) & (b <= hi)]


def objective(t: pd.DataFrame) -> float:
    """Mean of per-market log loss (each market counts equally)."""
    vals = []
    for _, d in t.groupby("market"):
        p = np.clip(d["p"].to_numpy(), 1e-4, 1 - 1e-4)
        y = d["y"].to_numpy()
        vals.append(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))))
    return float(np.mean(vals))




def summarize(t: pd.DataFrame, m: pd.DataFrame) -> dict:
    out = {"thresholds": int(len(t)), "player_games": int(t["game_id"].astype(str).add(t["player_id"]).nunique()) if len(t) else 0, "markets": {}}
    for mkey, d in t.groupby("market"):
        b = d.dropna(subset=["baseline_p"])
        mm = m[m["market"] == mkey]
        mb = mm.dropna(subset=["baseline"])
        out["markets"][mkey] = {
            "model": probability_summary(d["p"], d["y"]),
            "ece": ece(d["p"], d["y"]),
            "by_support": {lvl: {**probability_summary(g["p"], g["y"]), "ece": ece(g["p"], g["y"])}
                           for lvl, g in d.groupby("support")} if "support" in d else {},
            "baseline_same_rows": {"model": probability_summary(b["p"], b["y"]), "baseline": probability_summary(b["baseline_p"], b["y"])} if len(b) else None,
            "calibration": calibration_table(d["p"], d["y"]),
            "mean_projection": {"n": int(len(mm)), "model_mae": round(float(np.mean(np.abs(mm["proj"] - mm["actual"]))), 3),
                                "model_bias": round(float(np.mean(mm["proj"] - mm["actual"])), 3),
                                "recent_avg_mae": round(float(np.mean(np.abs(mb["baseline"] - mb["actual"]))), 3) if len(mb) else None},
        }
    # Confidence: distance of the probability from 50%.
    if len(t):
        conf = pd.cut((t["p"] - 0.5).abs(), [0, 0.1, 0.2, 0.3, 0.4, 0.5], include_lowest=True)
        out["by_confidence"] = [{"distance_from_50": str(k), **probability_summary(g["p"], g["y"]),
                                 "predicted": round(float(g["p"].mean()), 3), "actual": round(float(g["y"].mean()), 3)}
                                for k, g in t.groupby(conf, observed=True)]
        out["overall"] = {**probability_summary(t["p"], t["y"]), "ece": ece(t["p"], t["y"])}
        if "support" in t:
            out["by_support"] = {lvl: {**probability_summary(g["p"], g["y"]), "ece": ece(g["p"], g["y"])} for lvl, g in t.groupby("support")}
        b = t.dropna(subset=["baseline_p"])
        out["overall_vs_baseline"] = {"model": probability_summary(b["p"], b["y"]), "baseline": probability_summary(b["baseline_p"], b["y"])}
        out["calibration"] = calibration_table(t["p"], t["y"])
    return out
