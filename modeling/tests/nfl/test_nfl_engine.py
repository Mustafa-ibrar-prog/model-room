"""NFL engine tests. Synthetic plays below are test fixtures only."""
import json

import numpy as np
import pandas as pd
import pytest

from modelroom.nfl.config import RatingSettings
from modelroom.nfl.features import GARBAGE_WEIGHT, scrimmage_plays, team_games
from modelroom.nfl.ratings import EPARater

from ..conftest import real_nfl


def _plays(rows):
    base = {"play_type": "pass", "two_point_attempt": 0, "qb_dropback": 1, "wp": 0.5, "season": 2030, "week": 1,
            "home_team": "AAA", "passer_id": "q1", "passer_player_id": "q1", "passer": "Q One", "passer_player_name": "Q One",
            "yards_gained": 5, "interception": 0, "fumble_lost": 0, "down": 1, "third_down_converted": 0,
            "yardline_100": 50, "fixed_drive": 1, "fixed_drive_result": "Punt"}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_play_filter_and_garbage_time_weight():
    p = scrimmage_plays(_plays([
        {"game_id": "g", "posteam": "AAA", "defteam": "BBB", "epa": 0.5},
        {"game_id": "g", "posteam": "AAA", "defteam": "BBB", "epa": 1.0, "wp": 0.97},          # garbage time
        {"game_id": "g", "posteam": "AAA", "defteam": "BBB", "epa": 2.0, "play_type": "qb_kneel"},
        {"game_id": "g", "posteam": "AAA", "defteam": "BBB", "epa": 2.0, "two_point_attempt": 1},
        {"game_id": "g", "posteam": "AAA", "defteam": "BBB", "epa": np.nan},
    ]))
    assert len(p) == 2
    assert sorted(p["w"]) == [GARBAGE_WEIGHT, 1.0]
    tg = team_games(p)
    assert tg["epa"].iloc[0] == pytest.approx((0.5 + GARBAGE_WEIGHT * 1.0) / (1 + GARBAGE_WEIGHT))


def test_rater_recovers_known_strengths():
    """Synthetic round robin: offense[t] = 0.05*t, defense[t] = -0.02*t, home edge 0.03."""
    teams = [f"T{i}" for i in range(6)]
    rows, day = [], pd.Timestamp("2030-09-01")
    for rnd in range(10):
        for i in range(6):
            for j in range(i + 1, 6):
                h, a = (i, j) if (rnd + i + j) % 2 == 0 else (j, i)
                gid = f"{rnd}-{h}-{a}"
                date = (day + pd.Timedelta(days=7 * rnd)).date()
                for off, de, home in ((h, a, True), (a, h, False)):
                    rows.append({"game_id": gid, "team": teams[off], "opp": teams[de], "season": 2030,
                                 "game_date": date, "start_time": pd.Timestamp(date, tz="UTC"), "neutral": False,
                                 "is_home": home, "wplays": 60.0,
                                 "epa": 0.05 * off + (-0.02 * de) + (0.03 if home else -0.03)})
    tg = pd.DataFrame(rows)
    s = RatingSettings(half_life_games=1e9, season_carry=1.0, prior_games=1e-6, home_prior_games=1e-6)
    r = EPARater(tg, s).solve(np.datetime64("2031-01-01"), 2030)
    off = np.array([r.off[r.idx(t)] for t in teams])
    de = np.array([r.deff[r.idx(t)] for t in teams])
    assert np.allclose(off - off.mean(), 0.05 * (np.arange(6) - 2.5), atol=1e-6)
    assert np.allclose(de - de.mean(), -0.02 * (np.arange(6) - 2.5), atol=1e-6)
    assert r.home == pytest.approx(0.03, abs=1e-6)


def test_rater_ignores_games_on_or_after_cutoff():
    tg = pd.DataFrame([
        {"game_id": "a", "team": "X", "opp": "Y", "season": 2030, "game_date": pd.Timestamp("2030-09-01").date(),
         "start_time": pd.Timestamp("2030-09-01", tz="UTC"), "neutral": False, "is_home": True, "wplays": 60.0, "epa": 0.2},
        {"game_id": "b", "team": "X", "opp": "Y", "season": 2030, "game_date": pd.Timestamp("2030-09-08").date(),
         "start_time": pd.Timestamp("2030-09-08", tz="UTC"), "neutral": False, "is_home": True, "wplays": 60.0, "epa": 5.0},
    ])
    r1 = EPARater(tg, RatingSettings()).solve(np.datetime64("2030-09-08"), 2030)
    r2 = EPARater(tg.assign(epa=[0.2, -5.0]), RatingSettings()).solve(np.datetime64("2030-09-08"), 2030)
    assert r1.off[r1.idx("X")] == pytest.approx(r2.off[r2.idx("X")])
    assert r1.games_used == 1


@real_nfl
def test_real_board_is_internally_consistent():
    from modelroom.common.paths import published_board_path

    f = published_board_path("nfl")
    if not f.exists():
        pytest.skip("run `python -m modelroom nfl project` first")
    b = json.loads(f.read_text())
    assert b["schema_version"] == 1 and b["league"] == "nfl"
    for g in b["upcoming"]:
        p = g["projection"]
        assert p["margin"] == pytest.approx(p["home_score"] - p["away_score"], abs=0.11)
        assert p["total"] == pytest.approx(p["home_score"] + p["away_score"], abs=0.11)
        assert p["spread"] == pytest.approx(-p["margin"], abs=0.11)
        assert p["home_win_prob"] + p["away_win_prob"] == pytest.approx(1.0)
        assert g["result"] is None
    for g in b["recent"]:
        assert g["result"] is not None
