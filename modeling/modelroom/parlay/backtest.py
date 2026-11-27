"""Parlay calibration backtest (TEST, Moose 2026-11-27).

Question: when the site combines the model's leg probabilities into one parlay probability, does that number match how
often such parlays actually hit? And does the correlation table beat simply multiplying the legs?

Data (all stored, no API calls):
  NBA  walk-forward projections for 2025-26 from the props model shown on TEST (params_0.2.0.json, its own
       calibration), graded against box scores. Correlation table re-estimated on 2021-22 to 2024-25 only, so the
       test season never informs the coefficients.
  NFL  walk-forward projections for 2025 from the TEST props model (params_0.1.1.json); table from 2018 to 2024.
  Live the model probabilities actually published in the NBA props ledger this season (2026-27), graded against box
       scores stored so far; table from 2021-22 to 2025-26.

Parlays are drawn at random from what a user could build: legs priced between 20% and 80% (where books hang lines),
each leg's side (over / under) chosen at random so negative dependence is tested too. Types: same player, teammates,
opponents, different games, three legs in one game, three legs in three games, two + two across two games.

    python -m modelroom.parlay.backtest [--out ../docs/models/results/parlay-backtest.json] [--quick]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import correlations as C
from .joint import bvnu, frechet, inv_phi, joint

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT.parent / "docs" / "models" / "results" / "parlay-backtest.json"
P_LO, P_HI = 0.20, 0.80

NBA_MARKET_TO_STAT = {"points": "points", "rebounds": "rebounds", "assists": "assists", "pra": "pra", "threes": "threes",
                      "steals": "steals", "blocks": "blocks"}
NFL_STAT_TO_NAME = {v[0]: k for k, v in C.NFL_STATS.items()} | {"rush_rec_yds": "rush_rec_yards", "td_any": "anytime_td"}


# ------------------------------------------------------------------------------------------------- relationship lookup
def pair_r(table: dict, a: dict, b: dict, nfl: bool) -> tuple[float, float, float] | None:
    """Correlation between two prop variables (player, market), oriented as 'more of each'. None = not measured with
    enough data (the parlay is then priced with bounds only)."""
    cells = table["cells"]
    if a["game_id"] != b["game_id"]:
        xg = table["cross_game"]
        if xg["independent"]:
            band = xg["engine_r_band"] or 0.0
            return (0.0, -band, band)
        c = xg["cells"].get(C.key("xgame", a["market"], b["market"]))
    elif a["player_id"] == b["player_id"]:
        c = cells.get(C.key("same", a["market"], b["market"]))
    else:
        rel = "team" if a["team"] == b["team"] else "opp"
        la = f"{a['pos']}:{a['market']}" if nfl else a["market"]
        lb = f"{b['pos']}:{b['market']}" if nfl else b["market"]
        c = cells.get(C.key(rel, la, lb))
    if not c or c["insufficient"] or c["r"] is None:
        return None
    return (c["r"], c["lo"], c["hi"])


def price(legs: list[dict], table: dict, nfl: bool, sims: int = 4_000) -> dict:
    """Independent product, copula point estimate and the correlation-uncertainty range, for prop legs."""
    vars_ = {}
    for l in legs:
        vars_.setdefault((l["player_id"], l["market"]), len(vars_))
    info = {v: l for l in legs for v in [vars_[(l["player_id"], l["market"])]]}
    n = len(vars_)
    R, Rlo, Rhi = np.eye(n), np.eye(n), np.eye(n)
    missing = False
    for i in range(n):
        for j in range(i + 1, n):
            r = pair_r(table, info[i], info[j], nfl)
            if r is None:
                missing = True
                continue
            R[i, j] = R[j, i] = r[0]
            Rlo[i, j] = Rlo[j, i] = r[1]
            Rhi[i, j] = Rhi[j, i] = r[2]
    jl = [{"var": vars_[(l["player_id"], l["market"])], "side": l["side"], "p": l["p"]} for l in legs]
    ps = [l["p"] for l in legs]
    out = {"indep": float(np.prod(ps)), "bounds": frechet(ps)}
    if missing:
        out["copula"] = None
        return out
    out["copula"] = joint(jl, R, sims=sims)["p"]
    return out


# ------------------------------------------------------------------------------------------------- parlay sampling
def candidates(rows: pd.DataFrame, rng) -> pd.DataFrame:
    """One line per player-game-market (random threshold in the 20-80% band) with a random side."""
    r = rows[(rows.p >= P_LO) & (rows.p <= P_HI)].copy()
    r["_u"] = rng.random(len(r))
    r = r.sort_values("_u").drop_duplicates(["game_id", "player_id", "market"])
    side = np.where(rng.random(len(r)) < 0.5, 1, -1)
    r["side"] = side
    r["p"] = np.where(side > 0, r.p, 1 - r.p)
    r["y"] = np.where(side > 0, r.y, 1 - r.y)
    return r.drop(columns="_u").reset_index(drop=True)


def sample(c: pd.DataFrame, kind: str, n: int, rng) -> list[list[dict]]:
    recs = c.to_dict("records")
    by_game: dict = {}
    by_pg: dict = {}
    by_date: dict = {}
    for i, r in enumerate(recs):
        by_game.setdefault(r["game_id"], []).append(i)
        by_pg.setdefault((r["game_id"], r["player_id"]), []).append(i)
        by_date.setdefault(r["date"], set()).add(r["game_id"])
    games = list(by_game)
    multi_dates = [d for d, g in by_date.items() if len(g) >= 2]
    multi3 = [d for d, g in by_date.items() if len(g) >= 3]
    out, tries = [], 0
    while len(out) < n and tries < n * 30:
        tries += 1
        if kind == "same_player_2":
            k = list(by_pg)[rng.integers(len(by_pg))]
            idx = by_pg[k]
            if len(idx) < 2:
                continue
            pick = rng.choice(idx, 2, replace=False)
        elif kind in ("teammates_2", "opponents_2"):
            g = by_game[games[rng.integers(len(games))]]
            a, b = rng.choice(g, 2, replace=False) if len(g) >= 2 else (None, None)
            if a is None or recs[a]["player_id"] == recs[b]["player_id"]:
                continue
            same_team = recs[a]["team"] == recs[b]["team"]
            if same_team != (kind == "teammates_2"):
                continue
            pick = [a, b]
        elif kind == "same_game_3":
            g = by_game[games[rng.integers(len(games))]]
            if len(g) < 3:
                continue
            pick = rng.choice(g, 3, replace=False)
            if len({(recs[i]["player_id"], recs[i]["market"]) for i in pick}) < 3:
                continue
        elif kind in ("cross_game_2", "cross_game_3"):
            pool = multi_dates if kind == "cross_game_2" else multi3
            if not pool:
                break
            d = pool[rng.integers(len(pool))]
            gs = rng.choice(sorted(by_date[d]), 2 if kind == "cross_game_2" else 3, replace=False)
            pick = [rng.choice(by_game[g]) for g in gs]
        elif kind == "two_plus_two_4":
            if not multi_dates:
                break
            d = multi_dates[rng.integers(len(multi_dates))]
            gs = rng.choice(sorted(by_date[d]), 2, replace=False)
            if len(by_game[gs[0]]) < 2 or len(by_game[gs[1]]) < 2:
                continue
            pick = list(rng.choice(by_game[gs[0]], 2, replace=False)) + list(rng.choice(by_game[gs[1]], 2, replace=False))
            if len({(recs[i]["player_id"], recs[i]["market"]) for i in pick}) < 4:
                continue
        else:
            raise ValueError(kind)
        out.append([recs[int(i)] for i in pick])
    return out


KINDS = {"same_player_2": 4000, "teammates_2": 4000, "opponents_2": 4000, "cross_game_2": 4000,
         "same_game_3": 2500, "cross_game_3": 2500, "two_plus_two_4": 2000}


# ------------------------------------------------------------------------------------------------- scoring
def ll(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def calib_bins(p: np.ndarray, y: np.ndarray, edges=(0, .05, .1, .15, .2, .25, .3, .4, .5, .65, 1.0001)) -> list[dict]:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 30:
            out.append({"bin": [lo, round(min(hi, 1.0), 2)], "n": int(m.sum()), "predicted": round(float(p[m].mean()), 4),
                        "actual": round(float(y[m].mean()), 4)})
    return out


def ece(p, y, edges=np.linspace(0, 1, 11)) -> float:
    tot = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi + (1e-9 if hi == 1 else 0))
        if m.any():
            tot += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(tot)


def summarize(res: pd.DataFrame, seed: int = 3) -> dict:
    priced = res[res.copula.notna()]
    out = {"parlays": int(len(res)), "priced_with_correlations": int(len(priced)), "bounds_only": int(res.copula.isna().sum())}
    if priced.empty:
        return out
    y, pi, pc = priced.y.to_numpy(float), priced.indep.to_numpy(float), priced.copula.to_numpy(float)
    d = ll(pi, y) - ll(pc, y)            # positive = copula better
    dates = priced.date.to_numpy()
    ud = np.unique(dates)
    rng = np.random.default_rng(seed)
    sums = pd.Series(d).groupby(dates).agg(["sum", "count"]).loc[ud].to_numpy()
    bs = []
    for _ in range(500):
        t = sums[rng.integers(0, len(sums), len(sums))].sum(axis=0)
        bs.append(t[0] / t[1])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    out.update({
        "hit_rate": round(float(y.mean()), 4),
        "mean_predicted_independent": round(float(pi.mean()), 4),
        "mean_predicted_correlated": round(float(pc.mean()), 4),
        "log_loss_independent": round(float(ll(pi, y).mean()), 5),
        "log_loss_correlated": round(float(ll(pc, y).mean()), 5),
        "log_loss_gain": round(float(d.mean()), 5),
        "log_loss_gain_95ci": [round(float(lo), 5), round(float(hi), 5)],
        "brier_independent": round(float(np.mean((pi - y) ** 2)), 5),
        "brier_correlated": round(float(np.mean((pc - y) ** 2)), 5),
        "ece_independent": round(ece(pi, y), 4),
        "ece_correlated": round(ece(pc, y), 4),
        "calibration_correlated": calib_bins(pc, y),
        "dates": int(len(ud)),
    })
    return out


def run_backtest(rows: pd.DataFrame, table: dict, nfl: bool, seed: int, scale: float) -> dict:
    rng = np.random.default_rng(seed)
    c = candidates(rows, rng)
    per, all_rows = {}, []
    for kind, n in KINDS.items():
        recs = []
        for legs in sample(c, kind, max(50, int(n * scale)), rng):
            pr = price(legs, table, nfl)
            recs.append({"kind": kind, "date": legs[0]["date"], "y": float(all(l["y"] > 0.5 for l in legs)),
                         "indep": pr["indep"], "copula": pr["copula"], "legs": len(legs)})
        df = pd.DataFrame(recs)
        per[kind] = summarize(df) if len(df) else {"parlays": 0}
        all_rows.append(df)
    allr = pd.concat(all_rows, ignore_index=True)
    sg = allr[allr.kind.isin(["same_player_2", "teammates_2", "opponents_2", "same_game_3"])]
    return {"legs_available": int(len(c)), "by_type": per, "same_game_all": summarize(sg), "all": summarize(allr),
            "leg_calibration": {"mean_p": round(float(c.p.mean()), 4), "hit_rate": round(float(c.y.mean()), 4),
                                "ece": round(ece(c.p.to_numpy(float), c.y.to_numpy(float)), 4), "legs": int(len(c))}}


# ------------------------------------------------------------------------------------------------- data
def nba_table(seasons: list[int]) -> dict:
    p, tr = C.nba_frame(seasons)
    stats = list(C.NBA_STATS)
    return {"cells": C.league_table(p, tr, stats, "team", None), "cross_game": C.cross_game(p, tr, stats, seed=11)}


def nfl_table(seasons: list[int]) -> dict:
    p, tr = C.nfl_frame(seasons)
    stats = list(C.NFL_STATS)
    return {"cells": C.league_table(p, tr, stats, "team", "position"), "cross_game": C.cross_game(p, tr, stats, seed=13)}


def nba_walkforward_rows(season: int, quick: bool) -> pd.DataFrame:
    from modelroom.common.propeval import apply_calibration
    from modelroom.nba.props import backtest as B
    from modelroom.nba.props import inputs as I
    from modelroom.nba.props.config import PropParams
    params_file = ROOT / "modelroom" / "nba" / "props" / "params_0.2.0.json"
    p = PropParams.load(params_file)
    p = replace(p, settings=replace(p.settings, sims=1500))
    r = B.Runner(I.load())
    if quick:
        r.days[season] = r.days[season][:25]
    t, _ = r.scored([season], p)
    t = apply_calibration(t, p.calibration)
    meta = pd.read_parquet(C.PROC / "nba" / "prop_player_games.parquet", columns=["game_id", "player_id", "team", "is_home", "game_date"])
    t["game_id"] = t.game_id.astype(str)
    t["player_id"] = t.player_id.astype(str)
    meta["game_id"] = meta.game_id.astype(str)
    t = t.merge(meta, on=["game_id", "player_id"], how="inner")
    t["market"] = t.market.map(NBA_MARKET_TO_STAT)
    return t.rename(columns={"game_date": "date"}).dropna(subset=["market"])[["date", "game_id", "player_id", "team", "market", "p", "y"]]


def nfl_walkforward_rows(season: int, quick: bool) -> pd.DataFrame:
    from modelroom.nfl.props import backtest as B
    from modelroom.nfl.props import inputs as I
    from modelroom.nfl.props.config import MARKETS, PropParams
    params_file = ROOT / "modelroom" / "nfl" / "props" / "params_0.1.1.json"
    p = PropParams.load(params_file)
    p = replace(p, settings=replace(p.settings, sims=1500))
    r = B.Runner(I.load({season - 1, season}))
    if quick:
        g = r.inp.games
        r.inp.games = g[(g.season != season) | (g.week <= 4)]
    t, _ = r.scored([season], p)
    if p.calibration:
        from modelroom.common.propeval import apply_calibration
        t = apply_calibration(t, p.calibration)
    stat_of = {k: m["stat"] for k, m in MARKETS.items()}
    t["market"] = t.market.map(lambda m: m if m in C.NFL_STATS else NFL_STAT_TO_NAME.get(stat_of.get(m, ""), None))
    meta = pd.read_parquet(C.PROC / "nfl" / "player_games.parquet", columns=["game_id", "player_id", "team", "game_date", "position"])
    t = t.merge(meta.drop_duplicates(["game_id", "player_id"]), on=["game_id", "player_id"], how="inner")
    t = t.rename(columns={"game_date": "date", "position": "pos"}).dropna(subset=["market"])
    return t[t.pos.isin(C.NFL_POS)][["date", "game_id", "player_id", "team", "pos", "market", "p", "y"]]


def nba_live_rows(ledger: Path) -> pd.DataFrame:
    """This season's published ledger probabilities (latest record before tip-off per player-game), graded."""
    recs = []
    with open(ledger) as f:
        for line in f:
            d = json.loads(line)
            if d.get("kind") != "player_props":
                continue
            recs.append(d)
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    df = df[df.generated_at < df.game_start].sort_values("generated_at").drop_duplicates(["nba_game_id", "player_id", "model_version"], keep="last")
    # one model per player-game: the newest version recorded for it
    df = df.sort_values("model_version").drop_duplicates(["nba_game_id", "player_id"], keep="last")
    box = pd.read_parquet(C.PROC / "nba" / "prop_player_games.parquet")
    box = box[box.played & (box.minutes > 0)]
    box["game_id"] = box.game_id.astype(str)
    act = box.set_index(["game_id", "player_id"])
    cols = {"points": "pts", "rebounds": "reb", "assists": "ast", "pra": "pra", "threes": "fg3m", "steals": "stl", "blocks": "blk"}
    rows = []
    for d in df.itertuples(index=False):
        k = (str(d.nba_game_id), str(d.player_id))
        if k not in act.index:
            continue
        a = act.loc[k]
        for mk, probs in d.probabilities.items():
            col = cols.get(mk)
            if not col:
                continue
            for thr, pv in probs.items():
                if thr in ("mean", "sd") or pv is None:
                    continue
                rows.append({"date": a.game_date, "game_id": k[0], "player_id": k[1], "team": a.team, "market": mk,
                             "p": float(pv), "y": float(a[col] >= float(thr)), "model_version": d.model_version})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--ledger", default=str(ROOT / "preview-ledger" / "nba_props.jsonl"))
    ap.add_argument("--skip-nfl", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    scale = 0.25 if a.quick else 1.0
    report = {"kind": "parlay_backtest", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "leg_band": [P_LO, P_HI], "method": __doc__.split("\n\n")[0], "sections": {}}

    print("NBA walk-forward 2025-26 ...", flush=True)
    t = nba_table([2021, 2022, 2023, 2024, 2025])
    rows = nba_walkforward_rows(2026, a.quick)
    report["sections"]["nba_walkforward_2025_26"] = {"model": "nba-props 0.2.0 (TEST)", "table_seasons": "2020-21 to 2024-25",
                                                     **run_backtest(rows, t, False, seed=1, scale=scale)}
    print("NBA live ledger 2026-27 ...", flush=True)
    lp = Path(a.ledger)
    live = nba_live_rows(lp) if lp.exists() else pd.DataFrame()
    if len(live):
        t2 = nba_table([2022, 2023, 2024, 2025, 2026])
        report["sections"]["nba_live_2026_27"] = {"model": "published ledger probabilities", "versions": sorted(live.model_version.unique().tolist()),
                                                  "dates": [str(live.date.min()), str(live.date.max())], "table_seasons": "2021-22 to 2025-26",
                                                  **run_backtest(live, t2, False, seed=2, scale=min(scale, 0.25))}
    if not a.skip_nfl:
        print("NFL walk-forward 2025 ...", flush=True)
        t3 = nfl_table(list(range(2018, 2025)))
        rows = nfl_walkforward_rows(2025, a.quick)
        report["sections"]["nfl_walkforward_2025"] = {"model": "nfl-props 0.1.1 (TEST)", "table_seasons": "2018 to 2024",
                                                      **run_backtest(rows, t3, True, seed=3, scale=scale)}
    report["runtime_s"] = round(time.time() - t0, 1)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1, default=str))
    for name, s in report["sections"].items():
        al, sg = s["all"], s["same_game_all"]
        print(f"{name}: parlays {al['parlays']} | hit {al.get('hit_rate')} | pred indep {al.get('mean_predicted_independent')} "
              f"corr {al.get('mean_predicted_correlated')} | logloss gain {al.get('log_loss_gain')} {al.get('log_loss_gain_95ci')} | "
              f"same-game gain {sg.get('log_loss_gain')} {sg.get('log_loss_gain_95ci')} | ECE indep {al.get('ece_independent')} corr {al.get('ece_correlated')}")


if __name__ == "__main__":
    main()
