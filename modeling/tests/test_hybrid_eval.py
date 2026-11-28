"""Hybrid evaluation protocol (TEST research): chronological fits only, capped adjustment, honest verdicts."""
import numpy as np
import pandas as pd

from modelroom.nba.props import hybrid_eval as H


def _rows(signal: float, n_days=240, per_day=60, seed=1):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2024-10-20", periods=n_days).strftime("%Y-%m-%d")
    rows = []
    for d in days:
        for _ in range(per_day):
            x = {f: rng.normal() for f in H.FEATURES}
            base = rng.uniform(0.2, 0.8)
            true = H.sigm(H.logit(base) + signal * x["matchup"])
            rows.append({"date": d, "season": 2025, "market": "points", "pg": "g|p", "K": 10.0, "p": base, "y": float(rng.random() < true), **x})
    return pd.DataFrame(rows)


def test_real_signal_is_found_out_of_sample():
    out = H.walk_forward(_rows(0.4))
    assert out["overall"]["ll_gain"]["ci95"][0] > 0
    assert out["verdict"].startswith("hybrid improves")
    beta = dict(zip(out["final_coefficients"]["features"], out["final_coefficients"]["beta"]))
    assert beta["matchup"] > 0.25 and abs(beta["b2b"]) < 0.1


def test_noise_is_not_claimed_as_improvement():
    out = H.walk_forward(_rows(0.0, seed=3))
    assert not out["verdict"].startswith("hybrid improves")


def test_fits_use_only_earlier_months_and_adjustments_are_capped():
    R = _rows(3.0)
    out = H.walk_forward(R)
    for c in out["monthly_coefficients"]:
        assert c["train_n"] == int((R["date"] < c["month"] + "-01").sum())
    assert out["adjustment_size"]["share_capped"] > 0
    p = np.array([0.5, 0.5]); X = np.array([[10.0] + [0] * 6, [-10.0] + [0] * 6])
    adj = H.adjust(p, X, np.ones(7))
    assert np.allclose(H.logit(adj), [H.CAP, -H.CAP])
