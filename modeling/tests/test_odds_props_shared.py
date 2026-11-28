"""NBA points + NFL receiving yards from ONE daily allowance (Moose 2026-11-27), and per-book game lines to R2.
No network: a fake provider that serves both leagues."""
import json
from datetime import datetime, timezone

import pandas as pd

from modelroom.archive import market_snapshots as MS
from modelroom.archive.store import LocalStore
from modelroom.sources import gamelines_r2 as GL
from modelroom.sources import odds_props as OP

KEY = "secretkey1234567890abcdef"
NOW = datetime(2026, 11, 29, 13, 40, tzinfo=timezone.utc)          # Sunday 5:40 AM PT


def _ev(i, t, home, away):
    return {"id": i, "commence_time": t, "home_team": home, "away_team": away}


NBA_EV = [_ev(f"n{i}", f"2026-11-30T0{i}:00:00Z", "Denver Nuggets", "Dallas Mavericks") for i in range(1, 7)]     # 6 NBA games tonight
NFL_EV = [_ev("f1", "2026-11-29T18:00:00Z", "Minnesota Vikings", "Atlanta Falcons"), _ev("f2", "2026-11-29T21:25:00Z", "San Francisco 49ers", "Seattle Seahawks")]
NBA_BOARD = {"games": [{"game_id": "G1", "start_time": "2026-11-30T01:00:00+00:00", "home": {"abbr": "DEN", "name": "Denver Nuggets"},
                        "away": {"abbr": "DAL", "name": "Dallas Mavericks"}, "players": [{"player_id": "p1", "name": "Nikola Jokic"}]}]}
NFL_BOARD = {"games": [{"game_id": "2026_13_ATL_MIN", "start_time": "2026-11-29T18:00:00+00:00", "home": {"abbr": "MIN", "name": "Minnesota Vikings"},
                        "away": {"abbr": "ATL", "name": "Atlanta Falcons"}, "players": [{"player_id": "w1", "name": "Justin Jefferson"}]}]}


class Fake:
    def __init__(self, remaining):
        self.remaining, self.calls = remaining, []

    def __call__(self, url, key):
        self.calls.append(url)
        nfl = "americanfootball_nfl" in url
        if "/events?" in url:
            return {"body": json.dumps(NFL_EV if nfl else NBA_EV).encode(), "headers": {"x-requests-remaining": str(self.remaining), "x-requests-last": "0"}}, {}
        eid = url.split("/events/")[1].split("/")[0]
        mk = "player_reception_yds" if nfl else "player_points"
        ev = next(e for e in (NFL_EV if nfl else NBA_EV) if e["id"] == eid)
        who = "Justin Jefferson" if nfl else "Nikola Jokic"
        body = {**ev, "bookmakers": [{"key": "draftkings", "title": "DraftKings", "markets": [{"key": mk, "last_update": "2026-11-29T13:00:00Z", "outcomes": [
            {"name": "Over", "description": who, "point": 85.5 if nfl else 27.5, "price": -110},
            {"name": "Under", "description": who, "point": 85.5 if nfl else 27.5, "price": -110}]}]}]}
        self.remaining -= 1
        return {"body": json.dumps(body).encode(), "headers": {"x-requests-remaining": str(self.remaining), "x-requests-last": "1"}}, {}


def _day(tmp_path, remaining, mode="main", store=None):
    st = store or LocalStore(tmp_path / "r2")
    f = Fake(remaining)
    out = OP.run_day(mode, KEY, {"nba": NBA_BOARD, "nfl": NFL_BOARD}, st, st, NOW, 10, None, http=f, sleep=lambda s: None)
    return out, st, f


def test_split_allowance_is_proportional_and_never_starves_a_league():
    assert OP.split_allowance(4, {"nba": 6, "nfl": 2}) == {"nba": 3, "nfl": 1}
    assert OP.split_allowance(3, {"nba": 10, "nfl": 1}) == {"nba": 2, "nfl": 1}      # a lone Thursday game still gets one
    assert OP.split_allowance(1, {"nba": 10, "nfl": 1}) == {"nba": 1, "nfl": 0}
    assert OP.split_allowance(20, {"nba": 6, "nfl": 2}) == {"nba": 6, "nfl": 2}
    assert OP.split_allowance(5, {"nba": 6, "nfl": 0}) == {"nba": 5, "nfl": 0}
    assert OP.split_allowance(0, {"nba": 6, "nfl": 2}) == {"nba": 0, "nfl": 0}
    for a in range(0, 12):
        assert sum(OP.split_allowance(a, {"nba": 6, "nfl": 4}).values()) == min(a, 10)


def test_one_shared_allowance_and_skips_recorded(tmp_path):
    # 13 days left (Nov 29 -> Dec 10 reset is 11 days): reserve = 12*11 + 30 = 162; 200 left -> 3 a day
    out, st, f = _day(tmp_path, 200)
    b = out["budget"]
    assert b["allowance"] == 3 and out["shares"] == {"nba": 2, "nfl": 1}
    assert out["credits_billed"] == 3                                             # never more than the shared allowance
    paid = [c for c in f.calls if "/odds?" in c]
    assert sum("player_reception_yds" in c for c in paid) == 1 and sum("player_points" in c for c in paid) == 2
    assert out["leagues"]["nba"]["skipped_cap"] == 4 and out["leagues"]["nfl"]["skipped_cap"] == 1
    # NFL stored under its own private prefix with its own manifest chain; skipped games named in each manifest
    assert MS.verify_day(st, "2026-11-29", MS.NFL_PREFIX)["ok"] and MS.verify_day(st, "2026-11-29")["ok"]
    nfl_view = json.loads(st.get(MS.read_latest(st, "2026-11-29", MS.NFL_PREFIX)["view"]))
    assert nfl_view["market"] == "player_reception_yds"
    assert {s["status"] for s in nfl_view["game_status"].values()} <= {"captured", "skipped_cap"}
    assert "w1" in nfl_view["games"]["2026_13_ATL_MIN"]["players"]
    # a second trigger the same morning spends nothing
    again, _, f2 = _day(tmp_path, 197, store=st)
    assert not [c for c in f2.calls if "/odds?" in c]


def test_reserve_and_floor_still_hold(tmp_path):
    out, _, f = _day(tmp_path, 162)                   # exactly the reserve: nothing may be spent
    assert out["budget"]["allowance"] == 0 and not [c for c in f.calls if "/odds?" in c]


def test_key_never_in_output(tmp_path):
    out, _, _ = _day(tmp_path, 200)
    assert KEY not in json.dumps(out)


# ------------------------------------------------------------------ game lines per book
def test_gamelines_view_keeps_each_books_latest_line_for_upcoming_games():
    now = datetime(2026, 11, 29, 16, 0, tzinfo=timezone.utc)
    row = dict(league="nba", home_team="Denver Nuggets", away_team="Dallas Mavericks", source="the_odds_api", over_price=None, under_price=None, home_price=None, away_price=None, line=None)
    df = pd.DataFrame([
        {**row, "game_id": "G1", "commence_time": "2026-11-30T03:00:00Z", "sportsbook": "draftkings", "market": "spread", "line": -3.5, "home_price": -110, "away_price": -110, "captured_at": "2026-11-29T15:00:00Z", "collected_at": "2026-11-29T15:01:00Z"},
        {**row, "game_id": "G1", "commence_time": "2026-11-30T03:00:00Z", "sportsbook": "draftkings", "market": "spread", "line": -4.0, "home_price": -105, "away_price": -115, "captured_at": "2026-11-29T19:00:00Z", "collected_at": "2026-11-29T20:01:00Z"},
        {**row, "game_id": "G1", "commence_time": "2026-11-30T03:00:00Z", "sportsbook": "fanduel", "market": "total", "line": 228.5, "over_price": -112, "under_price": -108, "captured_at": "2026-11-29T15:00:00Z", "collected_at": "2026-11-29T15:01:00Z"},
        {**row, "game_id": "G1", "commence_time": "2026-11-30T03:00:00Z", "sportsbook": "betmgm", "market": "moneyline", "home_price": -170, "away_price": 145, "captured_at": "2026-11-29T15:00:00Z", "collected_at": "2026-11-29T15:01:00Z"},
        {**row, "game_id": "G0", "commence_time": "2026-11-29T15:00:00Z", "sportsbook": "draftkings", "market": "moneyline", "home_price": -150, "away_price": 130, "captured_at": "x", "collected_at": "2026-11-29T14:01:00Z"},
        {**row, "game_id": None, "commence_time": "2026-11-30T03:00:00Z", "sportsbook": "draftkings", "market": "moneyline", "home_price": -150, "away_price": 130, "captured_at": "x", "collected_at": "x"},
    ])
    v = GL.build_view(df, "nba", now)
    assert list(v["games"]) == ["G1"]                                             # started and unmatched games left out
    b = v["games"]["G1"]["books"]
    assert b["draftkings"]["spread"] == {"line": -4.0, "home": -105, "away": -115, "last_update": "2026-11-29T19:00:00Z"}   # newest collection
    assert b["fanduel"]["title"] == "FanDuel" and b["fanduel"]["total"]["over"] == -112
    assert b["betmgm"]["moneyline"]["away"] == 145


def test_gamelines_publish_is_private_write_once_and_verified(tmp_path):
    st = LocalStore(tmp_path / "r2")
    v = {"league": "nba", "generated_at": "2026-11-29T16:00:00+00:00", "games": {}}
    out = GL.publish(st, st, "nba", v, datetime(2026, 11, 29, 16, 0, tzinfo=timezone.utc))
    ptr = json.loads(st.get("v1/market-snapshots/nba/game-lines/latest.json"))
    assert ptr["view"].startswith("v1/market-snapshots/nba/game-lines/2026-11-29/view-") and out["games"] == 0
