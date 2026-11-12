"""Research (read-only): one row per projected NBA player-game that was played, for a model version and seasons.

    python research/2026-11-prop-stability/nba_rows.py <version> <season,season,...> <sims> <out.parquet> [overrides.json]

overrides: settings changed for an isolated experiment ({"minutes_gap_fill": 0.5}); recorded in every row as "experiment".

Uses the backtest's walk-forward machinery unchanged (modelroom.nba.props.backtest.Runner: each game day projected with
games before that day only, seed = the date) and the version's own params file. Records the projection's inputs and
the raw simulated ladder probabilities (calibration is applied in the analysis, with the version's own calibration),
plus the box score. Writes nothing but the output file; the ledger, params and committed results are untouched.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from modelroom.nba.props import backtest as B
from modelroom.nba.props import inputs as I
from modelroom.nba.props import model as M
from modelroom.nba.props.config import MARKETS, PropParams
from modelroom.nba.props.pipeline import _params_file

BOX = ["pts", "reb", "ast", "pra", "fg3m", "stl", "blk", "minutes", "fga", "fg3a", "fta", "fgm", "ftm", "tov", "oreb", "starter"]


def main(version: str, seasons: list[int], sims: int, out: str, overrides: dict | None = None) -> None:
    exp_tag = json.dumps(overrides, sort_keys=True) if overrides else None
    t0 = time.time()
    inp = I.load()
    overrides = dict(overrides or {})
    if overrides.pop("_exclude_playoffs", False):
        # Experiment: playoff / play-in games removed from every player's history (and not projected).
        keep = inp.player_games["season_type"].astype(str).isin(["2", "regular"])
        inp = replace(inp, player_games=inp.player_games[keep].reset_index(drop=True)) if hasattr(inp, "__dataclass_fields__") else inp
        if not hasattr(inp, "__dataclass_fields__"):
            raise SystemExit("inputs object is not a dataclass")
    run = B.Runner(inp)
    p = PropParams.load(_params_file(version))
    p = replace(p, settings=replace(p.settings, sims=sims, **(overrides or {})))
    tag = json.dumps(overrides or {}, sort_keys=True) if not exp_tag else exp_tag
    pg = inp.player_games
    played = pg[pg["played"]]
    box = {(g, pid): r for g, pid, r in zip(played["game_id"], played["player_id"], played[BOX].to_dict("records"))}
    rows = []
    g = inp.games
    for season in seasons:
        for day in run.days.get(season, []):
            dg = g[(g["game_date"].astype(str) == day) & (g["status"] == "final")]
            ctx = run.ctx(day, season, p.settings)
            run._ctx.clear()  # one day at a time (a season of cached contexts runs out of memory)
            projs = M.project_games(ctx, dg, p, seed=int(day.replace("-", "")))
            if day not in run._base:
                if len(run._base) > 400:
                    run._base.clear()
                run._base[day] = B._baseline(pg, run.pg_dates, pd.Timestamp(day), season)
            base = run._base[day]
            margin = dict(zip(dg["game_id"], dg["proj_margin"]))
            home = dict(zip(dg["game_id"], dg["home_abbr"]))
            st = dict(zip(dg["game_id"], dg.get("season_type", pd.Series(index=dg.index, dtype=object))))
            for x in projs:
                k = (x.game_id, x.player_id)
                a = box.get(k)
                if a is None:
                    continue
                hist = base.get(x.player_id)
                P = ctx.players.loc[x.player_id]
                inp_ = x.inputs
                r = {"version": version, "experiment": tag, "season": season, "date": day, "game_id": x.game_id, "player_id": x.player_id, "team": x.team,
                     "group": x.group, "home": x.team == home.get(x.game_id), "season_type": st.get(x.game_id),
                     "proj_margin": float(margin.get(x.game_id) or 0.0) * (1 if x.team == home.get(x.game_id) else -1),
                     "proj_min": inp_["projected_minutes"], "usual_min": float(P["minutes_when_playing"]), "minutes_high": float(P["minutes_high"]) if pd.notna(P["minutes_high"]) else np.nan,
                     "starter_rate": inp_["starter_rate"], "appear_rate": inp_["appear_rate_last10"], "usage_pm": float(P["usage_pm"]) if pd.notna(P["usage_pm"]) else np.nan,
                     "usage_freed": inp_["usage_freed_by_absences"], "teammates_out": inp_["teammates_out"] or "", "pace_factor": inp_["pace_factor"],
                     "minutes_scale": inp_["minutes_scale"], "n_games": int(P["n_games"]), "n_minutes": float(P["n_minutes"]), "support": x.support()[0],
                     "eligible": bool(B.eligible(x)),
                     "hist_min10": float(np.mean(hist["minutes"][-10:])) if hist is not None and len(hist["minutes"]) else np.nan,
                     "sim_min_mean": float(np.mean(x.sims["minutes"]))}
                for kk, v in a.items():
                    r[f"a_{kk}"] = float(v) if v is not None else np.nan
                for mkey, m in MARKETS.items():
                    s = m["stat"]
                    r[f"m_{mkey}"] = x.mean(s)
                    r[f"med_{mkey}"] = float(np.median(x.sims[s]))
                    r[f"lad_{mkey}"] = [x.prob(s, k2) for k2 in m["ladder"]]
                    hv = hist[s] if hist is not None else None
                    r[f"base_{mkey}"] = [(float(np.sum(hv >= k2)) + 0.5) / (len(hv) + 1.0) for k2 in m["ladder"]] if hv is not None and len(hv) else None
                    r[f"hm_{mkey}"] = float(np.mean(hv)) if hv is not None and len(hv) else np.nan
                c = (inp_.get("contributions") or {}).get("stats") or {}
                for s in ("pts", "pra"):
                    for kk, v in (c.get(s) or {}).items():
                        r[f"c_{s}_{kk}"] = v
                rows.append(r)
        # one file per season keeps memory flat
        pd.DataFrame(rows).to_parquet(out.replace(".parquet", f"_{season}.parquet"))
        print(version, season, len(rows), round(time.time() - t0), flush=True)
        rows = []
    print("done", out, round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], [int(s) for s in sys.argv[2].split(",")], int(sys.argv[3]), sys.argv[4], json.loads(sys.argv[5]) if len(sys.argv) > 5 else None)
