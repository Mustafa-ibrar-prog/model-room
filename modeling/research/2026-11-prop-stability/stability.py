"""Research (read-only): season-by-season metrics from the research rows (nba_rows.py / nfl_rows.py output).

    python research/2026-11-prop-stability/stability.py <league> <rows.parquet> <version> <out.json>

Row selection reproduces the committed backtests so the per-season figures add up to them:
  NBA  players whose last-10-game average is 18+ minutes (KEEP_ALL), ladder rows where the player's own recent hit
       rate is 5-95% (propeval.fixed_rows) -- "the same rows as 0.1.0" in nba-props-backtest-0.2.0.json.
  NFL  players the model projects with a real role (backtest.eligible), ladder rows with raw probability 2-98%.
Probabilities are calibrated with the version's own params (fit on 2021-22, as committed).

Per season x market (and per role group): player-games, MAE, bias, Brier, log loss, calibration error, the average
predicted vs actual rate of "k or more" over the ladder, and Over/Under at each player-game's most balanced rung
(lean = more than 3 points from 50%): how often the leaned side happened vs how often the model said it would.
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

EPS = 1e-6
LEAN = 0.03


def calib(p: np.ndarray, ab) -> np.ndarray:
    if not ab:
        return p
    q = np.clip(p, 1e-4, 1 - 1e-4)
    return 1 / (1 + np.exp(-(ab[0] + ab[1] * np.log(q / (1 - q)))))


def ece(p, y, b=10):
    if len(p) == 0:
        return float("nan")
    i = np.clip((p * b).astype(int), 0, b - 1)
    return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))


def ladder_rows(r: pd.DataFrame, league: str, mkey: str, ladder: list, cal) -> pd.DataFrame:
    """Explode one market's ladder into rows (p calibrated, y, baseline p), with the row filter of the committed backtest."""
    ycol = f"a_{STAT[league][mkey]}" if league == "nba" else f"y_{mkey}"
    d = r.dropna(subset=[f"m_{mkey}", ycol])
    if d.empty:
        return pd.DataFrame()
    P = np.array(d[f"lad_{mkey}"].tolist(), float)
    B = np.array([b if b is not None and len(b) == len(ladder) else [np.nan] * len(ladder) for b in d[f"base_{mkey}"]], float)
    Y = (d[ycol].to_numpy(float)[:, None] >= np.asarray(ladder, float)[None, :]).astype(float)
    out = pd.DataFrame({"i": np.repeat(np.arange(len(d)), len(ladder)), "k": np.tile(ladder, len(d)), "p_raw": P.ravel(), "b": B.ravel(), "y": Y.ravel()})
    if league == "nba":
        out = out[out["b"].notna() & (out["b"] >= 0.05) & (out["b"] <= 0.95)]
    else:
        out = out[(out["p_raw"] >= 0.02) & (out["p_raw"] <= 0.98)]
    out["p"] = calib(out["p_raw"].to_numpy(float), cal)
    return out


def metrics(d: pd.DataFrame, lad: pd.DataFrame, league: str, mkey: str) -> dict:
    ycol = f"a_{STAT[league][mkey]}" if league == "nba" else f"y_{mkey}"
    m = d.dropna(subset=[f"m_{mkey}", ycol])
    e = m[f"m_{mkey}"] - m[ycol]
    o = {"player_games": int(len(m)), "mae": round(float(e.abs().mean()), 3) if len(m) else None, "bias": round(float(e.mean()), 3) if len(m) else None,
         "recent_avg_mae": round(float((m[f"hm_{mkey}"] - m[ycol]).abs().mean()), 3) if m[f"hm_{mkey}"].notna().any() else None}
    if len(lad):
        p, y = lad["p"].to_numpy(float), lad["y"].to_numpy(float)
        pc = np.clip(p, EPS, 1 - EPS)
        o.update(ladder_rows=int(len(lad)), brier=round(float(np.mean((p - y) ** 2)), 5),
                 log_loss=round(float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))), 5), ece=round(ece(p, y), 4),
                 pred_rate=round(float(p.mean()), 4), actual_rate=round(float(y.mean()), 4))
        b = lad.dropna(subset=["b"])
        if len(b):
            bp = np.clip(b["b"].to_numpy(float), EPS, 1 - EPS)
            yb = b["y"].to_numpy(float)
            o["baseline_log_loss"] = round(float(-np.mean(yb * np.log(bp) + (1 - yb) * np.log(1 - bp))), 5)
            pp = np.clip(b["p"].to_numpy(float), EPS, 1 - EPS)
            o["model_log_loss_same_rows"] = round(float(-np.mean(yb * np.log(pp) + (1 - yb) * np.log(1 - pp))), 5)
        # Over/Under at each player-game's most balanced rung
        lad = lad.assign(dist=(lad["p"] - 0.5).abs())
        mid = lad.loc[lad.groupby("i")["dist"].idxmin()]
        mid = mid[(mid["p"] >= 0.2) & (mid["p"] <= 0.8)]
        ov, un = mid[mid["p"] > 0.5 + LEAN], mid[mid["p"] < 0.5 - LEAN]
        o["ou"] = {"n": int(len(mid)), "pred_over": round(float(mid["p"].mean()), 4) if len(mid) else None, "actual_over": round(float(mid["y"].mean()), 4) if len(mid) else None,
                   "over_leans": {"n": int(len(ov)), "expected": round(float(ov["p"].mean()), 4) if len(ov) else None, "hit": round(float(ov["y"].mean()), 4) if len(ov) else None},
                   "under_leans": {"n": int(len(un)), "expected": round(float(1 - un["p"].mean()), 4) if len(un) else None, "hit": round(float(1 - un["y"].mean()), 4) if len(un) else None}}
    return o


STAT = {"nba": {"points": "pts", "rebounds": "reb", "assists": "ast", "pra": "pra", "threes": "fg3m", "steals": "stl", "blocks": "blk"}}


def groups(r: pd.DataFrame, league: str) -> dict:
    if league == "nba":
        role = np.where(r["starter_rate"] > 0.5, "starter", "bench")
        band = pd.cut(r["proj_min"], [0, 24, 30, 36, 60], labels=["<24 min", "24-30 min", "30-36 min", "36+ min"], right=False).astype(str)
        q = r.groupby("season")["usage_pm"].transform(lambda s: s.rank(pct=True))
        use = pd.cut(q, [0, 1 / 3, 2 / 3, 1.0001], labels=["low usage", "mid usage", "high usage"]).astype(str)
        month = pd.to_datetime(r["date"]).dt.month.map(lambda m: "Oct-Nov" if m in (10, 11) else "Dec-Jan" if m in (12, 1) else "Feb-Apr" if m in (2, 3, 4) else "playoffs")
        return {"role": pd.Series(role, index=r.index), "minutes_band": band, "usage_tier": use, "month": month}
    tier = r.groupby(["season", "group"])["m_targets"].transform(lambda s: s.rank(pct=True))
    opp = np.where(r["group"] == "QB", "QB", np.where(r["group"] == "RB", "RB", r["group"] + np.where(tier > 0.5, " (top half by targets)", " (bottom half)")))
    return {"position": r["group"], "role": pd.Series(opp, index=r.index)}


def run(league: str, rows: str, version: str, out: str) -> dict:
    if league == "nba":
        from modelroom.nba.props.config import MARKETS, PropParams
        from modelroom.nba.props.pipeline import _params_file
        params = PropParams.load(_params_file(version))
        r = pd.read_parquet(rows)
        r = r[r["hist_min10"] >= 18.0]
    else:
        from modelroom.nfl.props.config import MARKETS, PropParams
        from modelroom.nfl.props.pipeline import VERSIONS
        params = PropParams.load(VERSIONS[version])
        r = pd.read_parquet(rows)
        r = r[r["eligible"]]
    r = r.reset_index(drop=True)
    res = {"league": league, "version": version, "rows_file": rows.split("/")[-1], "calibration": params.calibration, "seasons": {}, "by_group": {}, "pooled": {}}
    G = groups(r, league)
    for mkey, m in MARKETS.items():
        cal = params.calibration.get(mkey)
        for season, d in r.groupby("season"):
            lad = ladder_rows(d, league, mkey, m["ladder"], cal)
            if len(d.dropna(subset=[f"m_{mkey}"])):
                res["seasons"].setdefault(str(season), {})[mkey] = metrics(d, lad, league, mkey)
        for gname, g in G.items():
            for gv, d in r.groupby(g):
                for season_set, label in (((2023, 2024, 2025, 2026), "test"), ((2021, 2022), "tune"), ((2027,), "current")):
                    dd = d[d["season"].isin(season_set)]
                    if dd.dropna(subset=[f"m_{mkey}"]).empty:
                        continue
                    lad = ladder_rows(dd, league, mkey, m["ladder"], cal)
                    res["by_group"].setdefault(f"{gname}:{gv}", {}).setdefault(label, {})[mkey] = metrics(dd, lad, league, mkey)
        test = r[r["season"].isin((2023, 2024, 2025, 2026))]
        if len(test.dropna(subset=[f"m_{mkey}"])):
            res["pooled"][mkey] = metrics(test, ladder_rows(test, league, mkey, m["ladder"], cal), league, mkey)
    with open(out, "w") as f:
        json.dump(res, f, indent=1, default=lambda x: None if isinstance(x, float) and math.isnan(x) else str(x))
    return res


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
