"""Research (read-only): one row per projected NFL player-game that was played, for a model version and seasons.

    python research/2026-11-prop-stability/nfl_rows.py <version> <season,...> <sims> <out.parquet>

Uses the backtest's walk-forward machinery unchanged (modelroom.nfl.props.backtest.Runner.walk: each week projected
with earlier games only, seed = season x 100 + week, the version's own params incl. its volume model). Records
the raw simulated ladder probabilities (calibration applied in the analysis) and the box score. 0.1.1 here is
0.1.0's model + the inexperienced-QB factor; its live injury feed did not exist historically (nflverse injury
reports are used for every version, as in the 0.1.0 backtest).
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from modelroom.nfl.props import backtest as B
from modelroom.nfl.props import inputs as I
from modelroom.nfl.props.config import MARKETS, PropParams
from modelroom.nfl.props.pipeline import VERSIONS

STATS = ["pass_att", "pass_cmp", "pass_yds", "pass_td", "ints", "carries", "rush_yds", "rush_td", "targets", "receptions", "rec_yds",
         "rec_td", "long_rec", "offense_snaps", "offense_pct", "team_pass_att", "team_carries"]


def main(version: str, seasons: list[int], sims: int, out: str) -> None:
    t0 = time.time()
    inp = I.load(set(seasons))
    run = B.Runner(inp)
    p = PropParams.load(VERSIONS[version])
    p = replace(p, settings=replace(p.settings, sims=sims))
    rows = []
    for season in seasons:
        weeks = sorted(inp.games.loc[(inp.games["season"] == season) & (inp.games["status"] == "final"), "week"].unique())
        for wk in weeks:
            for rec in run.walk([season], p, only_week=int(wk)):
                x, a, base = rec["proj"], rec["actual"], rec["base"]
                r = {"version": version, "season": season, "week": int(wk), "game_id": x.game_id, "player_id": x.player_id, "group": x.group,
                     "team": x.team, "eligible": bool(B.eligible(x)), "eligible_hist": bool(B.eligible_history(x, base)),
                     "injury_status": x.inputs.get("injury_status"), "target_share": x.inputs.get("target_share"), "carry_share": x.inputs.get("carry_share"),
                     "team_pass_attempts": x.inputs.get("team_pass_attempts"), "team_carries_proj": x.inputs.get("team_carries"),
                     "snap_recent": x.inputs.get("snap_share_recent"), "n_games": (x.inputs.get("sample") or {}).get("games"),
                     "m_targets": x.mean("targets"), "m_carries": x.mean("carries")}
                act = {"rush_rec_yds": float(a["rush_yds"]) + float(a["rec_yds"]), "td_any": float(a["rush_td"]) + float(a["rec_td"])}
                for s in STATS:
                    r[f"a_{s}"] = float(a[s]) if s in a and pd.notna(a[s]) else np.nan
                for mkey, m in MARKETS.items():
                    if x.group not in m["positions"]:
                        continue
                    s = m["stat"]
                    y = act.get(s, a.get(s, np.nan) if hasattr(a, "get") else np.nan)
                    r[f"y_{mkey}"] = float(y) if y is not None and pd.notna(y) else np.nan
                    r[f"m_{mkey}"] = x.mean(s)
                    r[f"lad_{mkey}"] = [x.prob(s, k) for k in m["ladder"]]
                    hv = base[s].to_numpy(float) if base is not None and s in base else None
                    r[f"base_{mkey}"] = [(float(np.sum(hv >= k)) + 0.5) / (len(hv) + 1.0) for k in m["ladder"]] if hv is not None and len(hv) else None
                    r[f"hm_{mkey}"] = float(np.mean(hv)) if hv is not None and len(hv) else np.nan
                rows.append(r)
        print(version, season, len(rows), round(time.time() - t0), flush=True)
    pd.DataFrame(rows).to_parquet(out)
    print("done", out, len(rows), round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], [int(s) for s in sys.argv[2].split(",")], int(sys.argv[3]), sys.argv[4])
