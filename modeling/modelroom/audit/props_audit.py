"""Phase 1 audit of the player-prop engines (read-only: no parameters, ledgers or boards are changed).

    python -m modelroom.audit.props_audit nba|nfl [--seasons 2025,2026] [--sims 1500]

Walks the held-out test seasons exactly like the backtests (each day/week projected from earlier games
only, current params.json incl. calibration) and keeps one row per player-game-market with:
  projection mean / median, actual, randomized PIT, projected vs actual opportunity (minutes, targets,
  carries, attempts), role, and the calibrated P(over) at
    * every ladder threshold (as the backtest scores), and
    * a "market-style" line: the player's last-10 average rounded to the next whole number
      (k = floor(avg) + 1, i.e. Over avg.5), the way books and exchanges usually hang a line.
Rows go to data/outputs/<league>/audit/rows_*.parquet; the summary is computed by summarize().
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common.paths import ensure, output_dir


def _pit(sims: np.ndarray, y: float, rng) -> float:
    """Randomized PIT for a discrete outcome: U ~ [P(X < y), P(X <= y)]."""
    lo = float(np.mean(sims < y))
    hi = float(np.mean(sims <= y))
    return lo + rng.random() * (hi - lo)


def _line(hist: np.ndarray | None) -> float | None:
    if hist is None or len(hist) < 5:
        return None
    return float(math.floor(float(np.mean(hist[-10:]))) + 1)


def _mline(hist: np.ndarray | None) -> float | None:
    """Median-style line: Over (last-10 median − 0.5), i.e. P(X >= ceil(median)); at least 1."""
    if hist is None or len(hist) < 5:
        return None
    return float(max(1, math.ceil(float(np.median(hist[-10:])))))


# ------------------------------------------------------------------ NBA
def _actual_availability(M, ctx, day_games, pg_day, mode: str = "actual") -> dict:
    """Perfect-information availability for testing 0.2.1's injury logic: every candidate is "out" unless he
    played in that game, "available" if he did. An UPPER BOUND on what an injury report can tell the model
    (a real report is less certain); never used for the live model."""
    played = set(pg_day.loc[pg_day["played"], "player_id"].astype(str))
    if mode == "report":
        # What an injury report would say: Out = absent for injury / illness / rest / suspension / personal, or not in
        # the box at all. A coach's-decision DNP was healthy and available, so he is not "out" for his teammates.
        coach = pg_day["reason"].fillna("").str.upper().str.contains("COACH")
        played = played | set(pg_day.loc[coach, "player_id"].astype(str))
    out = {}
    for g in day_games.itertuples():
        for team in (g.home_abbr, g.away_abbr):
            pool = ctx.players[ctx.players["team"] == team].index.astype(str)
            feed = pd.DataFrame([{"player_id": pid, "status": "available" if pid in played else "out", "raw_status": None, "source": "box",
                                  "kind": "official", "report_time": None, "restriction": False, "restriction_minutes": None, "detail": None}
                                 for pid in pool])
            out[(str(g.game_id), team)] = M.availability(feed, {}, False, None)
    return out


def nba_rows(seasons, sims: int, params_path=None, avail_mode: str | None = None) -> pd.DataFrame:
    from dataclasses import replace

    from modelroom.nba.props import backtest as B
    from modelroom.nba.props import inputs as I
    from modelroom.nba.props import model as M
    from modelroom.nba.props.config import MARKETS, PropParams

    p = PropParams.load(Path(params_path)) if params_path else PropParams.load()
    p = replace(p, settings=replace(p.settings, sims=sims))
    inp = I.load()
    run = B.Runner(inp)
    pg = inp.player_games
    mins = {(g, pid): m for g, pid, m in pg.loc[pg["played"], ["game_id", "player_id", "minutes"]].itertuples(index=False)}
    rng = np.random.default_rng(7)
    rows = []
    g = inp.games
    hist_av = None
    if avail_mode == "hist" and p.settings.injury_feed:
        import os

        from modelroom.audit import hist_reports
        hist_av, st = hist_reports.build(inp, [Path(x) for x in os.environ["MODELROOM_HIST_REPORTS"].split(",")])
        print("historical reports:", st, flush=True)
    for season in seasons:
        for day in run.days.get(season, []):
            day_games = g[(g["game_date"].astype(str) == day) & (g["status"] == "final")]
            ctx = run.ctx(day, season, p.settings)
            av = None
            if avail_mode == "hist" and hist_av is not None:
                from modelroom.nba.props import returns

                prior = pg[pd.to_datetime(pg["game_date"]) < pd.Timestamp(day)]
                back = returns.current_back(prior[prior["season"] == season], ctx.players.index.astype(str).tolist())
                av = {k: {**v, "back": back} for k in ((str(r.game_id), t) for r in day_games.itertuples() for t in (r.home_abbr, r.away_abbr)) if (v := hist_av.get(k))}
            elif avail_mode in ("actual", "report") and p.settings.injury_feed:
                from modelroom.nba.props import returns

                av = _actual_availability(M, ctx, day_games, pg[pg["game_id"].isin(day_games["game_id"])], avail_mode)
                prior = pg[pd.to_datetime(pg["game_date"]) < pd.Timestamp(day)]
                back = returns.current_back(prior[prior["season"] == season], ctx.players.index.astype(str).tolist())
                for v in av.values():
                    v["back"] = back
            projs = M.project_games(ctx, day_games, p, seed=int(day.replace("-", "")), avail=av)
            opp_of = {**{(str(r.game_id), r.home_abbr): r.away_abbr for r in day_games.itertuples()}, **{(str(r.game_id), r.away_abbr): r.home_abbr for r in day_games.itertuples()}}
            base = B._baseline(pg, run.pg_dates, pd.Timestamp(day), season)
            for x in projs:
                k = (x.game_id, x.player_id)
                if not B.eligible(x) or k not in run.actual:
                    continue
                a = run.actual[k]
                hist = base.get(x.player_id)
                common = {"season": season, "date": day, "game_id": x.game_id, "player_id": x.player_id, "name": x.name,
                          "group": x.group, "starter": x.inputs.get("starter_rate", 0) > 0.5,
                          "proj_min": x.inputs.get("projected_minutes"), "act_min": mins.get(k),
                          "support": x.support()[0], "teammates_out": bool(x.inputs.get("teammates_out")),
                          "n_out": len(str(x.inputs.get("teammates_out")).split(", ")) if x.inputs.get("teammates_out") else 0,
                          "has_report": bool(av and (str(x.game_id), x.team) in av),
                          "my_status": ((x.inputs.get("availability") or {}).get("status")),
                          "usage_freed": float(x.inputs.get("usage_freed_by_absences") or 0.0),
                          "team": x.team, "opp": opp_of.get((str(x.game_id), x.team)),
                          "returning": any("back from" in n for n in ((x.inputs.get("availability") or {}).get("notes") or []))}
                for mkey, m in MARKETS.items():
                    st = m["stat"]
                    s = x.sims[st]
                    y = float(a[st])
                    hv = hist[st] if hist is not None else None
                    line = _line(hv)
                    r = {**common, "market": mkey, "mean": float(s.mean()), "median": float(np.median(s)), "sd": float(s.std()),
                         "actual": y, "pit": _pit(s, y, rng), "l10": float(np.mean(hv[-10:])) if hv is not None and len(hv) else np.nan,
                         "line": line}
                    if line is not None:
                        r["p_line"] = p.calibrate(mkey, float(np.mean(s >= line)))
                        r["p_line_raw"] = float(np.mean(s >= line))
                        r["y_line"] = float(y >= line)
                    ml = _mline(hv)
                    if ml is not None:
                        r["mline"] = ml
                        r["p_mline"] = p.calibrate(mkey, float(np.mean(s >= ml)))
                        r["y_mline"] = float(y >= ml)
                    r["ladder"] = [(thr, p.calibrate(mkey, float(np.mean(s >= thr))), float(y >= thr)) for thr in m["ladder"]]
                    rows.append(r)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ NFL
def nfl_rows(seasons, sims: int, params_path=None) -> pd.DataFrame:
    from dataclasses import replace

    from modelroom.nfl.props import backtest as B
    from modelroom.nfl.props import inputs as I
    from modelroom.nfl.props.config import FIT_SEASONS, MARKETS, TEST_SEASONS, TUNE_SEASONS, PropParams

    p = PropParams.load(Path(params_path)) if params_path else PropParams.load()
    p = replace(p, settings=replace(p.settings, sims=sims))
    inp = I.load(set(FIT_SEASONS) | set(TUNE_SEASONS) | set(TEST_SEASONS))
    run = B.Runner(inp)
    rng = np.random.default_rng(7)
    rows = []
    for season in seasons:
        weeks = sorted(inp.games.loc[(inp.games["season"] == season) & (inp.games["status"] == "final"), "week"].unique())
        for wk in weeks:
            for rec in run.walk([season], p, only_week=int(wk)):
                x = rec["proj"]
                if not B.eligible(x):
                    continue
                a = rec["actual"]
                hist = rec["base"]
                act = {"rush_rec_yds": a["rush_yds"] + a["rec_yds"], "td_any": a["rush_td"] + a["rec_td"]}
                gid = rec["game_id"]
                common = {"season": season, "week": int(wk), "game_id": gid, "player_id": rec["player_id"], "name": rec["name"],
                          "group": x.group, "team": x.team, "opp": x.opp,
                          "qb_career_att": x.inputs.get("starting_qb_career_attempts"), "qb_note": bool(x.inputs.get("qb_note")), "proj_tgt": x.mean("targets"), "act_tgt": float(a.get("targets", np.nan)),
                          "proj_car": x.mean("carries"), "act_car": float(a.get("carries", np.nan)),
                          "proj_att": x.mean("pass_att"), "act_att": float(a.get("pass_att", np.nan))}
                for mkey, m in MARKETS.items():
                    if x.group not in m["positions"]:
                        continue
                    st = m["stat"]
                    y = float(act.get(st, a.get(st, np.nan)))
                    if np.isnan(y):
                        continue
                    s = x.sims[st]
                    hv = hist[st].to_numpy(float) if hist is not None and st in hist else None
                    line = _line(hv)
                    r = {**common, "market": mkey, "mean": float(s.mean()), "median": float(np.median(s)), "sd": float(s.std()),
                         "actual": y, "pit": _pit(s, y, rng), "l10": float(np.mean(hv[-10:])) if hv is not None and len(hv) else np.nan,
                         "line": line, "support": x.support(mkey)[0]}
                    if line is not None:
                        r["p_line"] = p.calibrate(mkey, float(np.mean(s >= line)))
                        r["p_line_raw"] = float(np.mean(s >= line))
                        r["y_line"] = float(y >= line)
                    ml = _mline(hv)
                    if ml is not None:
                        r["mline"] = ml
                        r["p_mline"] = p.calibrate(mkey, float(np.mean(s >= ml)))
                        r["y_mline"] = float(y >= ml)
                    r["ladder"] = [(k, p.calibrate(mkey, float(np.mean(s >= k))), float(y >= k)) for k in m["ladder"]]
                    rows.append(r)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ summary
def _cal(p: np.ndarray, y: np.ndarray, bins=10) -> dict:
    """ECE and reliability (equal-width bins)."""
    if len(p) == 0:
        return {"n": 0}
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    rel, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        ece += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
        rel.append({"bin": f"{b/bins:.1f}-{(b+1)/bins:.1f}", "n": int(m.sum()), "pred": round(float(p[m].mean()), 4), "actual": round(float(y[m].mean()), 4)})
    eps = 1e-6
    ll = float(-np.mean(y * np.log(np.clip(p, eps, 1)) + (1 - y) * np.log(np.clip(1 - p, eps, 1))))
    return {"n": int(len(p)), "pred": round(float(p.mean()), 4), "actual": round(float(y.mean()), 4), "ece": round(ece, 4),
            "log_loss": round(ll, 4), "brier": round(float(np.mean((p - y) ** 2)), 4), "reliability": rel}


def _side(p: np.ndarray, y: np.ndarray) -> dict:
    """Over leans (p > .5) and Under leans (p < .5) calibrated separately, each on its own side."""
    o, u = p > 0.5, p < 0.5
    return {"over_share": round(float(o.mean()), 4), "under_share": round(float(u.mean()), 4),
            "over": {k: v for k, v in _cal(p[o], y[o]).items() if k != "reliability"},
            "under": {k: v for k, v in _cal(1 - p[u], 1 - y[u]).items() if k != "reliability"}}


def summarize(df: pd.DataFrame, league: str) -> dict:
    out = {"league": league, "rows": int(len(df)), "seasons": sorted(df["season"].unique().tolist())}
    # 1. Bias of the projection itself
    bias = []
    for mk, d in df.groupby("market"):
        err = d["mean"] - d["actual"]
        bias.append({"market": mk, "n": len(d), "mean_proj": round(d["mean"].mean(), 3), "mean_actual": round(d["actual"].mean(), 3),
                     "bias": round(err.mean(), 3), "bias_pct": round(100 * err.mean() / max(d["actual"].mean(), 1e-9), 2),
                     "median_proj": round(d["median"].mean(), 3), "median_actual": round(d["actual"].median(), 3),
                     "mae": round(err.abs().mean(), 3), "rmse": round(float(np.sqrt((err ** 2).mean())), 3),
                     "l10_mae": round((d["l10"] - d["actual"]).abs().mean(), 3),
                     "pit_mean": round(d["pit"].mean(), 4),
                     "pit_tails": round(float(((d["pit"] < 0.1) | (d["pit"] > 0.9)).mean()), 4),
                     "pit_center": round(float(((d["pit"] > 0.25) & (d["pit"] < 0.75)).mean()), 4),
                     "sd_ratio": round(float(d["sd"].mean() / max((d["mean"] - d["actual"]).std(), 1e-9)), 3)})
    out["bias_by_market"] = bias
    # 2. Over / Under at the market-style line
    L = df.dropna(subset=["p_line"])
    out["market_line"] = {"all": _side(L["p_line"].to_numpy(), L["y_line"].to_numpy()),
                          "calibration": _cal(L["p_line"].to_numpy(), L["y_line"].to_numpy()),
                          "raw_uncalibrated_over_share": round(float((L["p_line_raw"] > 0.5).mean()), 4)}
    M2 = df.dropna(subset=["p_mline"]) if "p_mline" in df else df.iloc[0:0]
    if len(M2):
        out["median_line"] = {"all": _side(M2["p_mline"].to_numpy(), M2["y_mline"].to_numpy()),
                              "by_market": {mk: {**_side(d["p_mline"].to_numpy(), d["y_mline"].to_numpy()), "actual_over_rate": round(float(d["y_mline"].mean()), 4),
                                                 "pred_over_rate": round(float(d["p_mline"].mean()), 4), "n": len(d)} for mk, d in M2.groupby("market")}}
    out["market_line_by_market"] = {mk: {**_side(d["p_line"].to_numpy(), d["y_line"].to_numpy()),
                                         "actual_over_rate": round(float(d["y_line"].mean()), 4), "n": len(d)}
                                    for mk, d in L.groupby("market")}
    # 3. Ladder (what the backtest scores), by side
    lad = [(r.market, r.season, t, pp, yy) for r in df[["market", "season", "ladder"]].itertuples(index=False) for (t, pp, yy) in r.ladder]
    lad = pd.DataFrame(lad, columns=["market", "season", "threshold", "p", "y"])
    lad = lad[(lad["p"] >= 0.02) & (lad["p"] <= 0.98)]
    out["ladder"] = {"all": _side(lad["p"].to_numpy(), lad["y"].to_numpy()), "calibration": _cal(lad["p"].to_numpy(), lad["y"].to_numpy())}
    out["ladder_by_season"] = {int(s): {k: v for k, v in _cal(d["p"].to_numpy(), d["y"].to_numpy()).items() if k != "reliability"} for s, d in lad.groupby("season")}
    # 4. Breakdowns
    role_cols = ["group"] + (["starter", "support", "teammates_out"] if league == "nba" else ["support"])
    out["bias_by_role"] = {}
    for c in role_cols:
        out["bias_by_role"][c] = {str(v): {"n": len(d), "bias_pct_by_market": {mk: round(100 * (dd["mean"] - dd["actual"]).mean() / max(dd["actual"].mean(), 1e-9), 2)
                                                                             for mk, dd in d.groupby("market")},
                                           "market_line_over_share": round(float((d["p_line"] > 0.5).mean()), 4),
                                           "market_line_actual_over": round(float(d["y_line"].mean()), 4)}
                                   for v, d in df.dropna(subset=["p_line"]).groupby(c)}
    out["bias_by_season"] = {int(s): {mk: round(100 * (dd["mean"] - dd["actual"]).mean() / max(dd["actual"].mean(), 1e-9), 2) for mk, dd in d.groupby("market")}
                             for s, d in df.groupby("season")}
    # 5. Opportunity
    if league == "nba":
        d = df.drop_duplicates(["game_id", "player_id"]).dropna(subset=["act_min"])
        e = d["proj_min"] - d["act_min"]
        out["opportunity"] = {"minutes": {"n": len(d), "mean_proj": round(d["proj_min"].mean(), 2), "mean_actual": round(d["act_min"].mean(), 2),
                                          "bias": round(e.mean(), 2), "mae": round(e.abs().mean(), 2),
                                          "by_starter": {str(k): {"bias": round((g["proj_min"] - g["act_min"]).mean(), 2), "mae": round((g["proj_min"] - g["act_min"]).abs().mean(), 2), "n": len(g)} for k, g in d.groupby("starter")},
                                          "by_teammates_out": {str(k): {"bias": round((g["proj_min"] - g["act_min"]).mean(), 2), "n": len(g)} for k, g in d.groupby("teammates_out")},
                                          "big_misses_share": round(float((e.abs() > 8).mean()), 4)}}
    else:
        d = df.drop_duplicates(["game_id", "player_id"])
        opp = {}
        for k, pc, ac, grp in (("targets", "proj_tgt", "act_tgt", ("WR", "TE", "RB")), ("carries", "proj_car", "act_car", ("RB", "QB")), ("pass_att", "proj_att", "act_att", ("QB",))):
            g = d[d["group"].isin(grp)].dropna(subset=[ac])
            e = g[pc] - g[ac]
            opp[k] = {"n": len(g), "mean_proj": round(g[pc].mean(), 2), "mean_actual": round(g[ac].mean(), 2), "bias": round(e.mean(), 2), "mae": round(e.abs().mean(), 2),
                      "by_group": {gg: round((x[pc] - x[ac]).mean(), 2) for gg, x in g.groupby("group")}}
        out["opportunity"] = opp
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("league", choices=["nba", "nfl"])
    ap.add_argument("--seasons", default=None)
    ap.add_argument("--sims", type=int, default=1500)
    ap.add_argument("--params", default=None, help="params file (default: the live params.json)")
    ap.add_argument("--tag", default="", help="suffix for the output files")
    ap.add_argument("--avail", default=None, choices=[None, "actual", "report", "hist"], help="NBA 0.2.1: availability from who actually played (upper bound)")
    a = ap.parse_args(argv)
    if a.league == "nba":
        seasons = [int(s) for s in (a.seasons or "2025,2026").split(",")]
        df = nba_rows(seasons, a.sims, a.params, a.avail)
    else:
        seasons = [int(s) for s in (a.seasons or "2023,2024,2025").split(",")]
        df = nfl_rows(seasons, a.sims, a.params)
    d = ensure(output_dir(a.league) / "audit")
    tag = "_".join(map(str, seasons)) + (f"_{a.tag}" if a.tag else "")
    df.drop(columns=["ladder"]).to_parquet(d / f"rows_{tag}.parquet")
    df.to_pickle(d / f"rows_{tag}.pkl")
    s = summarize(df, a.league)
    (d / f"summary_{tag}.json").write_text(json.dumps(s, indent=2, default=str))
    print(json.dumps({k: s[k] for k in ("rows", "market_line", "ladder")}, indent=1, default=str)[:3000])


if __name__ == "__main__":
    main()
