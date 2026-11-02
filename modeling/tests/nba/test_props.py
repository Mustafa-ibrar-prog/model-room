"""NBA prop engine. Synthetic context checks the mechanics; real-data tests skip without downloaded data."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from modelroom.nba.props import model as M
from modelroom.nba.props.config import PropParams, PropSettings, support_level

from ..conftest import has_real


def _ctx(missed=None) -> M.Context:
    ids = [f"p{i}" for i in range(9)]
    P = pd.DataFrame(index=ids)
    P["name"] = [f"Player {i}" for i in range(9)]
    P["team"] = "AAA"
    P["group"] = ["G", "G", "F", "F", "C", "G", "F", "C", "G"]
    P["last_game"] = pd.Timestamp("2030-01-09")
    P["minutes_when_playing"] = [36, 34, 32, 30, 28, 22, 20, 16, 12.0]
    P["starter_rate"] = [1, 1, 1, 1, 1, 0, 0, 0, 0.0]
    for r, v in {"fg2m": 0.15, "fg3m": 0.06, "ftm": 0.1, "reb": 0.18, "ast": 0.1, "stl": 0.03, "blk": 0.02}.items():
        P[f"{r}_pm"] = v
    P["usage_pm"] = 0.5
    P["n_games"] = 40
    P["n_minutes"] = 1000.0
    P["appear_rate"] = 1.0
    P["missed_in_row"] = 0.0
    if missed:
        P.loc[missed, "missed_in_row"] = 3.0
    return M.Context(pd.Timestamp("2030-01-10"), 2030, P, pd.DataFrame(), pd.Series({"AAA": 99.0, "BBB": 99.0}), {"pace": 99.0})


P0 = PropParams(replace(PropSettings(), sims=4000))


def test_points_are_built_from_makes_and_minutes_fill_the_game():
    out = M.project_team(_ctx(), "g", "AAA", "BBB", 0.0, 99.0, P0, np.random.default_rng(1))
    x = out[0]
    assert np.all(x.sims["pra"] == x.sims["pts"] + x.sims["reb"] + x.sims["ast"])
    assert np.all(x.sims["pts"] >= 3 * x.sims["fg3m"])
    assert sum(o.inputs["projected_minutes"] for o in out) == pytest.approx(240 * 1.012, rel=0.05)
    probs = [x.prob("pts", k) for k in (5, 10, 15, 20, 25, 30)]
    assert all(a >= b for a, b in zip(probs, probs[1:]))


def test_ruled_out_starter_gives_minutes_and_usage_to_teammates():
    base = {o.player_id: o for o in M.project_team(_ctx(), "g", "AAA", "BBB", 0, 99, P0, np.random.default_rng(2))}
    after = {o.player_id: o for o in M.project_team(_ctx(missed=["p0"]), "g", "AAA", "BBB", 0, 99, P0, np.random.default_rng(2))}
    assert "p0" not in after
    assert after["p5"].inputs["projected_minutes"] > base["p5"].inputs["projected_minutes"]
    assert after["p1"].inputs["usage_freed_by_absences"] > 0 and after["p1"].inputs["teammates_out"] == "Player 0"


def test_blowouts_trim_starters():
    close = M.project_team(_ctx(), "g", "AAA", "BBB", 0, 99, P0, np.random.default_rng(3))
    blow = M.project_team(_ctx(), "g", "AAA", "BBB", 20, 99, P0, np.random.default_rng(3))
    assert blow[0].inputs["projected_minutes"] < close[0].inputs["projected_minutes"]


def test_seeded_projections_reproduce():
    games = pd.DataFrame([{"game_id": "g1", "home_abbr": "AAA", "away_abbr": "BBB", "proj_margin": 3.0, "proj_pace": 100.0}])
    a = M.project_games(_ctx(), games, P0, seed=20300110)
    b = M.project_games(_ctx(), games, P0, seed=20300110)
    assert all(np.array_equal(x.sims["pts"], y.sims["pts"]) for x, y in zip(a, b))


def test_support_levels():
    assert support_level(40, 1200)[0] == "ok"
    assert support_level(8, 150)[0] == "limited"
    assert support_level(2, 40)[0] == "insufficient"


@pytest.mark.skipif(not has_real("nba", "games"), reason="run `python -m modelroom nba ingest` first")
def test_real_player_table_and_no_lookahead():
    from modelroom.nba import ingest
    from modelroom.nba.features import game_possessions
    from modelroom.nba.props import data

    pg = data.load()
    v = data.validate(pg)
    assert v["points_identity"] == 1.0 and v["duplicates"] == 0
    games, tg = ingest.load()
    pace = game_possessions(games, tg)[["game_id", "pace"]].astype({"game_id": str})
    ctx = M.build(pg, pace, pd.Timestamp("2025-01-15"), 2025, PropSettings())
    assert (ctx.players["last_game"] < pd.Timestamp("2025-01-15")).all()
    assert len(ctx.team_pace) == 30
