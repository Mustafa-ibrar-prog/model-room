"""Read-only: every NFL skill candidate the 0.1.1 props engine considers, per team-game, with the inputs to its
target / carry share and what actually happened. No simulation; the share arithmetic below reproduces
model.project_team for 0.1.1 settings (opp_redistribution=proportional, questionable_model=none, no RB factors).
Output: rows_<seasons>.pkl (one row per candidate, incl. players ruled Out) for the allocation research."""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd
from modelroom.nfl.props import backtest as B, inputs as I, model as M, depth as DEPTH
from modelroom.nfl.props.config import PropParams

OUT = Path(__file__).with_name("data"); OUT.mkdir(exist_ok=True)
p = PropParams.load(Path("modelroom/nfl/props/params_0.1.1.json"))
s = p.settings
seasons = [int(x) for x in sys.argv[1:]]
inp = I.load(set(range(min(seasons) - 3, max(seasons) + 1)))
run = B.Runner(inp)
pg = inp.player_games
act = pg.groupby(["game_id", "player_id"]).agg(a_tgt=("targets", "sum"), a_car=("carries", "sum"), a_snaps=("offense_snaps", "sum"),
                                               a_pct=("offense_pct", "max")).reset_index()
rows, t0 = [], time.time()
for season, week, g in B._weeks(inp.games, seasons):
    cutoff = pd.Timestamp(g["game_date"].min())
    ctx = run.ctx(cutoff, season, s, week)
    ro, inj = I.week_slices(inp, season, week)
    dep = DEPTH.ranks(season, week, cutoff)
    for _, gm in g.iterrows():
        total = float(gm["proj_home_score"] + gm["proj_away_score"]); mg = float(gm["proj_home_score"] - gm["proj_away_score"])
        for team, opp, margin, qb in ((gm["home_team"], gm["away_team"], mg, gm.get("home_qb_id")), (gm["away_team"], gm["home_team"], -mg, gm.get("away_qb_id"))):
            qb = qb if isinstance(qb, str) else None
            c = M.candidates(ctx, team, ro, inj, gameday=False)
            active = c[~c["out"]]
            if active.empty:
                continue
            D = ctx.defense.loc[opp] if opp in ctx.defense.index else None
            mu_pa, mu_ru = M.team_volume(ctx, team, opp, margin, total, p)
            qbs = active[active["group"] == "QB"]
            starter = qb if qb in qbs.index else (qbs["pass_att_w"].idxmax() if len(qbs) and qbs["pass_att_w"].max() > 0 else None)
            allsk = c[c["group"].isin(["WR", "TE", "RB"])]
            skill = active[active["group"].isin(["WR", "TE", "RB"])]
            snap = lambda df: (df["snap_short"] / df["snap_long"]).replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(0.4, 1.6) ** s.snap_trend_strength
            mt = allsk["group"].map(lambda x: M._ratio(D, f"tshare_{x}", s.matchup_strength))
            t_pre = allsk["target_share"] * snap(allsk) * mt
            tw = t_pre.reindex(skill.index).sum()
            t_scale = float(np.clip(1.0 / tw, 0.75, 1.4)) if tw > 0 else 1.0
            rush = allsk.copy()
            if starter is not None:
                rush = pd.concat([rush, active.loc[[starter]]])
            c_pre = rush["carry_share"] * snap(rush).where(rush["group"] != "QB", 1.0)
            cw = c_pre.reindex([i for i in rush.index if i in active.index]).sum()
            c_scale = float(np.clip(1.0 / cw, 0.75, 1.4)) if cw > 0 else 1.0
            for pid, x in rush.iterrows():
                isact = pid in active.index
                rows.append({"season": season, "week": week, "game_id": gm["game_id"], "team": team, "opp": opp, "player_id": pid,
                             "group": x["group"], "injury": x["injury_status"], "out": bool(x["out"]), "starter_qb": pid == starter,
                             "mu_pa": mu_pa, "mu_ru": mu_ru, "t_scale": t_scale, "c_scale": c_scale,
                             "tshare_hist": x["target_share"], "cshare_hist": x["carry_share"], "snap_short": x["snap_short"], "snap_long": x["snap_long"],
                             "snap_mult": float(snap(rush.loc[[pid]]).iloc[0]), "match_t": float(mt.get(pid, 1.0)) if pid in mt.index else 1.0,
                             "p_play": x.get("p_play"), "games_season": x["games_season"], "n_games": x["n_games"], "games_w": x["games_w"],
                             "depth": dep.get(pid), "on_roster_status": None,
                             "t_share": float(t_pre[pid] * t_scale) if (isact and pid in t_pre.index) else 0.0,
                             "c_share": float(c_pre[pid] * c_scale) if isact else 0.0})
    print(season, week, len(rows), f"{time.time() - t0:.0f}s", flush=True)
R = pd.DataFrame(rows)
R["proj_tgt"] = R.t_share * R.mu_pa * 1.0
R["proj_car"] = R.c_share * R.mu_ru
R = R.merge(act, on=["game_id", "player_id"], how="left")
for c_ in ("a_tgt", "a_car", "a_snaps"):
    R[c_] = R[c_].fillna(0)
R["played"] = (R.a_snaps > 0) | (R.a_tgt + R.a_car > 0)
R.to_pickle(OUT / f"rows_{'_'.join(map(str, seasons))}.pkl")
print("saved", len(R))
