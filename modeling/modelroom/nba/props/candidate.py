"""NBA props 0.2.0 candidate: foundation fixes tuned on 2021-22, scored once on the test seasons against 0.1.0.

    python -m modelroom.nba.props.candidate [--tune-sims 800]

Changes searched (each is a setting; the defaults reproduce 0.1.0 exactly):
  * rate_prior_kind=role   per-minute rates pulled toward players in the same role, not the position
                           average (bench players were lifted toward starter rates: +12% on points)
  * minutes_fill=headroom  missing team minutes go to players with room below their own recent high,
                           instead of scaling everyone (stars) up to fill 240
  * usage_decay            freed usage from an absent teammate fades as the absence ages (teammates'
                           recent rates already include it: the old rule double-counted long absences)
  * the existing noise / strength settings are re-searched, with calibration applied

Tuning objective = per-market log loss after per-market calibration fit on the same rows. Nothing here
touches params.json; the candidate goes to params_0.2.0.json, the report to
docs/models/results/nba-props-candidate-0.2.0.json.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from modelroom.common.paths import ensure, output_dir
from modelroom.common.propeval import apply_calibration, fit_calibration, fixed_rows, objective, summarize

from . import backtest as B
from . import inputs as I
from .config import CANDIDATE_FILE, CANDIDATE_VERSION, MODEL_VERSION, TEST_SEASONS, TUNE_SEASONS, PropParams

GRID = [
    ("rate_prior_kind", ["role"]),
    ("minutes_fill", ["headroom"]),
    ("usage_decay", [1.0]),
    ("usage_boost", [0.5, 1.5]),
    ("rate_prior_minutes", [150.0, 500.0]),
    ("minutes_half_life", [6.0]),
    ("minutes_sd", [5.0, 9.0, 11.0]),
    ("scoring_sd", [0.25, 0.45, 0.55]),
    ("rebound_sd", [0.25, 0.45, 0.55]),
    ("assist_sd", [0.25, 0.45, 0.55]),
    ("stock_sd", [0.25, 0.55]),
    ("pace_strength", [0.5]),
    ("matchup_strength", [0.0, 1.0]),
]
GRID2 = GRID


def cal_objective(t) -> float:
    t = fixed_rows(t)
    return objective(apply_calibration(t, fit_calibration(t)))


def tune(run: B.Runner, p: PropParams, log=print, grid=None) -> tuple[PropParams, list]:
    ckpt = ensure(output_dir("nba")) / "props_candidate_ckpt.json"
    done: dict = json.loads(ckpt.read_text()) if ckpt.exists() else {}

    def ev(c: PropParams) -> float:
        k = json.dumps(asdict(c.settings), sort_keys=True)
        if k not in done:
            done[k] = cal_objective(run.scored(B.OBJECTIVE_SEASONS, c)[0])
            ckpt.write_text(json.dumps(done))
        return done[k]

    best = ev(p)
    hist = [{"start": round(best, 5)}]
    log(f"start {best:.5f}", flush=True)
    for key, values in (grid or GRID):
        for v in values:
            if getattr(p.settings, key) == v:
                continue
            c = replace(p, settings=replace(p.settings, **{key: v}))
            val = ev(c)
            hist.append({"change": {key: v}, "objective": round(val, 5)})
            log(f"  {key}={v}: {val:.5f}{'  *' if val < best - 1e-5 else ''}", flush=True)
            if val < best - 1e-5:
                best, p = val, c
    return p, hist


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune-sims", type=int, default=800)
    ap.add_argument("--test-sims", type=int, default=2000)
    ap.add_argument("--round2", action="store_true", help="refine from the saved candidate; old-model results are kept from the round-1 report")
    a = ap.parse_args(argv)
    B.KEEP_ALL = True
    t0 = time.time()
    inp = I.load()
    run = B.Runner(inp)
    old = PropParams.load()
    res = (Path(__file__).resolve().parents[3] / ".." / "docs" / "models" / "results").resolve()
    prev = json.loads((res / f"nba-props-candidate-{CANDIDATE_VERSION}.json").read_text()) if a.round2 else None
    base = PropParams.load(CANDIDATE_FILE) if a.round2 else old
    start = replace(base, settings=replace(base.settings, sims=a.tune_sims), calibration={})
    new, hist = tune(run, start, grid=GRID2 if a.round2 else None)
    out = {"old": prev["old"]} if prev else {}
    if prev:
        hist = prev["tuning_history"] + [{"round": 2}] + hist
    for tag, p in ((("new", new),) if prev else (("old", old), ("new", new))):
        p = replace(p, settings=replace(p.settings, sims=a.test_sims))
        tune_t, _ = run.scored(TUNE_SEASONS, p)
        cal = fit_calibration(fixed_rows(tune_t))
        raw, m = run.scored(TEST_SEASONS, p)
        raw = fixed_rows(raw)
        t = apply_calibration(raw, cal)
        out[tag] = {"settings": asdict(p.settings), "calibration": cal, "test_objective": round(objective(t), 5), "test": summarize(t, m)}
        print(tag, out[tag]["test_objective"], flush=True)
        if tag == "new":
            cand = replace(p, calibration=cal, settings=replace(p.settings, sims=10000),
                           provenance={"fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       "status": f"candidate {CANDIDATE_VERSION}: not active", "tuning_seasons": list(TUNE_SEASONS),
                                       "test_seasons": list(TEST_SEASONS)})
            d = cand.to_json()
            d["model_version"] = CANDIDATE_VERSION
            Path(CANDIDATE_FILE).write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
    report = {"model_id": "nba-props", "old_version": MODEL_VERSION, "candidate_version": CANDIDATE_VERSION,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tuning_seasons": list(TUNE_SEASONS),
              "objective_seasons": list(B.OBJECTIVE_SEASONS), "test_seasons": list(TEST_SEASONS), "tuning_history": hist,
              **out, "runtime_s": round(time.time() - t0, 1)}
    ensure(res)
    (res / f"nba-props-candidate-{CANDIDATE_VERSION}.json").write_text(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
