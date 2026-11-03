"""Calibrated P(stat >= k) on a grid of whole-number lines, published with each prop market.

The site uses it to price any line an exchange lists (not just the board's display thresholds) without
re-running the simulation. Yardage stats use a 5-yard grid that the site interpolates; counts use 1.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

COARSE = {"pass_yds", "rush_yds", "rec_yds", "rush_rec_yds"}


def build(sims: np.ndarray, stat: str, calibrate: Callable[[float], float]) -> dict:
    x = np.sort(np.asarray(sims, dtype=float))
    n = len(x)
    if n == 0:
        return {"k0": 0, "step": 1, "p": []}
    step = 5 if stat in COARSE else 1
    lo = max(0, math.floor(float(np.quantile(x, 0.01)) / step) * step)
    hi = math.ceil(float(np.quantile(x, 0.99)) / step) * step + step
    ks = np.arange(lo, hi + step, step, dtype=float)
    raw = 1.0 - np.searchsorted(x, ks, side="left") / n   # P(X >= k)
    return {"k0": int(lo), "step": step, "p": [round(calibrate(float(r)), 3) for r in raw]}
