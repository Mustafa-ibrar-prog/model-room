"""Historical correlation table for parlay pricing (TEST, Moose 2026-11-27).

Measures how prop and game-line outcomes move together, from stored box scores only (no API calls):

  1. For every player-game, a pre-game expectation per stat: an exponentially weighted mean and spread of the
     player's PREVIOUS games only (no look-ahead). The surprise is z = (actual - expected) / spread.
  2. Surprises are turned into normal scores (rank -> probit) so the coefficient is the Gaussian-copula correlation
     the site's joint engine uses.
  3. Coefficients are pooled by relationship: same player (stat x stat), teammates, opponents, player vs the game
     total and vs his own team's margin, game margin vs game total, and players / game totals in DIFFERENT games on
     the same night (the cross-game independence test).
  4. Each cell keeps its sample size, an effective sample size (distinct games: pairs inside one game are not
     independent) and a 95% interval. Cross-game cells get a date-clustered bootstrap interval.

Cells with fewer than MIN_PAIRS pairs are written with "insufficient": true and the site prices such parlays with
bounds only. Estimation seasons and the holdout season are disjoint; the holdout shows whether coefficients hold up.

    python -m modelroom.parlay.correlations [--out data/published/parlay_correlations.json]
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "data" / "published" / "parlay_correlations.json"

MIN_PAIRS = 300
NEGLIGIBLE_R = 0.03          # |r| below this moves a two-leg joint probability by well under one point
_inv = np.vectorize(NormalDist().inv_cdf)

NBA_STATS = {"points": ("pts", 2.0), "rebounds": ("reb", 1.0), "assists": ("ast", 1.0), "threes": ("fg3m", 0.5),
             "steals": ("stl", 0.5), "blocks": ("blk", 0.5), "pra": ("pra", 3.0)}
# NFL: column, z floor, minimum pre-game expectation for the player-game to count (keeps fringe roles out)
NFL_STATS = {"passing_yards": ("pass_yds", 30, 120), "passing_attempts": ("pass_att", 4, 18), "passing_completions": ("pass_cmp", 3, 12),
             "passing_tds": ("pass_td", 0.5, 0.6), "interceptions": ("ints", 0.5, 0.3), "rushing_yards": ("rush_yds", 10, 12),
             "rushing_attempts": ("carries", 2, 4), "anytime_td": ("td_scored", 0.3, 0.12), "fantasy_points": ("fantasy_ppr", 3, 5),
             "receiving_yards": ("rec_yds", 10, 12), "receptions": ("receptions", 1, 1.5), "rush_rec_yards": ("rush_rec", 10, 20),
             "longest_reception": ("long_rec", 5, 8)}
NFL_POS = ("QB", "RB", "WR", "TE")


# ---------------------------------------------------------------------------------------------------------- helpers
def normal_scores(x: pd.Series) -> pd.Series:
    """Rank -> probit, NaNs kept. Ties share the average rank."""
    ok = x.notna()
    out = pd.Series(np.nan, index=x.index)
    if ok.sum() < 3:
        return out
    r = x[ok].rank(method="average")
    out[ok] = _inv(r / (ok.sum() + 1))
    return out


def fisher_ci(r: float, n_eff: int) -> tuple[float, float]:
    if n_eff <= 3 or not np.isfinite(r):
        return (-1.0, 1.0)
    z, se = math.atanh(max(min(r, 0.999999), -0.999999)), 1 / math.sqrt(n_eff - 3)
    return (math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se))


def cell(x: np.ndarray, y: np.ndarray, n_eff: int | None = None) -> dict:
    m = np.isfinite(x) & np.isfinite(y)
    n = int(m.sum())
    if n < 3:
        return {"r": None, "n": n, "n_eff": 0, "lo": None, "hi": None, "insufficient": True}
    r = float(np.corrcoef(x[m], y[m])[0, 1])
    ne = int(min(n, n_eff)) if n_eff else n
    lo, hi = fisher_ci(r, ne)
    return {"r": round(r, 4), "n": n, "n_eff": ne, "lo": round(lo, 4), "hi": round(hi, 4), "insufficient": n < MIN_PAIRS}


def key(rel: str, a: str, b: str | None = None, symmetric: bool = True) -> str:
    if b is None:
        return f"{rel}|{a}"
    if symmetric and b < a:
        a, b = b, a
    return f"{rel}|{a}|{b}"


def prior_z(df: pd.DataFrame, by: str, col: str, halflife: float, min_periods: int, floor: float) -> tuple[pd.Series, pd.Series]:
    """Expected value from previous games only (shifted EWM), and z = (actual - expected) / max(spread, floor)."""
    g = df.groupby(by, sort=False)[col]
    mean = g.transform(lambda s: s.shift(1).ewm(halflife=halflife, min_periods=min_periods).mean())
    sd = g.transform(lambda s: s.shift(1).ewm(halflife=halflife, min_periods=min_periods).std())
    z = (df[col] - mean) / np.maximum(sd.fillna(floor), floor)
    return z, mean


def team_residuals(games: pd.DataFrame, halflife: float, min_periods: int) -> pd.DataFrame:
    """Per game: total and home-margin surprise against each team's previous scoring and allowing (no look-ahead)."""
    g = games.dropna(subset=["home_score", "away_score"]).sort_values("start_time").copy()
    long = pd.concat([
        pd.DataFrame({"game_id": g.game_id, "t": g.start_time, "team": g.home, "pf": g.home_score, "pa": g.away_score}),
        pd.DataFrame({"game_id": g.game_id, "t": g.start_time, "team": g.away, "pf": g.away_score, "pa": g.home_score}),
    ]).sort_values("t")
    for c in ("pf", "pa"):
        long[c + "_exp"] = long.groupby("team")[c].transform(lambda s: s.shift(1).ewm(halflife=halflife, min_periods=min_periods).mean())
    e = long.set_index(["game_id", "team"])
    h = e.loc[list(zip(g.game_id, g.home))].reset_index(drop=True)
    a = e.loc[list(zip(g.game_id, g.away))].reset_index(drop=True)
    exp_h = (h.pf_exp.values + a.pa_exp.values) / 2
    exp_a = (a.pf_exp.values + h.pa_exp.values) / 2
    out = pd.DataFrame({"game_id": g.game_id.values, "date": g.date.values,
                        "total_res": (g.home_score.values + g.away_score.values) - (exp_h + exp_a),
                        "margin_res": (g.home_score.values - g.away_score.values) - (exp_h - exp_a)})
    out = out.dropna()
    out["total_ns"] = normal_scores(out.total_res)
    out["margin_ns"] = normal_scores(out.margin_res)
    return out


def cross_game_pairs(df: pd.DataFrame, cols: list[str], reps: int, seed: int) -> pd.DataFrame:
    """Random pairs of rows from DIFFERENT games on the same date (several random pairings per date)."""
    rng = np.random.default_rng(seed)
    parts = []
    for date, d in df.groupby("date", sort=False):
        if d.game_id.nunique() < 2:
            continue
        idx = d.index.to_numpy()
        gid = d.game_id.to_numpy()
        for _ in range(reps):
            perm = rng.permutation(len(idx))
            ok = gid != gid[perm]
            if ok.any():
                a, b = idx[ok], idx[perm][ok]
                parts.append(pd.DataFrame({"date": date, **{c + "_x": df.loc[a, c].to_numpy() for c in cols},
                                           **{c + "_y": df.loc[b, c].to_numpy() for c in cols}}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def bootstrap_ci(pairs: pd.DataFrame, x: str, y: str, reps: int = 300, seed: int = 7) -> tuple[float, float]:
    """95% interval for r with whole dates resampled (pairs on one night share that night's conditions)."""
    d = pairs[["date", x, y]].dropna()
    if len(d) < MIN_PAIRS:
        return (-1.0, 1.0)
    # per-date sufficient statistics make each replicate O(dates)
    d = d.assign(xx=d[x] * d[x], yy=d[y] * d[y], xy=d[x] * d[y], one=1.0)
    s = d.groupby("date")[[x, y, "xx", "yy", "xy", "one"]].sum().to_numpy()
    rng = np.random.default_rng(seed)
    rs = []
    for _ in range(reps):
        t = s[rng.integers(0, len(s), len(s))].sum(axis=0)
        sx, sy, sxx, syy, sxy, n = t
        vx, vy = sxx - sx * sx / n, syy - sy * sy / n
        if vx > 0 and vy > 0:
            rs.append((sxy - sx * sy / n) / math.sqrt(vx * vy))
    lo, hi = np.percentile(rs, [2.5, 97.5])
    return float(lo), float(hi)


def symmetric_pairs(df: pd.DataFrame, on: list[str], differ: str, cols: list[str]) -> pd.DataFrame:
    """All ordered pairs of rows sharing `on` with different `differ` (both orientations, so coefficients are symmetric)."""
    keep = on + [differ] + cols
    m = df[keep].merge(df[keep], on=on, suffixes=("_x", "_y"))
    return m[m[differ + "_x"] != m[differ + "_y"]]


# ---------------------------------------------------------------------------------------------------------- NBA
def nba_frame(seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = pd.read_parquet(PROC / "nba" / "prop_player_games.parquet")
    p = p[p.played & (p.minutes > 0) & p.season_type.isin([2, 3])].copy()
    p = p.sort_values(["player_id", "game_date"]).reset_index(drop=True)
    _, mexp = prior_z(p, "player_id", "minutes", 10, 8, 1.0)
    p["min_exp"] = mexp
    for name, (col, floor) in NBA_STATS.items():
        p[name + "_z"], _ = prior_z(p, "player_id", col, 10, 8, floor)
    p = p[(p.min_exp >= 15) & p.season.isin(seasons)].copy()
    for name in NBA_STATS:
        p[name] = normal_scores(p[name + "_z"])
    g = pd.read_parquet(PROC / "nba" / "games.parquet")
    g = g.assign(home=g.home_abbr, away=g.away_abbr, date=g.game_date, game_id=g.game_id.astype(str))
    tr = team_residuals(g[g.season.isin(seasons + [min(seasons) - 1])], 15, 10)
    p["game_id"] = p.game_id.astype(str)
    p = p.merge(tr[["game_id", "total_ns", "margin_ns"]], on="game_id", how="left")
    p["own_margin_ns"] = np.where(p.is_home, p.margin_ns, -p.margin_ns)
    p["date"] = p.game_date
    return p, tr[tr.game_id.isin(p.game_id)]


def league_table(p: pd.DataFrame, tr: pd.DataFrame, stats: list[str], team_col: str, pos_col: str | None) -> dict:
    """All relationship cells for one league. With pos_col, teammate/opponent/game-line cells are keyed POS:stat."""
    cells: dict = {}
    n_games = p.game_id.nunique()
    # same player
    for i, a in enumerate(stats):
        for b in stats[i + 1:]:
            cells[key("same", a, b)] = cell(p[a].to_numpy(float), p[b].to_numpy(float))
    cols = stats
    if pos_col:
        # one column per POS:stat so every pair can be keyed by position
        lab = []
        for pos in NFL_POS:
            for s in stats:
                c = f"{pos}:{s}"
                p[c] = np.where(p[pos_col] == pos, p[s], np.nan)
                if p[c].notna().sum() >= 50:
                    lab.append(c)
        cols = lab
    tm = symmetric_pairs(p, ["game_id", team_col], "player_id", cols)
    op = symmetric_pairs(p, ["game_id"], team_col, cols)
    op = op[op[team_col + "_x"] != op[team_col + "_y"]] if team_col + "_x" in op else op
    n_team_games = p.groupby(["game_id", team_col]).ngroups
    for i, a in enumerate(cols):
        for b in cols[i:]:
            cells[key("team", a, b)] = cell(tm[a + "_x"].to_numpy(float), tm[b + "_y"].to_numpy(float), n_team_games)
            cells[key("opp", a, b)] = cell(op[a + "_x"].to_numpy(float), op[b + "_y"].to_numpy(float), n_games)
    for c in cols:
        cells[key("ptotal", c)] = cell(p[c].to_numpy(float), p.total_ns.to_numpy(float), n_games)
        cells[key("pmargin", c)] = cell(p[c].to_numpy(float), p.own_margin_ns.to_numpy(float), n_games)
    cells["game|margin|total"] = cell(tr.margin_ns.to_numpy(float), tr.total_ns.to_numpy(float))
    return cells


def cross_game(p: pd.DataFrame, tr: pd.DataFrame, stats: list[str], seed: int) -> dict:
    """Same-night, different-game pairs: is there any measurable dependence?"""
    pairs = cross_game_pairs(p, stats, reps=3, seed=seed)
    out = {}
    for i, a in enumerate(stats):
        for b in stats[i:]:
            c = cell(pairs[a + "_x"].to_numpy(float), pairs[b + "_y"].to_numpy(float))
            lo, hi = bootstrap_ci(pairs, a + "_x", b + "_y")
            c.update(lo=round(lo, 4), hi=round(hi, 4), n_dates=int(pairs.date.nunique()))
            c["verdict"] = verdict(c)
            out[key("xgame", a, b)] = c
    gp = cross_game_pairs(tr.reset_index(drop=True), ["total_ns", "margin_ns"], reps=3, seed=seed + 1)
    for a, b in (("total_ns", "total_ns"), ("margin_ns", "margin_ns"), ("total_ns", "margin_ns")):
        c = cell(gp[a + "_x"].to_numpy(float), gp[b + "_y"].to_numpy(float))
        lo, hi = bootstrap_ci(gp, a + "_x", b + "_y")
        c.update(lo=round(lo, 4), hi=round(hi, 4), n_dates=int(gp.date.nunique()))
        c["verdict"] = verdict(c)
        out[key("xgame", a.replace("_ns", ""), b.replace("_ns", ""))] = c
    rs = [abs(v["r"]) for v in out.values() if v["r"] is not None and not v["insufficient"]]
    tested = sum(1 for v in out.values() if v["verdict"] != "insufficient")
    dependent = [k for k, v in out.items() if v["verdict"] == "dependent"]
    # Many cells are tested at the 5% level, so about 5% will look "dependent" by chance even when nothing is there.
    # The family passes when the count of flagged cells is within what chance produces (binomial 95th percentile)
    # and no flagged coefficient is large enough to matter.
    allowed = int(np.ceil(tested * 0.05 + 1.645 * math.sqrt(tested * 0.05 * 0.95)))
    biggest = max((abs(out[k]["r"]) for k in dependent), default=0.0)
    independent = len(dependent) <= allowed and biggest < 0.06
    return {"cells": out, "tested": tested, "max_abs_r": round(max(rs), 4) if rs else None, "dependent_cells": dependent,
            "chance_allowance": allowed, "independent": independent,
            # the engine prices cross-game legs as independent and widens the range by this band
            "engine_r_band": round(max(rs), 4) if rs and independent else None,
            "verdict": ("independent: flagged cells are within chance and tiny" if independent
                        else "dependent: the engine uses the measured cross-game coefficients")}


def verdict(c: dict) -> str:
    if c["insufficient"] or c["r"] is None:
        return "insufficient"
    if (c["lo"] <= 0 <= c["hi"]) or abs(c["r"]) < NEGLIGIBLE_R:
        return "independent"
    return "dependent"


def holdout_check(est: dict, hold: dict) -> dict:
    """Do the estimation-season coefficients hold in the holdout season? Mean absolute difference over cells both
    seasons measured with enough data, and the share of holdout coefficients inside the estimation interval
    widened by the holdout's own sampling error."""
    diffs, inside, n = [], 0, 0
    for k, c in est.items():
        h = hold.get(k)
        if not h or c["insufficient"] or h["insufficient"] or c["r"] is None or h["r"] is None:
            continue
        n += 1
        diffs.append(abs(c["r"] - h["r"]))
        half = max(c["hi"] - c["r"], c["r"] - c["lo"]) + max(h["hi"] - h["r"], h["r"] - h["lo"])
        inside += abs(c["r"] - h["r"]) <= half
    return {"cells_compared": n, "mean_abs_diff": round(float(np.mean(diffs)), 4) if diffs else None,
            "max_abs_diff": round(float(np.max(diffs)), 4) if diffs else None, "share_consistent": round(inside / n, 3) if n else None}


def build_nba() -> dict:
    est_seasons, hold_seasons = [2022, 2023, 2024, 2025, 2026], [2027]
    p, tr = nba_frame(est_seasons)
    stats = list(NBA_STATS)
    cells = league_table(p, tr, stats, "team", None)
    xg = cross_game(p, tr, stats, seed=11)
    ph, trh = nba_frame(hold_seasons)
    hold = league_table(ph, trh, stats, "team", None) if len(ph) > 1000 else {}
    return {"estimation_seasons": est_seasons, "holdout_seasons": hold_seasons, "player_games": int(len(p)),
            "games": int(p.game_id.nunique()), "holdout_player_games": int(len(ph)),
            "cells": cells, "cross_game": xg, "holdout": holdout_check(cells, hold)}


# ---------------------------------------------------------------------------------------------------------- NFL
def nfl_frame(seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = pd.read_parquet(PROC / "nfl" / "player_games.parquet")
    p = p[p.season_type.isin(["REG", "POST"]) & p.position.isin(NFL_POS)].copy()
    p["rush_rec"] = p.rush_yds.fillna(0) + p.rec_yds.fillna(0)
    p["td_scored"] = (p.td_scored.fillna(0) > 0).astype(float)
    p = p.sort_values(["player_id", "game_date"]).reset_index(drop=True)
    for name, (col, floor, need) in NFL_STATS.items():
        p[col] = p[col].astype(float)
        z, mean = prior_z(p, "player_id", col, 6, 4, floor)
        p[name + "_z"] = np.where(mean >= need, z, np.nan)
    p = p[p.season.isin(seasons)].copy()
    for name in NFL_STATS:
        p[name] = normal_scores(p[name + "_z"])
    g = pd.read_parquet(PROC / "nfl" / "games.parquet")
    g = g.assign(home=g.home_team, away=g.away_team, date=g.game_date)
    tr = team_residuals(g[g.season.isin(seasons + [min(seasons) - 1])], 6, 4)
    p = p.merge(tr[["game_id", "total_ns", "margin_ns"]], on="game_id", how="left")
    p["own_margin_ns"] = np.where(p.team == p.home_team, p.margin_ns, -p.margin_ns)
    # NFL slates span Thursday to Monday; "same night" = same game date
    p["date"] = p.game_date
    p = p[p[list(NFL_STATS)].notna().any(axis=1)]
    return p, tr[tr.game_id.isin(p.game_id)]


def build_nfl() -> dict:
    est_seasons, hold_seasons = list(range(2018, 2026)), [2026]
    p, tr = nfl_frame(est_seasons)
    stats = list(NFL_STATS)
    cells = league_table(p, tr, stats, "team", "position")
    xg = cross_game(p, tr, stats, seed=13)
    ph, trh = nfl_frame(hold_seasons)
    hold = league_table(ph, trh, stats, "team", "position") if len(ph) > 1000 else {}
    return {"estimation_seasons": est_seasons, "holdout_seasons": hold_seasons, "player_games": int(len(p)),
            "games": int(p.game_id.nunique()), "holdout_player_games": int(len(ph)),
            "cells": cells, "cross_game": xg, "holdout": holdout_check(cells, hold)}


def build() -> dict:
    return {
        "schema": 1,
        "kind": "parlay_correlations",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_pairs": MIN_PAIRS,
        "negligible_r": NEGLIGIBLE_R,
        "method": ("Gaussian-copula correlations of pre-game surprises (actual minus a no-look-ahead weighted average of "
                   "the player's previous games, scaled by their spread), normal-scored. Pooled by relationship. 95% "
                   "intervals use distinct games as the effective sample; cross-game cells use a date-clustered bootstrap."),
        "leagues": {"nba": build_nba(), "nfl": build_nfl()},
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    t = build()
    Path(a.out).write_text(json.dumps(t, indent=1, sort_keys=True))
    for lg, d in t["leagues"].items():
        usable = sum(1 for c in d["cells"].values() if not c["insufficient"])
        print(f"{lg}: {usable}/{len(d['cells'])} cells usable; cross-game {d['cross_game']['verdict']} "
              f"(max |r| {d['cross_game']['max_abs_r']}); holdout {d['holdout']}")


if __name__ == "__main__":
    main()
