"""Parlay engine (TEST, Moose 2026-11-27): joint probability math, correlation helpers, backtest pricing rules."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modelroom.parlay import backtest as BT
from modelroom.parlay import correlations as C
from modelroom.parlay.joint import bvnu, fair_american, frechet, genz, joint, nearest_corr

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "parlay-joint.json"


# ------------------------------------------------------------------------------------------------- joint
def test_bvnu_matches_shared_fixture():
    """The same reference values the TypeScript tests use, so both engines agree."""
    fx = json.loads(FIX.read_text())
    for h, k, r, ref in fx["bvnu"]:
        assert abs(bvnu(h, k, r) - ref) < 1e-9


def test_bvnu_closed_forms():
    assert bvnu(0, 0, 0) == pytest.approx(0.25)
    assert bvnu(0, 0, 0.5) == pytest.approx(0.25 + math.asin(0.5) / (2 * math.pi), abs=1e-10)
    assert bvnu(-math.inf, 0.3, 0.2) == pytest.approx(1 - 0.6179114221889526, abs=1e-12)
    assert bvnu(math.inf, 0, 0.9) == 0.0


def test_genz_three_variables_matches_reference():
    fx = json.loads(FIX.read_text())
    r = joint(fx["legs"], np.array(fx["R"]))
    assert r["method"].startswith("genz")
    assert abs(r["p"] - fx["ref3"]) < 4 * r["se"] + 1e-4


def test_joint_same_variable_and_edge_cases():
    R = np.eye(2)
    assert joint([{"var": 0, "side": 1, "p": 0.6}, {"var": 0, "side": 1, "p": 0.3}], R)["p"] == pytest.approx(0.3)
    assert joint([{"var": 0, "side": 1, "p": 0.6}, {"var": 0, "side": -1, "p": 0.6}], R)["p"] == pytest.approx(0.2)
    assert joint([{"var": 0, "side": 1, "p": 0.3}, {"var": 0, "side": -1, "p": 0.3}], R)["p"] == 0.0
    assert joint([{"var": 0, "side": 1, "p": 1.0}, {"var": 1, "side": 1, "p": 0.4}], R)["p"] == pytest.approx(0.4)
    assert joint([{"var": 0, "side": 1, "p": 0.0}, {"var": 1, "side": 1, "p": 0.4}], R)["p"] == 0.0
    assert joint([{"var": 0, "side": 1, "p": 0.6}, {"var": 1, "side": 1, "p": 0.5}], R)["p"] == pytest.approx(0.3)


def test_correlation_direction():
    legs = [{"var": 0, "side": 1, "p": 0.5}, {"var": 1, "side": 1, "p": 0.5}]
    up = joint(legs, np.array([[1, 0.4], [0.4, 1]]))["p"]
    down = joint(legs, np.array([[1, -0.4], [-0.4, 1]]))["p"]
    assert up > 0.25 > down
    flipped = joint([legs[0], {**legs[1], "side": -1}], np.array([[1, 0.4], [0.4, 1]]))["p"]
    assert flipped == pytest.approx(down)


def test_genz_independent_box_multiplies():
    p = genz(np.array([0.0, -0.5, 0.3]), np.array([np.inf, np.inf, np.inf]), np.eye(3), sims=2000)
    from statistics import NormalDist
    N = NormalDist()
    assert p["p"] == pytest.approx((1 - N.cdf(0)) * (1 - N.cdf(-0.5)) * (1 - N.cdf(0.3)), abs=1e-12)


def test_nearest_corr_repairs():
    bad = np.array([[1, 0.9, 0.9], [0.9, 1, -0.9], [0.9, -0.9, 1]])
    f = nearest_corr(bad)
    assert np.allclose(np.diag(f), 1)
    assert np.linalg.eigvalsh(f).min() > 0


def test_frechet_and_fair_odds():
    lo, hi = frechet([0.6, 0.7])
    assert lo == pytest.approx(0.3) and hi == 0.6
    assert frechet([0.2, 0.3, 0.4]) == (0.0, 0.2)
    assert fair_american(0.5) == -100 and fair_american(0.25) == 300 and fair_american(0) is None


# ------------------------------------------------------------------------------------------------- correlations
def test_normal_scores_and_fisher():
    s = C.normal_scores(pd.Series([3.0, 1.0, np.nan, 2.0]))
    assert np.isnan(s[2]) and s[1] < s[3] < s[0] and s[3] == pytest.approx(0.0)
    lo, hi = C.fisher_ci(0.3, 1000)
    assert lo < 0.3 < hi and hi - lo < 0.13
    assert C.fisher_ci(0.3, 2) == (-1.0, 1.0)


def test_keys_are_symmetric():
    assert C.key("team", "rebounds", "points") == C.key("team", "points", "rebounds") == "team|points|rebounds"
    assert C.key("ptotal", "points") == "ptotal|points"


def test_prior_z_uses_previous_games_only():
    df = pd.DataFrame({"pid": ["a"] * 12, "x": [10.0] * 11 + [100.0]})
    z, mean = C.prior_z(df, "pid", "x", 10, 8, 1.0)
    assert np.isnan(mean[:8]).all()
    assert mean.iloc[11] == pytest.approx(10.0)     # the 100 isn't in its own expectation
    assert z.iloc[11] == pytest.approx(90.0)        # floor of 1 used when spread is 0


def test_cell_marks_small_samples_insufficient():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(100)
    c = C.cell(x, x + rng.standard_normal(100))
    assert c["insufficient"] and c["n"] == 100
    c = C.cell(np.r_[x, x, x, x], np.r_[x, x, x, x], n_eff=50)
    assert not c["insufficient"] and c["n_eff"] == 50


def test_verdict_rules():
    assert C.verdict({"insufficient": False, "r": 0.01, "lo": -0.02, "hi": 0.04}) == "independent"
    assert C.verdict({"insufficient": False, "r": 0.02, "lo": 0.005, "hi": 0.035}) == "independent"   # negligible
    assert C.verdict({"insufficient": False, "r": 0.08, "lo": 0.04, "hi": 0.12}) == "dependent"
    assert C.verdict({"insufficient": True, "r": 0.5, "lo": 0.1, "hi": 0.9}) == "insufficient"


def test_cross_game_finds_independence_in_independent_data_and_dependence_when_present():
    rng = np.random.default_rng(3)
    rows = []
    for d in range(200):
        shared = rng.standard_normal()
        for g in range(6):
            for p in range(6):
                rows.append({"date": f"d{d}", "game_id": f"{d}-{g}", "points": rng.standard_normal(), "rebounds": 0.8 * shared + 0.6 * rng.standard_normal()})
    p = pd.DataFrame(rows)
    tr = pd.DataFrame({"date": [f"d{d}" for d in range(200) for _ in range(6)], "game_id": [f"{d}-{g}" for d in range(200) for g in range(6)],
                       "total_ns": rng.standard_normal(1200), "margin_ns": rng.standard_normal(1200)})
    xg = C.cross_game(p, tr, ["points", "rebounds"], seed=1)
    assert xg["cells"]["xgame|points|points"]["verdict"] == "independent"
    assert xg["cells"]["xgame|rebounds|rebounds"]["verdict"] == "dependent"   # a shared nightly factor is detected
    assert not xg["independent"]


def test_published_table_is_well_formed():
    t = json.loads((Path(__file__).resolve().parents[1] / "data" / "published" / "parlay_correlations.json").read_text())
    assert t["kind"] == "parlay_correlations" and t["schema"] == 1 and t["min_pairs"] == 300
    for lg in ("nba", "nfl"):
        L = t["leagues"][lg]
        assert L["cross_game"]["independent"] is True
        for k, c in L["cells"].items():
            if not c["insufficient"]:
                assert -1 <= c["lo"] <= c["r"] <= c["hi"] <= 1, k
                assert c["n"] >= 300
        assert set(L["estimation_seasons"]).isdisjoint(L["holdout_seasons"])
    # only aggregates: no player ids or names anywhere
    s = json.dumps(t)
    assert "player_id" not in s and "name" not in s


# ------------------------------------------------------------------------------------------------- backtest pricing
def _table(insufficient=False):
    return {"cells": {"same|points|rebounds": {"r": 0.3, "lo": 0.28, "hi": 0.32, "n": 1000, "insufficient": insufficient},
                      "team|points|points": {"r": 0.0, "lo": -0.02, "hi": 0.02, "n": 1000, "insufficient": False}},
            "cross_game": {"independent": True, "engine_r_band": 0.02, "cells": {}}}


def _leg(**k):
    base = {"date": "d", "game_id": "g", "player_id": "a", "team": "X", "market": "points", "p": 0.5, "y": 1.0, "side": 1}
    return {**base, **k}


def test_backtest_price_rules():
    same = [_leg(), _leg(market="rebounds")]
    r = BT.price(same, _table(), nfl=False)
    assert r["copula"] > r["indep"] == pytest.approx(0.25)
    assert BT.price(same, _table(insufficient=True), nfl=False)["copula"] is None
    cross = [_leg(), _leg(game_id="h", player_id="b")]
    assert BT.price(cross, _table(), nfl=False)["copula"] == pytest.approx(0.25)


def test_candidates_flip_sides_consistently():
    rows = pd.DataFrame([{"date": "d", "game_id": "g", "player_id": str(i), "team": "X", "market": "points", "p": 0.7, "y": 1.0} for i in range(400)])
    c = BT.candidates(rows, np.random.default_rng(0))
    under = c[c.side < 0]
    assert len(under) and np.allclose(under.p, 0.3) and (under.y == 0).all()
    assert ((c.p >= 0.2) & (c.p <= 0.8)).all()
