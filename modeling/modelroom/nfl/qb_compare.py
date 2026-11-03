"""Old vs new starting-QB identification, with every other setting frozen.

    python -m modelroom.nfl.qb_compare            (writes docs/models/results/nfl-qb-starter-comparison.json)

Nothing here saves parameters or touches the live projections. The active model keeps the schedule's QB
field ("listed") until the projected-starter version is approved.

Variants, all scored on the same held-out seasons with the CURRENT tuned settings (params.json):
  listed     the schedule's QB field. For past games this is the actual starter, known only afterwards,
             so the existing backtest had a small look-ahead advantage here.
  previous   the team's previous starter: what the schedule field holds for coming games (old live behaviour)
  projected  the new rule (starters.py): roster + injury report + depth chart as of kickoff
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

VARIANTS = ("listed", "previous", "projected")
OUT = Path(__file__).resolve().parents[3] / "docs" / "models" / "results" / "nfl-qb-starter-comparison.json"


def _set(src: str) -> None:
    os.environ["MODELROOM_NFL_QB_SOURCE"] = src


def game_engine(log=print) -> dict:
    from modelroom.nfl import backtest, project, walkforward
    from modelroom.nfl.config import ModelParams

    params = ModelParams.load()
    out, proj = {}, {}
    for src in VARIANTS:
        _set(src)
        prep = walkforward.prepare()
        q = project.apply(walkforward.run(prep, params.ratings, params.points.qb_replacement_epa, project_seasons=set(backtest.TEST)), params.points)
        ev = backtest.evaluate(q)
        out[src] = {k: ev[k] for k in ("games", "margin", "total", "win_probability", "calibration")}
        proj[src] = q.set_index("game_id")[["proj_margin", "proj_total", "home_win_prob"]]
        log(f"game engine [{src}]: margin MAE {ev['margin']['mae']}, total MAE {ev['total']['mae']}, win Brier {ev['win_probability']['brier']}")
    a, b = proj["listed"], proj["projected"]
    common = a.index.intersection(b.index)
    changed = (a.loc[common, "proj_margin"] - b.loc[common, "proj_margin"]).abs() > 0.05
    out["changed_vs_listed"] = {"games": int(len(common)), "projections_changed": int(changed.sum())}
    p = proj["previous"]
    common2 = p.index.intersection(b.index)
    out["changed_vs_previous"] = {"games": int(len(common2)), "projections_changed": int(((p.loc[common2, "proj_margin"] - b.loc[common2, "proj_margin"]).abs() > 0.05).sum())}
    return out


def props(log=print) -> dict:
    from modelroom.common.propeval import apply_calibration, objective, summarize
    from modelroom.nfl.props import backtest as PB
    from modelroom.nfl.props import inputs as I
    from modelroom.nfl.props.config import FIT_SEASONS, TEST_SEASONS, TUNE_SEASONS, PropParams

    base = PropParams.load()
    p = replace(base, settings=replace(base.settings, sims=4000))
    out, rows, ys = {}, {}, {}
    for src in ("listed", "projected"):
        _set(src)
        inp = I.load(set(FIT_SEASONS) | set(TUNE_SEASONS) | set(TEST_SEASONS))
        runner = PB.Runner(inp)
        raw, m = runner.scored(TEST_SEASONS, p)
        t = apply_calibration(raw, p.calibration)
        s = summarize(t, m)
        out[src] = {"objective_log_loss": round(objective(t), 5), "overall": s.get("overall"), "overall_vs_baseline": s.get("overall_vs_baseline"),
                    "by_market": {k: {"log_loss": v["model"]["log_loss"], "brier": v["model"]["brier"], "n": v["model"]["n"], "ece": round(v["ece"], 4)} for k, v in s["markets"].items()}}
        ti = t.set_index(["game_id", "player_id", "market", "threshold"])
        rows[src] = ti["p"]
        ys[src] = ti["y"]
        t[["game_id", "player_id", "market", "threshold", "p", "y"]].to_parquet(f"/tmp/qbc_props_{src}.parquet")
        OUT.with_suffix(f".{src}.partial.json").write_text(json.dumps(out[src], default=str))
        log(f"props [{src}]: log loss {out[src]['objective_log_loss']}, ECE {s['overall']['ece']:.4f}, n {s['overall']['n']}")
        del runner, inp
    a, b = rows["listed"], rows["projected"]
    common = a.index.intersection(b.index)
    diff = (a.loc[common] - b.loc[common]).abs() > 1e-9
    pg = common.droplevel([2, 3]).unique()
    changed_pg = diff[diff].index.droplevel([2, 3]).unique()
    def ll(pp, yy):
        pp = np.clip(pp.to_numpy(float), 1e-4, 1 - 1e-4)
        yy = yy.to_numpy(float)
        return {"log_loss": round(float(-np.mean(yy * np.log(pp) + (1 - yy) * np.log(1 - pp))), 5), "brier": round(float(np.mean((pp - yy) ** 2)), 5)}
    y = ys["listed"].loc[common]
    out["same_rows"] = {"n": int(len(common)), "listed": ll(a.loc[common], y), "projected": ll(b.loc[common], y)}
    ch = diff[diff].index
    out["changed_rows_only"] = {"n": int(len(ch)), "listed": ll(a.loc[ch], ys["listed"].loc[ch]), "projected": ll(b.loc[ch], ys["listed"].loc[ch])} if len(ch) else None
    out["changed"] = {"thresholds_compared": int(len(common)), "thresholds_changed": int(diff.sum()),
                      "player_games_compared": int(len(pg)), "player_games_changed": int(len(changed_pg)),
                      "only_in_listed": int(len(a.index.difference(b.index))), "only_in_projected": int(len(b.index.difference(a.index)))}
    return out


def starters_report() -> dict:
    from modelroom.nfl import starters
    from modelroom.nfl.props.config import TEST_SEASONS

    st = starters.load()
    s = starters.summary(st)
    test = st[st["season"].isin(TEST_SEASONS) & (st["status"] == "final")].sort_values(["team", "season", "week"]).copy()
    test["prev_actual"] = test.groupby("team")["actual_qb_id"].shift(1)
    s["test_seasons"] = {
        "team_games": int(len(test)),
        "projected_differs_from_listed": int((test["qb_id"] != test["listed_qb_id"]).sum()),
        "projected_differs_from_previous_starter": int((test["qb_id"] != test["prev_actual"]).sum()),
        "starter_changes_actual": int((test["actual_qb_id"] != test["prev_actual"]).sum()),
        "starter_changes_caught_by_projected": int(((test["actual_qb_id"] != test["prev_actual"]) & (test["qb_id"] == test["actual_qb_id"])).sum()),
        "accuracy": {"projected": round(float((test["qb_id"] == test["actual_qb_id"]).mean()), 4),
                     "previous_starter": round(float((test["prev_actual"] == test["actual_qb_id"]).mean()), 4),
                     "listed (after-the-fact)": round(float((test["listed_qb_id"] == test["actual_qb_id"]).mean()), 4)},
    }
    return s


def main() -> dict:
    if os.environ.get("QBC_PROPS_ONLY"):
        report = json.loads(OUT.read_text())
        report["props"] = props()
        OUT.write_text(json.dumps(report, indent=2, default=str))
        return report
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "note": "Same tuned settings for every variant; only the starting QB differs. Nothing here changes the live model.",
              "starters": starters_report()}
    report["game_engine"] = game_engine()
    OUT.write_text(json.dumps(report, indent=2, default=str))
    report["props"] = props()
    OUT.write_text(json.dumps(report, indent=2, default=str))
    os.environ.pop("MODELROOM_NFL_QB_SOURCE", None)
    return report


if __name__ == "__main__":
    main()
