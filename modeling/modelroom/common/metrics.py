"""Evaluation metrics shared by both backtests."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def normal_cdf(x: np.ndarray | float) -> np.ndarray | float:
    """Standard normal CDF via erf (no scipy needed)."""
    arr = np.asarray(x, dtype=float)
    out = 0.5 * (1.0 + np.vectorize(math.erf)(arr / math.sqrt(2.0)))
    return float(out) if np.ndim(x) == 0 else out


def error_summary(pred: np.ndarray, actual: np.ndarray) -> dict:
    err = np.asarray(pred, float) - np.asarray(actual, float)
    return {
        "n": int(err.size),
        "mae": round(float(np.mean(np.abs(err))), 3),
        "rmse": round(float(np.sqrt(np.mean(err**2))), 3),
        "bias": round(float(np.mean(err)), 3),
    }


def probability_summary(prob: np.ndarray, outcome: np.ndarray) -> dict:
    p = np.clip(np.asarray(prob, float), 1e-6, 1 - 1e-6)
    y = np.asarray(outcome, float)
    return {
        "n": int(p.size),
        "brier": round(float(np.mean((p - y) ** 2)), 4),
        "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
        "accuracy": round(float(np.mean((p > 0.5) == (y == 1))), 4),
    }


def calibration_table(prob: np.ndarray, outcome: np.ndarray, bins: int = 10) -> list[dict]:
    """Predicted vs actual win rate in equal-width probability bins."""
    df = pd.DataFrame({"p": np.asarray(prob, float), "y": np.asarray(outcome, float)})
    edges = np.linspace(0, 1, bins + 1)
    df["bin"] = pd.cut(df["p"], edges, include_lowest=True)
    rows = []
    for interval, g in df.groupby("bin", observed=True):
        rows.append(
            {
                "bin": f"{interval.left:.1f}-{interval.right:.1f}",
                "n": int(len(g)),
                "predicted": round(float(g["p"].mean()), 3),
                "actual": round(float(g["y"].mean()), 3),
            }
        )
    return rows


def against_line(model_line: np.ndarray, market_line: np.ndarray, actual: np.ndarray, min_edge: float = 0.0) -> dict:
    """How often the side the model preferred (vs the market) won.

    For spreads pass margins (home − away) as model_line, market_line and actual.
    For totals pass totals. Pushes are excluded. This is a descriptive record,
    not evidence of profitability (it ignores the bookmaker's margin, and the
    break-even rate at −110 is about 52.4%).
    """
    m, k, a = (np.asarray(v, float) for v in (model_line, market_line, actual))
    ok = ~(np.isnan(m) | np.isnan(k) | np.isnan(a))
    m, k, a = m[ok], k[ok], a[ok]
    edge = m - k
    pick = np.sign(edge)
    result = np.sign(a - k)
    use = (np.abs(edge) >= min_edge) & (pick != 0) & (result != 0)
    wins = int(np.sum(pick[use] == result[use]))
    n = int(np.sum(use))
    return {
        "n": n,
        "wins": wins,
        "win_rate": round(wins / n, 4) if n else None,
        "min_edge": min_edge,
        "model_mae": round(float(np.mean(np.abs(m - a))), 3) if m.size else None,
        "market_mae": round(float(np.mean(np.abs(k - a))), 3) if k.size else None,
    }
