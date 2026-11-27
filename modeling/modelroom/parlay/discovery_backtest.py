"""Does the pick-discovery ranking find value historically? (TEST, Moose 2026-11-27)

The Parlay Builder's "Picks to consider" list ranks legs by the model's edge over the sportsbook's no-vig price,
discounted for data quality and risk. The only stored history with both the model's walk-forward probability and a
real sportsbook price is NFL moneylines (nflverse closing lines). This replays 2023-2025 week by week with the active
NFL game model (params.json, fitted on 2021-22) and checks, out of sample:

  * do bigger model edges win more often than the price implies, and what would $1 per pick have returned?
  * does the ranker's top of the list beat the rest?

No AI is involved: a historical test of AI suggestions is not possible honestly (a language model has read about these
games; anything it says about them is contaminated). AI-assisted suggestions must be tested prospectively.

    python -m modelroom.parlay.discovery_backtest [--out ../docs/models/results/parlay-discovery-backtest.json]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT.parent / "docs" / "models" / "results" / "parlay-discovery-backtest.json"
TEST = (2023, 2024, 2025)


def dec(a: np.ndarray) -> np.ndarray:
    return np.where(a > 0, 1 + a / 100, 1 + 100 / np.abs(a))


def score(edge: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Same rule as the site (src/server/parlay/discover.ts): edge, discounted for long shots."""
    risk = np.where(p < 0.35, 0.5, np.where(p < 0.45, 0.8, 1.0))
    return edge * risk


def summarize(d: pd.DataFrame, seed: int = 5) -> dict:
    if d.empty:
        return {"picks": 0}
    ret = np.where(d.won, d.decimal - 1, -1.0)
    rng = np.random.default_rng(seed)
    weeks = d.week_key.to_numpy()
    uw = np.unique(weeks)
    s = pd.DataFrame({"w": weeks, "r": ret}).groupby("w").r.agg(["sum", "count"]).loc[uw].to_numpy()
    bs = [(lambda t: t[0] / t[1])(s[rng.integers(0, len(s), len(s))].sum(axis=0)) for _ in range(1000)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"picks": int(len(d)), "win_rate": round(float(d.won.mean()), 4), "model_p": round(float(d.p.mean()), 4),
            "market_p": round(float(d.mkt.mean()), 4), "roi_per_dollar": round(float(ret.mean()), 4),
            "roi_95ci": [round(float(lo), 4), round(float(hi), 4)]}


def build() -> dict:
    from modelroom.nfl import project, walkforward
    from modelroom.nfl.config import ModelParams
    params = ModelParams.load()
    prep = walkforward.prepare()
    proj = project.apply(walkforward.run(prep, params.ratings, params.points.qb_replacement_epa, project_seasons=set(TEST)), params.points)
    proj = proj[proj.actual_margin.notna()]
    ml = pd.read_parquet(ROOT / "data" / "processed" / "nfl" / "market_lines.parquet")
    ml = ml[(ml.market == "moneyline") & ml.home_price.notna() & ml.away_price.notna()].drop_duplicates("game_id", keep="last")
    g = proj.merge(ml[["game_id", "home_price", "away_price"]], on="game_id", how="inner")
    hd, ad = dec(g.home_price.to_numpy(float)), dec(g.away_price.to_numpy(float))
    ih, ia = 1 / hd, 1 / ad
    mh = ih / (ih + ia)
    rows = []
    for side, p, m, d, won in (("home", g.home_win_prob, mh, hd, g.actual_margin > 0), ("away", 1 - g.home_win_prob, 1 - mh, ad, g.actual_margin < 0)):
        rows.append(pd.DataFrame({"game_id": g.game_id, "season": g.season, "week": g.week, "side": side, "p": p.to_numpy(float),
                                  "mkt": m, "decimal": d, "won": won.to_numpy() & (g.actual_margin != 0).to_numpy()}))
    s = pd.concat(rows, ignore_index=True)
    s["edge"] = s.p - s.mkt
    s["score"] = score(s.edge.to_numpy(), s.p.to_numpy())
    s["week_key"] = s.season.astype(str) + "-" + s.week.astype(str).str.zfill(2)
    out = {"kind": "parlay_discovery_backtest", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "seasons": list(TEST), "games": int(g.game_id.nunique()), "market": "NFL moneyline, nflverse closing prices",
           "model": "nfl-game (params.json, fitted on 2021-22)", "baseline_all_sides": summarize(s)}
    bands = [(-1, 0), (0, 0.02), (0.02, 0.04), (0.04, 0.07), (0.07, 1)]
    out["by_edge"] = [{"edge": [a, b], **summarize(s[(s.edge > a) & (s.edge <= b)])} for a, b in bands]
    pos = s[s.edge > 0].copy()
    pos["rank"] = pos.groupby("week_key").score.rank(ascending=False, method="first")
    out["ranker_top3_per_week"] = summarize(pos[pos["rank"] <= 3])
    out["ranker_rest_positive_edge"] = summarize(pos[pos["rank"] > 3])
    out["long_shots_positive_edge"] = summarize(pos[pos.p < 0.35])
    out["notes"] = [
        "Closing prices: the hardest prices to beat; an edge here is conservative.",
        "Ties count as losses for simplicity (rare in the NFL).",
        "ROI intervals resample whole weeks.",
    ]
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    r = build()
    Path(a.out).write_text(json.dumps(r, indent=1))
    print(json.dumps({k: r[k] for k in ("baseline_all_sides", "by_edge", "ranker_top3_per_week", "ranker_rest_positive_edge", "long_shots_positive_edge")}, indent=1))


if __name__ == "__main__":
    main()
