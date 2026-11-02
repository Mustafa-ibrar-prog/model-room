"""NBA engine tests. Synthetic leagues below are test fixtures only."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from modelroom.nba import walkforward
from modelroom.nba.config import FittedAdjustments, RatingSettings
from modelroom.nba.features import game_possessions, rest_days
from modelroom.nba.project import finalize, rating_projection, situational
from modelroom.nba.ratings import SeasonPrior, SeasonRater

from ..conftest import real_nba


def synthetic_league(n_teams=6, days=40, seasons=(2030, 2031)):
    """Deterministic fake league: team i has offense +i, defense -i/2 (per 100), pace 100."""
    games, tg = [], []
    gid = 1
    for season in seasons:
        start = pd.Timestamp(f"{season - 1}-11-01")
        for d in range(days):
            shift = 1 + d % (n_teams - 1)
            for x in range(n_teams):
                y = (x + shift) % n_teams
                if x > y:
                    continue
                h, a = (x, y) if d % 2 == 0 else (y, x)
                date = start + pd.Timedelta(days=d)
                # off[t] = t, def[t] = -t/2, home edge 1.5 per team per 100
                eff_h = 110 + h + (-a / 2) + 1.5
                eff_a = 110 + a + (-h / 2) - 1.5
                games.append({"game_id": gid, "season": season, "season_type": "regular",
                              "start_time": date.tz_localize("UTC"), "game_date": date.date(),
                              "home_id": h, "away_id": a, "home_abbr": f"T{h}", "away_abbr": f"T{a}",
                              "home_name": f"Team {h}", "away_name": f"Team {a}", "neutral": False,
                              "status": "final", "periods": 4, "has_box": True,
                              "home_score": eff_h, "away_score": eff_a})
                for team, opp, pts, home in ((h, a, eff_h, True), (a, h, eff_a, False)):
                    # FGA − OREB + TOV + 0.44·FTA = 100 possessions
                    tg.append({"game_id": gid, "team_id": team, "opp_id": opp, "is_home": home, "pts": pts,
                               "fga": 85.0, "fta": 25.0, "oreb": 10.0, "tov": 14.0})
                gid += 1
    return pd.DataFrame(games), pd.DataFrame(tg)


def test_possession_formula():
    g, tg = synthetic_league(seasons=(2030,), days=2)
    p = game_possessions(g, tg)
    assert p["possessions"].iloc[0] == pytest.approx(85 - 10 + 14 + 0.44 * 25)
    assert p["pace"].iloc[0] == pytest.approx(p["possessions"].iloc[0])


def test_rest_days_and_back_to_back():
    g = pd.DataFrame({"game_id": [1, 2, 3], "season": [2030] * 3, "status": ["final"] * 3,
                      "game_date": pd.to_datetime(["2030-01-01", "2030-01-02", "2030-01-05"]).date,
                      "home_id": [1, 1, 2], "away_id": [2, 3, 1]})
    r = rest_days(g).set_index("game_id")
    assert r.loc[1, "home_rest"] == 4               # first game of the season
    assert r.loc[2, "home_rest"] == 1 and r.loc[2, "home_b2b"]
    assert r.loc[3, "away_rest"] == 3 and not r.loc[3, "away_b2b"]


def test_ratings_recover_known_team_strengths():
    g, tg = synthetic_league(seasons=(2030,), days=60)
    poss = game_possessions(g, tg)
    teams = sorted(set(g["home_id"]) | set(g["away_id"]))
    flat = SeasonPrior(teams, np.zeros(6), np.zeros(6), 110.0, 0.0, np.zeros(6), 100.0)
    s = replace(RatingSettings(), half_life_days=1e9, prior_games=1e-3, home_prior_games=1e-3)
    r = SeasonRater(g, poss, teams, s).solve(flat)
    net = r.off - r.deff
    true_net = np.array(teams) - (-np.array(teams) / 2)
    assert np.allclose(net - net.mean(), true_net - true_net.mean(), atol=1e-3)
    assert r.home == pytest.approx(1.5, abs=1e-3)


def test_walkforward_uses_only_earlier_games():
    """Changing a result on date D must not change any projection dated on or before D."""
    g, tg = synthetic_league()
    proj_a, _, _ = walkforward.run(g, tg, RatingSettings(), project_seasons={2031})
    target = g[g["season"] == 2031].iloc[len(g[g["season"] == 2031]) // 2]
    tg2 = tg.copy()
    tg2.loc[(tg2["game_id"] == target["game_id"]) & tg2["is_home"], "pts"] += 40
    proj_b, _, _ = walkforward.run(g, tg2, RatingSettings(), project_seasons={2031})
    on_or_before = proj_a["game_date"] <= target["game_date"]
    after = proj_a["game_date"] > target["game_date"]
    assert np.allclose(proj_a.loc[on_or_before, "margin_raw"], proj_b.loc[on_or_before, "margin_raw"])
    assert not np.allclose(proj_a.loc[after, "margin_raw"], proj_b.loc[after, "margin_raw"])


def test_projection_is_deterministic():
    g, tg = synthetic_league()
    a, _, _ = walkforward.run(g, tg, RatingSettings(), project_seasons={2031})
    b, _, _ = walkforward.run(g, tg, RatingSettings(), project_seasons={2031})
    pd.testing.assert_frame_equal(a, b)


def test_finalize_scores_and_conventions():
    df = pd.DataFrame({"game_id": [1], "margin_raw": [4.0], "total_raw": [220.0], "rest_adj": [1.0], "injury_adj": [np.nan]})
    out = finalize(df, FittedAdjustments(margin_sigma=12.0, total_points=0.0))
    r = out.iloc[0]
    assert r["proj_margin"] == 5.0 and r["model_spread"] == -5.0
    assert r["proj_home_score"] + r["proj_away_score"] == pytest.approx(220.0)
    assert 0.5 < r["home_win_prob"] < 1.0


def test_situational_signs():
    rest = pd.DataFrame({"game_id": [1], "home_rest": [3], "away_rest": [1], "home_b2b": [False], "away_b2b": [True]})
    out = situational(rest, FittedAdjustments(b2b_points=1.5, rest_points=0.2))
    assert out["rest_adj"].iloc[0] == pytest.approx(1.5 + 0.2 * 2)


@real_nba
def test_real_ratings_are_sensible():
    from modelroom.nba import ingest

    g, tg = ingest.load()
    _, finals, _ = walkforward.run(g, tg, RatingSettings(), until_season=2026)
    r = finals[2026]
    assert len(r.team_ids) == 30
    assert 105 < r.mu < 125           # league points per 100 possessions
    assert 95 < r.mu_pace < 105       # possessions per 48
    assert 0 < r.home < 3             # home edge per team per 100


def test_total_offsets_use_only_earlier_games():
    from modelroom.nba.project import total_offsets

    p = pd.DataFrame({
        "game_id": [1, 2, 3, 4],
        "season": [2030, 2030, 2031, 2031],
        "season_type": ["regular", "regular", "regular", "postseason"],
        "start_time": pd.to_datetime(["2030-01-01", "2030-01-02", "2031-01-01", "2031-05-01"], utc=True),
        "game_date": pd.to_datetime(["2030-01-01", "2030-01-02", "2031-01-01", "2031-05-01"]).date,
        "total_raw": [200.0, 200.0, 200.0, 200.0],
        "actual_total": [210.0, 220.0, np.nan, np.nan],
    })
    off = total_offsets(p, rolling_games=250)
    assert np.isnan(off.iloc[0])                    # nothing before the first game
    assert off.iloc[1] == pytest.approx(10.0)       # only game 1 is earlier
    assert off.iloc[2] == pytest.approx(15.0)       # games 1-2
    assert off.iloc[3] == pytest.approx(15.0)       # no earlier playoff history -> no playoff offset


@real_nba
def test_real_board_is_internally_consistent():
    import json

    from modelroom.common.paths import published_board_path

    f = published_board_path("nba")
    if not f.exists():
        pytest.skip("run `python -m modelroom nba project` first")
    b = json.loads(f.read_text())
    assert b["schema_version"] == 1 and b["league"] == "nba"
    assert b["data"]["market"]["connected"] in (True, False)
    for g in b["upcoming"]:
        p = g["projection"]
        assert p["margin"] == pytest.approx(p["home_score"] - p["away_score"], abs=0.11)
        assert p["spread"] == pytest.approx(-p["margin"], abs=0.11)
        assert 0 < p["home_win_prob"] < 1
        if g["market"] is None:
            assert g["edges"] is None               # no market, no invented edge
