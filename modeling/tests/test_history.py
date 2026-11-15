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
    real_read = L.read  # the prediction ledgers are stubbed; the picks ledger this run writes is read for real
    monkeypatch.setattr(L, "read", lambda path: recs[path.stem] if path.stem in recs else real_read(path))
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

    # Picks: frozen from the pre-game record and graded on the selected side. 48.0 projected, so the nearest recorded
    # threshold is 50 at 45%: the pick is "under 50", and 55 yards makes it a miss. The home side at 56% won: a hit.
    picks = {p["id"]: p for p in day["picks"]}
    assert (picks["nfl:g1:moneyline"]["team"], picks["nfl:g1:moneyline"]["result"]) == ("HOM", "hit")
    pp = picks["nfl:g1:prop:p1:receiving_yards"]
    assert (pp["selection"], pp["line"], pp["actual"], pp["result"], pp["stat_label"]) == ("below", 50.0, 55.0, "miss", "Receiving yards")
    assert not any(k.startswith("nfl:g2") for k in picks)                # g2 has no recorded projection: no pick, nothing invented
    summary = json.loads((tmp_path / "data" / "published" / "history" / "nfl" / "picks_summary.json").read_text())
    assert summary["overall"]["games"]["hit"] == 1 and summary["overall"]["props"]["miss"] == 1
    # this game had already started when its picks were written: both are labelled reconstructed, never pre-game
    assert summary["provenance"]["moneyline"] == {"pre_game": 0, "reconstructed": 1}
    assert summary["provenance"]["prop"] == {"pre_game": 0, "reconstructed": 1}
    assert summary["provenance"]["spread"] == summary["provenance"]["total"] == {"pre_game": 0, "reconstructed": 0}  # never backfilled
    assert picks["nfl:g1:moneyline"]["frozen_before_start"] is False
    row = summary["by_date"][-1]                                          # winner, spread and total keep separate records
    assert row["moneyline"]["hit"] == 1 and row["spread"]["graded"] == 0 and row["total"]["graded"] == 0
    # a second build changes nothing and writes nothing
    again = history.build("nfl")["picks"]
    assert (again["game_picks_added"], again["prop_picks_added"], again["settled"], again["corrections"]) == (0, 0, 0, 0)


def test_spread_and_total_picks_are_only_written_before_the_game(tmp_path, monkeypatch):
    """A line is not part of the model's record, so a spread/total pick exists only if it was stored pre-game."""
    import json
    from datetime import datetime, timedelta, timezone

    import pandas as pd

    from modelroom import history
    from modelroom.common import ledger as L

    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path / "ledger"))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    soon, played, far = now + timedelta(minutes=30), now - timedelta(hours=5), now + timedelta(hours=9)
    day = now.date().isoformat()
    row = lambda gid, start, hs, as_, st: {"game_id": gid, "season": 2026, "game_date": min(day, start.date().isoformat()), "start_time": pd.Timestamp(start),  # noqa: E731
                                           "home": "H" + gid, "away": "A" + gid, "home_score": hs, "away_score": as_, "status": st}
    games = pd.DataFrame([row("old", played, 110, 100, "final"), row("soon", soon, None, None, "scheduled"), row("far", far, None, None, "scheduled")])
    monkeypatch.setattr(history, "_games_table", lambda league: games)
    monkeypatch.setattr(history, "_player_stats", lambda league: ({}, {}, {}))
    mk = {"spread": -4.5, "total": 220.5, "books": 9, "captured_at": (now - timedelta(hours=6)).isoformat(), "sources": {"the_odds_api"}}
    monkeypatch.setattr(history, "_market", lambda league: {"old": mk, "soon": mk, "far": mk})
    monkeypatch.setattr(history, "_sigmas", lambda league: (13.0, 18.0))
    rec = lambda gid, start: {"game_id": gid, "game_start": start.isoformat(), "generated_at": (min(now, start) - timedelta(hours=7)).isoformat(),  # noqa: E731
                              "model_version": "1", "pred_home_score": 112.0, "pred_away_score": 104.0, "pred_margin": 8.0, "pred_total": 216.0, "home_win_prob": 0.7}
    recs = {"nba": [rec("old", played), rec("soon", soon), rec("far", far)], "nba_props": []}
    real_read = L.read
    monkeypatch.setattr(L, "read", lambda path: recs[path.stem] if path.stem in recs else real_read(path))
    history.build("nba")
    from modelroom import picks as P
    stored = P.read_picks("nba")
    # already played when the picks ledger began: the recorded winner only. No spread or total is reconstructed.
    assert {k for k in stored if ":old:" in k} == {"nba:old:moneyline"}
    assert stored["nba:old:moneyline"]["backfilled"] is True and stored["nba:old:moneyline"]["frozen_before_start"] is False
    # starting in 30 minutes: all three are written now, before the game, with the side and the line
    assert {k for k in stored if ":soon:" in k} == {"nba:soon:moneyline", "nba:soon:spread", "nba:soon:total"}
    sp, tot = stored["nba:soon:spread"], stored["nba:soon:total"]
    assert (sp["team"], sp["line"], sp["frozen_before_start"], sp["backfilled"]) == ("Hsoon", -4.5, True, False)
    assert (tot["selection"], tot["line"]) == ("under", 220.5)
    # nine hours away: too early, the projection can still change
    assert not any(":far:" in k for k in stored)
    out = json.loads((tmp_path / "data" / "published" / "history" / "nba" / f"{min(day, soon.date().isoformat())}.json").read_text())
    res = {p["id"]: p["result"] for p in out["picks"]}
    assert res["nba:soon:spread"] == "pending" and res["nba:soon:total"] == "pending"   # not played: stays pending
    summary = json.loads((tmp_path / "data" / "published" / "history" / "nba" / "picks_summary.json").read_text())
    assert summary["provenance"]["spread"] == {"pre_game": 1, "reconstructed": 0}        # written before the game started
    assert summary["provenance"]["total"] == {"pre_game": 1, "reconstructed": 0}
    assert all(p["frozen_before_start"] for p in out["picks"] if p["id"].startswith("nba:soon:"))
    assert summary["overall"]["spread"]["pending"] == 1 and summary["overall"]["spread"]["graded"] == 0 and summary["overall"]["spread"]["hit_rate"] is None
