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
