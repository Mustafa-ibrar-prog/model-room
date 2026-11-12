"""Compare isolated NBA experiments with 0.2.0 on the same seasons and player-games (research)."""
import glob
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "research/2026-11-prop-stability")
import stability as ST  # noqa: E402
from modelroom.nba.props.config import MARKETS, PropParams  # noqa: E402
from modelroom.nba.props.pipeline import _params_file  # noqa: E402

O = "data/output/research"
CAL = PropParams.load(_params_file("0.2.0")).calibration


def load(pattern):
    fs = sorted(glob.glob(f"{O}/{pattern}"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True) if fs else pd.DataFrame()


def summary(r: pd.DataFrame, regular_only=True) -> dict:
    r = r[r["hist_min10"] >= 18].reset_index(drop=True)
    if regular_only and "season_type" in r:
        r = r[r["season_type"].astype(str).isin(["regular", "2", "None"]) | r["season_type"].isna()]
    out = {}
    role = np.where(r["starter_rate"] > 0.5, "starter", "bench")
    for season, d in r.groupby("season"):
        s = {"player_games": int(len(d)), "minutes_bias": round(float((d["sim_min_mean"] - d["a_minutes"]).mean()), 3)}
        for mk in ("points", "pra", "rebounds", "assists", "threes"):
            lad = ST.ladder_rows(d.reset_index(drop=True), "nba", mk, MARKETS[mk]["ladder"], CAL.get(mk))
            m = ST.metrics(d.reset_index(drop=True), lad, "nba", mk)
            s[mk] = {"bias": m["bias"], "mae": m["mae"], "log_loss": m.get("log_loss"), "ece": m.get("ece"),
                     "over_hit": m["ou"]["over_leans"]["hit"], "over_exp": m["ou"]["over_leans"]["expected"],
                     "under_hit": m["ou"]["under_leans"]["hit"], "under_exp": m["ou"]["under_leans"]["expected"]}
        for rl in ("starter", "bench"):
            dd = d[role[d.index] == rl] if False else d[np.where(d["starter_rate"] > 0.5, "starter", "bench") == rl]
            s[f"points_bias_{rl}"] = round(float((dd["m_points"] - dd["a_pts"]).mean()), 3)
        out[int(season)] = s
    return out


if __name__ == "__main__":
    base = pd.concat([load("nba_0.2.0_hist_*.parquet"), load("nba_0.2.0_2027.parquet")], ignore_index=True)
    res = {"0.2.0": summary(base[base["season"].isin([2025, 2026, 2027])])}
    for tag, pat in (("minutes_gap_fill 0.5", "x1_gapfill05*.parquet"), ("usage_boost 0", "x2_usage0*.parquet"), ("season_carry 0.25", "x3_carry025*.parquet"),
                     ("no playoff history", "x4_noplayoffs*.parquet"), ("minutes_gap_fill 0", "x5_gapfill0*.parquet")):
        d = load(pat)
        if len(d):
            res[tag] = summary(d)
    json.dump(res, open(f"{O}/experiments_nba.json", "w"), indent=1)
    for tag, v in res.items():
        for s, x in v.items():
            print(f"{tag:22s} {s} n={x['player_games']:>5} min_bias={x['minutes_bias']:+.2f} pts_bias={x['points']['bias']:+.2f} (starter {x['points_bias_starter']:+.2f} bench {x['points_bias_bench']:+.2f}) "
                  f"pra_bias={x['pra']['bias']:+.2f} pts_ll={x['points']['log_loss']} pra_ll={x['pra']['log_loss']} reb_ll={x['rebounds']['log_loss']} ast_ll={x['assists']['log_loss']} "
                  f"ptsOU over {x['points']['over_hit']}/{x['points']['over_exp']}")
