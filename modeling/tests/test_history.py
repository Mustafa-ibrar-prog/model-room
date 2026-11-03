from modelroom.history import _pregame, performance


def test_pregame_keeps_latest_record_before_start():
    recs = [
        {"game_id": "g", "generated_at": "2026-11-01T10:00:00Z", "game_start": "2026-11-01T18:00:00Z", "v": 1},
        {"game_id": "g", "generated_at": "2026-11-01T12:00:00Z", "game_start": "2026-11-01T18:00:00Z", "v": 2},
        {"game_id": "g", "generated_at": "2026-11-01T19:00:00Z", "game_start": "2026-11-01T18:00:00Z", "v": 3},
    ]
    assert _pregame(recs)["g"]["v"] == 2


def test_performance_blocks():
    props = [{"date": "2026-11-01", "market": "points", "player": "A", "player_id": "1", "p": p, "y": y}
             for p, y in [(0.8, 1.0), (0.3, 0.0), (0.6, 1.0), (0.2, 1.0)]]
    out = performance("nba", [], props)
    assert out["props"]["overall"]["n"] == 4
    assert out["props"]["overall"]["hit_rate"] == 0.75
    assert sum(b["n"] for b in out["props"]["calibration"]) == 4
    assert "games" not in out


def test_build_grades_recorded_projections_only(tmp_path, monkeypatch):
    import json

    import pandas as pd

    from modelroom import history
    from modelroom.common import ledger as L

    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path / "ledger"))
    games = pd.DataFrame([
        {"game_id": "g1", "season": 2026, "game_date": "2026-11-01", "start_time": pd.Timestamp("2026-11-01T18:00Z"), "home": "HOM", "away": "AWY",
         "home_score": 24, "away_score": 20, "status": "final"},
        {"game_id": "g2", "season": 2026, "game_date": "2026-11-01", "start_time": pd.Timestamp("2026-11-01T21:00Z"), "home": "H2", "away": "A2",
         "home_score": None, "away_score": None, "status": "scheduled"},
    ])
    monkeypatch.setattr(history, "_games_table", lambda league: games)
    monkeypatch.setattr(history, "_player_stats", lambda league: ({("g1", "p1"): {"rec_yds": 55.0}}, {"receiving_yards": "rec_yds"}, {"receiving_yards": "Receiving yards"}))
    recs = {
        "nfl": [
            {"game_id": "g1", "game_start": "2026-11-01T18:00:00+00:00", "generated_at": "2026-11-01T12:00:00+00:00", "model_version": "1", "pred_home_score": 23.0,
             "pred_away_score": 21.0, "pred_margin": 2.0, "pred_total": 44.0, "home_win_prob": 0.56},
            {"game_id": "g1", "game_start": "2026-11-01T18:00:00+00:00", "generated_at": "2026-11-01T19:00:00+00:00", "model_version": "1", "pred_home_score": 30.0,
             "pred_away_score": 10.0, "pred_margin": 20.0, "pred_total": 40.0, "home_win_prob": 0.99},   # after kickoff: never used
        ],
        "nfl_props": [
            {"game_id": "g1|p1", "nfl_game_id": "g1", "player_id": "p1", "player": "P One", "team": "HOM", "game_start": "2026-11-01T18:00:00+00:00",
             "generated_at": "2026-11-01T12:00:00+00:00", "model_version": "0.1.0",
             "probabilities": {"receiving_yards": {"mean": 48.0, "sd": 20.0, "40": 0.66, "50": 0.45, "60": 0.30}}},
        ],
    }
    monkeypatch.setattr(L, "read", lambda path: recs[path.stem])
    monkeypatch.setattr(history.ledger, "read", lambda path: recs[path.stem])
    out = history.build("nfl")
    assert out["graded_games"] == 1 and out["graded_thresholds"] == 3
    day = json.loads((tmp_path / "data" / "published" / "history" / "nfl" / "2026-11-01.json").read_text())
    g1 = next(g for g in day["games"] if g["game_id"] == "g1")
    assert g1["pregame"]["home_win_prob"] == 0.56                       # the pre-game record, not the later one
    assert g1["result"] == {"margin_error": -2.0, "total_error": 0.0, "winner_correct": True}
    g2 = next(g for g in day["games"] if g["game_id"] == "g2")
    assert g2["final"] is None and g2["result"] is None
    th = {t["k"]: t["hit"] for t in day["props"][0]["markets"]["receiving_yards"]["thresholds"]}
    assert th == {40.0: True, 50.0: True, 60.0: False}                  # 55 yards
    assert day["props"][0]["markets"]["receiving_yards"]["actual"] == 55.0
