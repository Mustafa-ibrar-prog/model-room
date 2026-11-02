"""Shared pieces of the published board: freshness, market comparison, ledger grading.

No league logic: each engine supplies its own projections in the common shape.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger

Z80 = 1.2815515655446004  # two-sided 80% interval for a normal error


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts) -> str | None:
    if ts is None or (isinstance(ts, float) and math.isnan(ts)) or pd.isna(ts):
        return None
    return pd.Timestamp(ts).tz_convert("UTC").isoformat() if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).isoformat()


def freshness(games: pd.DataFrame, *, last_ingest: str | None, now: datetime, grace_hours: float, stale_hours: float) -> dict:
    """current  = every game that should be final by now has a result, and the data was refreshed recently
    delayed  = some finished games have no result yet, or the last refresh is older than stale_hours
    """
    due = games[(games["start_time"] < pd.Timestamp(now) - pd.Timedelta(hours=grace_hours)) & ~games["status"].isin(["final", "postponed", "final_no_box"])]
    ingest_age = None
    if last_ingest:
        ingest_age = (now - datetime.fromisoformat(last_ingest)).total_seconds() / 3600
    status = "current"
    reasons = []
    if len(due):
        status = "delayed"
        reasons.append(f"{len(due)} finished game(s) have no result in the source yet")
    if ingest_age is None:
        status = "delayed"
        reasons.append("no successful ingest recorded")
    elif ingest_age > stale_hours:
        status = "delayed"
        reasons.append(f"last ingest {ingest_age:.0f} hours ago")
    finals = games[games["status"] == "final"]
    return {
        "status": status,
        "reasons": reasons,
        "results_through": str(finals["game_date"].max()) if len(finals) else None,
        "last_ingest": last_ingest,
        "missing_results": [str(g) for g in due["game_id"].head(20)],
    }


def implied_probabilities(home_ml: float | None, away_ml: float | None) -> tuple[float | None, float | None]:
    """No-vig implied win probabilities from American moneylines (normalized to sum to 1)."""
    def raw(ml):
        if ml is None or pd.isna(ml):
            return None
        ml = float(ml)
        return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)

    h, a = raw(home_ml), raw(away_ml)
    if h is None or a is None:
        return None, None
    s = h + a
    return h / s, a / s


def market_by_game(consensus: pd.DataFrame, raw_snapshots: pd.DataFrame | None) -> dict:
    """{game_id: {spread, total, home_ml, away_ml, books, captured_at, sources}} from consensus rows."""
    out: dict = {}
    for _, r in consensus.iterrows():
        g = out.setdefault(r["game_id"], {"spread": None, "total": None, "home_ml": None, "away_ml": None,
                                          "books": 0, "captured_at": None, "sources": set()})
        if r["market"] in ("spread", "total"):
            g[r["market"]] = None if pd.isna(r["line"]) else float(r["line"])
        g["books"] = max(g["books"], int(r["books"]))
        if pd.notna(r["captured_at"]):
            ts = pd.Timestamp(r["captured_at"]).isoformat()
            g["captured_at"] = max(filter(None, [g["captured_at"], ts]))
        g["sources"].update(str(r["sources"]).split(","))
    if raw_snapshots is not None and len(raw_snapshots):
        ml = raw_snapshots[(raw_snapshots["market"] == "moneyline") & raw_snapshots["game_id"].notna()].copy()
        if len(ml):
            ml["ts"] = pd.to_datetime(ml["captured_at"], utc=True, errors="coerce")
            latest = ml.sort_values("ts").groupby(["game_id", "sportsbook"], dropna=False).tail(1)
            med = latest.groupby("game_id")[["home_price", "away_price"]].median()
            for gid, r in med.iterrows():
                g = out.setdefault(gid, {"spread": None, "total": None, "home_ml": None, "away_ml": None,
                                         "books": 0, "captured_at": None, "sources": set()})
                g["home_ml"], g["away_ml"] = r["home_price"], r["away_price"]
    for g in out.values():
        g["sources"] = sorted(s for s in g["sources"] if s and s != "nan")
    return out


def model_vs_market(proj: dict, market: dict | None) -> dict | None:
    """Edges. Positive spread edge = model likes the home side; positive total edge = model is over."""
    if not market:
        return None
    e = {"spread": None, "total": None, "home_prob_market": None, "away_prob_market": None, "home_prob_diff": None}
    if market.get("spread") is not None:
        e["spread"] = round(market["spread"] - proj["spread"], 2)
    if market.get("total") is not None:
        e["total"] = round(proj["total"] - market["total"], 2)
    hp, ap = implied_probabilities(market.get("home_ml"), market.get("away_ml"))
    if hp is not None:
        e["home_prob_market"], e["away_prob_market"] = round(hp, 4), round(ap, 4)
        e["home_prob_diff"] = round(proj["home_win_prob"] - hp, 4)
    return e


def grade_ledger(path, results: pd.DataFrame) -> dict:
    """Join stored pre-game predictions to final results. The ledger itself is never modified.

    results columns: game_id, home_score, away_score (finals only).
    Uses the latest pre-game prediction per game and model version.
    """
    recs = ledger.read(path)
    if not recs:
        return {"tracked": 0, "graded": 0, "note": "No stored predictions yet."}
    df = pd.DataFrame(recs)
    df["game_id"] = df["game_id"].astype(str)
    df = df.sort_values("generated_at").groupby(["game_id", "model_version"]).tail(1)
    res = results.assign(game_id=results["game_id"].astype(str))
    m = df.merge(res, on="game_id", how="inner")
    out = {"tracked": int(len(df)), "graded": int(len(m)), "by_version": {}}
    for ver, g in m.groupby("model_version"):
        pm = g["pred_margin"].astype(float)
        pt = g["pred_total"].astype(float)
        am = g["home_score"] - g["away_score"]
        at = g["home_score"] + g["away_score"]
        hw = (am > 0).astype(float)
        p = g["home_win_prob"].astype(float).clip(1e-6, 1 - 1e-6)
        out["by_version"][ver] = {
            "games": int(len(g)),
            "margin_mae": round(float(np.mean(np.abs(pm - am))), 2),
            "total_mae": round(float(np.mean(np.abs(pt - at))), 2),
            "winner_correct": round(float(np.mean((p > 0.5) == (hw == 1))), 3),
            "brier": round(float(np.mean((p - hw) ** 2)), 4),
        }
    return out


def interval(center: float, sigma: float | None) -> list[float] | None:
    if sigma is None:
        return None
    return [round(center - Z80 * sigma, 1), round(center + Z80 * sigma, 1)]


def upcoming_window(df: pd.DataFrame, now: datetime, days: int) -> pd.DataFrame:
    return df[(df["start_time"] > pd.Timestamp(now)) & (df["start_time"] <= pd.Timestamp(now + timedelta(days=days)))]
