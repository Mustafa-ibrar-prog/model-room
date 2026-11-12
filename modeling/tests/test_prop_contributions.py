"""P3: projection contributions are bookkeeping only. They add up to the simulated mean, and recording them draws no
random numbers (the simulation is identical with the bookkeeping replaced by a no-op)."""
from __future__ import annotations

import numpy as np
import pytest

from modelroom.nba.props import model as NBA
from modelroom.nfl.props import model as NFL

from .nba.test_props import P0 as NBA_P0, _ctx as nba_ctx
from .nfl.test_props import _ctx as nfl_ctx, _params as nfl_params


def _sum(c: dict) -> float:
    return sum(v for k, v in c.items() if k != "final")


def test_nba_contributions_add_up_to_the_simulated_mean():
    out = NBA.project_team(nba_ctx(missed=["p0"]), "g", "AAA", "BBB", 12.0, 101.0, NBA_P0, np.random.default_rng(5))
    for x in out:
        c = x.inputs["contributions"]
        assert c["order"][0] == "baseline" and c["order"][-1] == "simulation"
        for stat, ch in c["stats"].items():
            assert ch["final"] == pytest.approx(float(np.mean(x.sims[stat])), abs=1e-3)
            assert _sum(ch) == pytest.approx(ch["final"], abs=0.01)
    # A teammate is out: usage boost recorded for scoring, none for rebounds; a 12-point margin trims starters.
    p1 = next(x for x in out if x.player_id == "p1").inputs["contributions"]["stats"]
    assert p1["pts"]["usage"] > 0 and p1["reb"]["usage"] == 0
    assert p1["pts"]["blowout"] < 0
    assert p1["pts"]["pace"] > 0  # 101 projected vs the team's usual 99


def test_nba_bookkeeping_does_not_touch_the_simulation(monkeypatch):
    a = NBA.project_team(nba_ctx(missed=["p0"]), "g", "AAA", "BBB", 12.0, 101.0, NBA_P0, np.random.default_rng(9))
    monkeypatch.setattr(NBA, "contributions", lambda *a, **k: {})
    b = NBA.project_team(nba_ctx(missed=["p0"]), "g", "AAA", "BBB", 12.0, 101.0, NBA_P0, np.random.default_rng(9))
    for x, y in zip(a, b):
        assert x.player_id == y.player_id
        assert all(np.array_equal(x.sims[k], y.sims[k]) for k in x.sims)


def test_nfl_contributions_add_up_and_cover_the_isolated_markets():
    out = NFL.project_team(nfl_ctx(), "g", "AAA", "BBB", -3.0, 44.0, "qb1", None, None, nfl_params(), np.random.default_rng(4))
    stat = {"receptions": "receptions", "receiving_yards": "rec_yds", "rushing_attempts": "carries", "rushing_yards": "rush_yds",
            "passing_attempts": "pass_att", "passing_completions": "pass_cmp", "passing_yards": "pass_yds"}
    by = {x.player_id: x for x in out}
    assert set(by["qb1"].inputs["contributions"]["stats"]) >= {"passing_attempts", "passing_completions", "passing_yards"}
    assert set(by["wr1"].inputs["contributions"]["stats"]) >= {"receptions", "receiving_yards"}
    for x in out:
        for mk, ch in x.inputs["contributions"]["stats"].items():
            if ch is None:  # zero share: the chain's factors are undefined, so it is marked unavailable, not estimated
                assert float(np.mean(x.sims[stat[mk]])) < 0.05  # the share is floored at 1e-4 in the simulation
                continue
            assert ch["final"] == pytest.approx(float(np.mean(x.sims[stat[mk]])), abs=1e-3)
            assert _sum(ch) == pytest.approx(ch["final"], abs=0.01)
    # Markets whose mean can't be isolated as a chain (TDs, longest catch, combos, fantasy) are simply not recorded.
    assert "anytime_td" not in by["wr1"].inputs["contributions"]["stats"]


def test_nfl_bookkeeping_does_not_touch_the_simulation(monkeypatch):
    run = lambda: NFL.project_team(nfl_ctx(), "g", "AAA", "BBB", -3.0, 44.0, "qb1", None, None, nfl_params(), np.random.default_rng(8))  # noqa: E731
    a = run()
    monkeypatch.setattr(NFL, "_chain", lambda *a, **k: None)
    b = run()
    for x, y in zip(a, b):
        assert x.player_id == y.player_id
        assert all(np.array_equal(x.sims[k], y.sims[k]) for k in x.sims)


def test_chain_marks_a_non_finite_factor_unavailable():
    assert NFL._chain(10.0, [("game_environment", 1.1), ("lineup", float("nan"))], np.ones(5)) is None
    c = NFL._chain(10.0, [("game_environment", 1.1), ("matchup_efficiency", 0.5)], np.full(5, 5.4))
    assert c == {"baseline": 10.0, "game_environment": 1.0, "matchup_efficiency": -5.5, "simulation": -0.1, "final": 5.4}
