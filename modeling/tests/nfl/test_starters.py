"""Projected starting QB: roster + injury report + depth chart as of kickoff, never the after-the-fact field."""
import pandas as pd
import pytest

from modelroom.nfl import starters


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path))
    (tmp_path / "processed" / "nfl").mkdir(parents=True)
    games = pd.DataFrame([
        # week 9: the starter (S) is back on the roster and ranked 1 again; the schedule field still says B
        {"game_id": "g9", "season": 2026, "week": 9, "game_date": "2026-11-05", "start_time": pd.Timestamp("2026-11-06T01:15Z"),
         "home_team": "BAL", "away_team": "JAX", "home_qb_id": "B", "away_qb_id": "J", "home_qb_name": "Backup", "away_qb_name": "Jax QB", "status": "scheduled"},
        # week 10: S is Out on the injury report, so B starts even though the chart still lists S first
        {"game_id": "g10", "season": 2026, "week": 10, "game_date": "2026-11-12", "start_time": pd.Timestamp("2026-11-13T01:15Z"),
         "home_team": "BAL", "away_team": "JAX", "home_qb_id": None, "away_qb_id": None, "home_qb_name": None, "away_qb_name": None, "status": "scheduled"},
    ])
    ro = pd.DataFrame([
        {"season": 2026, "week": w, "team": t, "position": "QB", "gsis_id": g, "full_name": n, "status": "ACT"}
        for w in (8, 9) for t, g, n in (("BAL", "S", "Starter"), ("BAL", "B", "Backup"), ("JAX", "J", "Jax QB"))
    ])
    inj = pd.DataFrame([{"season": 2026, "week": 10, "team": "BAL", "gsis_id": "S", "report_status": "Out"}])
    pg = pd.DataFrame([
        {"game_id": "g8", "team": "BAL", "player_id": "B", "pass_att": 30, "game_date": "2026-10-29"},
        {"game_id": "g8", "team": "JAX", "player_id": "J", "pass_att": 35, "game_date": "2026-10-29"},
    ])
    monkeypatch.setattr(starters.player_data, "rosters", lambda seasons: ro)
    monkeypatch.setattr(starters.player_data, "load", lambda: (pg, None, None))
    from modelroom.nfl.props import inputs as PI
    monkeypatch.setattr(PI, "injuries", lambda: inj)
    snap = pd.Timestamp("2026-11-04T12:00Z")
    monkeypatch.setattr(starters, "_depth", lambda seasons: ({}, [snap], {snap: {"S": 1, "B": 2, "J": 1}}))
    return games


def test_returning_starter_and_injured_starter(world):
    st = starters.build(world).set_index(["game_id", "team"])
    assert st.loc[("g9", "BAL"), "qb_id"] == "S" and st.loc[("g9", "BAL"), "source"] == "depth chart"
    assert st.loc[("g9", "BAL"), "listed_qb_id"] == "B"            # the schedule field would have used the backup
    assert st.loc[("g10", "BAL"), "qb_id"] == "B"                  # starter ruled Out
    assert st.loc[("g9", "JAX"), "qb_id"] == "J"


def test_engines_use_the_schedule_field_until_switched(world, monkeypatch):
    starters.build(world)
    monkeypatch.delenv("MODELROOM_NFL_QB_SOURCE", raising=False)
    from modelroom.nfl import ingest
    assert ingest.qb_source() == "listed"
    g = starters.apply(world, "projected")
    assert g.set_index("game_id").loc["g9", "home_qb_id"] == "S" and g.set_index("game_id").loc["g9", "home_qb_id_listed"] == "B"
