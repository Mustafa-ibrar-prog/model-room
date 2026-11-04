"""NFL props 0.2.0 candidate: foundation fixes tuned on 2021-22, scored once on 2023-25 against 0.1.0.

    python -m modelroom.nfl.props.candidate [--tune-sims 1000]

Changes searched (each is a setting; the defaults reproduce 0.1.0 exactly):
  * share_half_life_games  target/carry shares on their own, shorter recency (lead-back carries ran low)
  * shock_kind + eff_sd_*  the per-game yards shock: symmetric instead of lognormal, sized per family
                           (pass / rec / rush) instead of one 0.30 for everything (distributions too wide)
  * the existing dispersion / prior settings are re-searched around their 0.1.0 values

Tuning objective = per-market log loss AFTER the per-market calibration the live board applies (fit on the
same tuning rows), so a setting can't win only because calibration would undo it later. Nothing here
touches params.json; the candidate goes to params_0.2.0.json, and the comparison report to
docs/models/results/nfl-props-candidate-0.2.0.json.
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
from .config import CANDIDATE_FILE, CANDIDATE_VERSION, FIT_SEASONS, MODEL_VERSION, TEST_SEASONS, TUNE_SEASONS, PropParams

GRID = [
    ("availability_weight", [1.0]),
    ("shock_kind", ["normal"]),
    ("eff_sd_pass", [0.0, 0.06, 0.12, 0.2]),
    ("eff_sd_rec", [0.08, 0.15, 0.22, 0.3]),
    ("eff_sd_rush", [0.08, 0.15, 0.22, 0.3]),
    ("share_half_life_games", [3.0, 5.0, 8.0]),
    ("carry_dispersion", [3.0, 6.0, 10.0]),
    ("target_dispersion", [10.0, 15.0, 25.0]),
    ("rate_prior", [20.0, 40.0]),
    ("snap_trend_strength", [0.5, 1.0, 1.5]),
]


def cal_objective(t) -> float:
    t = fixed_rows(t)
    return objective(apply_calibration(t, fit_calibration(t)))


def tune(run: B.Runner, p: PropParams, log=print) -> tuple[PropParams, list]:
    ckpt = ensure(output_dir("nfl")) / "props_candidate_ckpt.json"
    done: dict = json.loads(ckpt.read_text()) if ckpt.exists() else {}

    def ev(c: PropParams) -> float:
        k = json.dumps(asdict(c.settings), sort_keys=True)
        if k not in done:
            done[k] = cal_objective(run.scored(TUNE_SEASONS, c)[0])
            ckpt.write_text(json.dumps(done))
        return done[k]

    best = ev(p)
    hist = [{"start": round(best, 5)}]
    log(f"start {best:.5f}")
    for _ in range(2):
        changed = False
        for key, values in GRID:
            for v in values:
                if getattr(p.settings, key) == v:
                    continue
                c = replace(p, settings=replace(p.settings, **{key: v}))
                val = ev(c)
                hist.append({"change": {key: v}, "objective": round(val, 5)})
                log(f"  {key}={v}: {val:.5f}{'  *' if val < best - 1e-5 else ''}")
                if val < best - 1e-5:
                    best, p, changed = val, c, True
        if not changed:
            break
    return p, hist


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune-sims", type=int, default=1000)
    ap.add_argument("--test-sims", type=int, default=3000)
    a = ap.parse_args(argv)
    B.KEEP_ALL = True
    t0 = time.time()
    inp = I.load(set(FIT_SEASONS) | set(TUNE_SEASONS) | set(TEST_SEASONS))
    run = B.Runner(inp)
    old = PropParams.load()
    start = replace(old, settings=replace(old.settings, sims=a.tune_sims), calibration={})
    new, hist = tune(run, start)

    out = {}
    for tag, p in (("old", old), ("new", new)):
        p = replace(p, settings=replace(p.settings, sims=a.test_sims))
        tune_t, _ = run.scored(TUNE_SEASONS, p)
        cal = fit_calibration(fixed_rows(tune_t))
        raw, m = run.scored(TEST_SEASONS, p)
        raw = fixed_rows(raw)
        t = apply_calibration(raw, cal)
        out[tag] = {"settings": asdict(p.settings), "calibration": cal, "test_objective": round(objective(t), 5),
                    "test": summarize(t, m)}
        if tag == "new":
            cand = replace(p, calibration=cal, settings=replace(p.settings, sims=10000),
                           provenance={"fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       "status": f"candidate {CANDIDATE_VERSION}: not active", "tuning_seasons": list(TUNE_SEASONS),
                                       "test_seasons": list(TEST_SEASONS)})
            d = cand.to_json()
            d["model_version"] = CANDIDATE_VERSION
            Path(CANDIDATE_FILE).write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
    report = {"model_id": "nfl-props", "old_version": MODEL_VERSION, "candidate_version": CANDIDATE_VERSION,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "tuning_seasons": list(TUNE_SEASONS), "test_seasons": list(TEST_SEASONS), "tuning_history": hist,
              **out, "runtime_s": round(time.time() - t0, 1)}
    res = Path(__file__).resolve().parents[3] / ".." / "docs" / "models" / "results"
    res = res.resolve()
    ensure(res)
    (res / f"nfl-props-candidate-{CANDIDATE_VERSION}.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"old": out["old"]["test_objective"], "new": out["new"]["test_objective"], "settings": out["new"]["settings"]}, indent=1))


if __name__ == "__main__":
    main()
