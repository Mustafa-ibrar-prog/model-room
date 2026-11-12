"""Research (read-only): decompose NBA projection bias into minutes and per-minute-rate parts, by subgroup."""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd


def prep(r: pd.DataFrame) -> pd.DataFrame:
    r = r.copy()
    r["role"] = np.where(r["starter_rate"] > 0.5, "starter", "bench")
    r["band"] = pd.cut(r["proj_min"], [0, 18, 24, 30, 36, 60], labels=["<18", "18-24", "24-30", "30-36", "36+"], right=False)
    q = r.groupby("season")["usage_pm"].transform(lambda s: s.rank(pct=True))
    r["usage_tier"] = pd.cut(q, [0, 1 / 3, 2 / 3, 1.0001], labels=["low", "mid", "high"])
    r["absence"] = np.where(r["teammates_out"].str.len() > 0, "teammate out", "none")
    for s, a in (("points", "pts"), ("pra", "pra"), ("rebounds", "reb"), ("assists", "ast"), ("threes", "fg3m")):
        r[f"bias_{s}"] = r[f"m_{s}"] - r[f"a_{a}"]
        # minutes / rate split: projected per-minute = simulated mean / simulated mean minutes
        rate_p = r[f"m_{s}"] / r["sim_min_mean"].clip(lower=1)
        rate_a = r[f"a_{a}"] / r["a_minutes"].clip(lower=1)
        r[f"minpart_{s}"] = (r["sim_min_mean"] - r["a_minutes"]) * rate_p
        r[f"ratepart_{s}"] = r["a_minutes"] * (rate_p - rate_a)
    r["bias_min"] = r["sim_min_mean"] - r["a_minutes"]
    r["bias_projmin"] = r["proj_min"] - r["a_minutes"]
    return r


def table(r: pd.DataFrame, by: str, stats=("points", "pra")) -> pd.DataFrame:
    agg = {"n": ("bias_min", "size"), "minutes_bias": ("bias_min", "mean")}
    for s in stats:
        agg[f"{s}_bias"] = (f"bias_{s}", "mean")
        agg[f"{s}_from_minutes"] = (f"minpart_{s}", "mean")
        agg[f"{s}_from_rate"] = (f"ratepart_{s}", "mean")
    return r.groupby(by, observed=True).agg(**agg).round(3)


if __name__ == "__main__":
    r = prep(pd.read_parquet(sys.argv[1]))
    r = r[r["eligible"]]
    pd.set_option("display.width", 250)
    for by in ("season", "role", "band", "usage_tier", "absence"):
        print(table(r, by), "\n")
