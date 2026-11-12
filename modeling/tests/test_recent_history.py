"""Recent form on the props board: last 10 played games, this season's regular-season averages, opportunity kept apart.
Display only: attach() must read past games before the cutoff and never touch a projection."""
import pandas as pd

from modelroom.common import recent


def _pg():
    rows = []
    for i in range(14):
        d = pd.Timestamp("2026-10-01") + pd.Timedelta(days=2 * i)
        season = 2027 if i >= 4 else 2026
        rows.append({"player_id": "7", "game_date": d.date(), "opp": f"T{i}", "season": season, "season_type": 2 if i != 5 else 3,
                     "pts": float(i), "minutes": 30.0 + i, "played": i != 8})
    rows.append({"player_id": "7", "game_date": pd.Timestamp("2026-11-30").date(), "opp": "FUT", "season": 2027, "season_type": 2,
                 "pts": 99.0, "minutes": 40.0, "played": True})  # after the cutoff: never shown
    return pd.DataFrame(rows)


def _games():
    return [{"players": [{"player_id": "7", "markets": {"points": {"mean": 20.0}}}, {"player_id": "8", "markets": {"points": {}}}]}]


def test_last_ten_season_and_opportunity():
    pg = _pg()
    gj = _games()
    before = {k: v for k, v in gj[0]["players"][0].items()}
    recent.attach(gj, pg, {"points": "pts"}, pd.Timestamp("2026-11-01"), pg["played"], season=2027,
                  regular=pg["season_type"].eq(2), opportunity={"minutes": "Minutes", "missing_col": "X"})
    p = gj[0]["players"][0]
    assert {k: v for k, v in p.items() if k != "recent"} == before  # nothing else on the player changes
    r = p["recent"]
    assert len(r["games"]) == 10 and r["values"]["points"][0] == 13.0  # newest first, the DNP (i=8) and the future game excluded
    assert 8.0 not in r["values"]["points"] and 99.0 not in r["values"]["points"]
    assert r["games"][-1]["season"] == 2026  # crosses into the earlier season, labelled
    assert r["opportunity"] == [{"key": "minutes", "label": "Minutes"}]  # unknown columns are dropped
    assert r["games"][0]["minutes"] == 43.0
    s = r["season"]
    # 2027 regular season before the cutoff: i = 4, 6, 7, 9, 10, 11, 12, 13 (5 is a playoff row, 8 did not play)
    assert s["season"] == 2027 and s["games"] == 8
    assert s["avg"]["points"] == round((4 + 6 + 7 + 9 + 10 + 11 + 12 + 13) / 8, 2)
    assert "recent" not in gj[0]["players"][1]  # no history: no block, nothing invented


def test_season_with_no_games_is_explicit():
    pg = _pg()
    gj = _games()
    recent.attach(gj, pg, {"points": "pts"}, pd.Timestamp("2026-11-01"), pg["played"], season=2028, regular=pg["season_type"].eq(2))
    assert gj[0]["players"][0]["recent"]["season"] == {"season": 2028, "games": 0, "avg": {}, "opportunity": {}}
