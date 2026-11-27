"""Small summary of the parlay backtests for the Parlay Builder page (TEST, Moose 2026-11-27).

Reads docs/models/results/parlay-backtest.json, parlay-discovery-backtest.json and data/published/parlay_correlations.json;
writes data/published/parlay_validation.json (aggregates only).

    python -m modelroom.parlay.publish_validation
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT.parent / "docs" / "models" / "results"
LABELS = {"nba_walkforward_2025_26": "NBA 2025-26 (walk-forward)", "nba_live_2026_27": "NBA 2026-27 (published picks so far)",
          "nfl_walkforward_2025": "NFL 2025 (walk-forward)"}


def build() -> dict:
    bt = json.loads((RES / "parlay-backtest.json").read_text())
    rows, calib = [], []
    for k, s in bt["sections"].items():
        a = s["all"]
        rows.append({"label": LABELS.get(k, k), "parlays": a.get("priced_with_correlations", 0), "hit_rate": a.get("hit_rate"),
                     "predicted": a.get("mean_predicted_correlated"), "predicted_independent": a.get("mean_predicted_independent"),
                     "log_loss_gain": a.get("log_loss_gain"), "log_loss_gain_95ci": a.get("log_loss_gain_95ci")})
    main = bt["sections"].get("nba_walkforward_2025_26")
    if main:
        calib = main["all"].get("calibration_correlated", [])
    corr = json.loads((ROOT / "data" / "published" / "parlay_correlations.json").read_text())
    xg = [{"league": lg, "independent": d["cross_game"]["independent"], "max_abs_r": d["cross_game"]["max_abs_r"],
           "dependent_cells": len(d["cross_game"]["dependent_cells"]), "tested": d["cross_game"]["tested"]} for lg, d in corr["leagues"].items()]
    disc = None
    dp = RES / "parlay-discovery-backtest.json"
    if dp.exists():
        d = json.loads(dp.read_text())
        top = d["ranker_top3_per_week"]
        disc = {"summary": "Large model-vs-market gaps on NFL moneylines (2023-25, closing prices) did not win more often than the price implied.",
                "top3_roi": top.get("roi_per_dollar"), "top3_roi_95ci": top.get("roi_95ci"), "baseline_roi": d["baseline_all_sides"].get("roi_per_dollar"),
                "picks": top.get("picks", 0), "seasons": d["seasons"]}
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "parlay": rows, "calibration": calib, "cross_game": xg, "discovery": disc}


def main() -> None:
    out = ROOT / "data" / "published" / "parlay_validation.json"
    out.write_text(json.dumps(build(), indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
