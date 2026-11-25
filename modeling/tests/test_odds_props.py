"""NBA player points lines (TEST): credit cap, one request per game per day, failure rules, key scrubbing, write-once
storage with verification, manifest chain, player matching and main-line selection. No network: a fake provider."""
import json
import urllib.error
from datetime import date, datetime, timezone

import pytest

from modelroom.archive import market_snapshots as MS
from modelroom.archive.store import ArchiveError, LocalStore
from modelroom.markets import prop_matching as PM
from modelroom.sources import odds_props as OP

KEY = "secretkey1234567890abcdef"
NOW = datetime(2026, 11, 25, 20, 40, tzinfo=timezone.utc)          # 12:40 PM PT
BOARD = {"games": [
    {"game_id": "G1", "start_time": "2026-11-26T03:00:00+00:00", "home": {"abbr": "DEN", "name": "Denver Nuggets"}, "away": {"abbr": "DAL", "name": "Dallas Mavericks"},
     "players": [{"player_id": "p1", "name": "Nikola Jokić"}, {"player_id": "p2", "name": "Kyrie Irving"}, {"player_id": "p3", "name": "Derrick Jones Jr."}]},
    {"game_id": "G2", "start_time": "2026-11-26T00:00:00+00:00", "home": {"abbr": "LAC", "name": "LA Clippers"}, "away": {"abbr": "BOS", "name": "Boston Celtics"},
     "players": [{"player_id": "p9", "name": "Jayson Tatum"}]}]}


def _ev(i, t, home="Denver Nuggets", away="Dallas Mavericks"):
    return {"id": f"e{i}", "commence_time": t, "home_team": home, "away_team": away}


EVENTS = [_ev(1, "2026-11-26T03:00:00Z"), _ev(2, "2026-11-26T00:00:00Z", "Los Angeles Clippers", "Boston Celtics"),
          _ev(3, "2026-11-25T20:45:00Z"), _ev(4, "2026-11-27T03:00:00Z")]   # e3 starts within 10 min; e4 is tomorrow


def _odds(eid, empty=False):
    if empty:
        return {"id": eid, "commence_time": "2026-11-26T03:00:00Z", "home_team": "Denver Nuggets", "away_team": "Dallas Mavericks", "bookmakers": []}
    out = lambda n, p, pr: {"name": n, "description": p, "point": pr[0], "price": pr[1]}
    return {"id": eid, "commence_time": "2026-11-26T03:00:00Z", "home_team": "Denver Nuggets", "away_team": "Dallas Mavericks", "bookmakers": [
        {"key": "bookA", "title": "Book A", "markets": [{"key": "player_points", "last_update": "2026-11-25T20:39:00Z", "outcomes": [
            out("Over", "Nikola Jokic", (27.5, -115)), out("Under", "Nikola Jokic", (27.5, -105)),
            out("Over", "Nikola Jokic", (30.5, 150)), out("Under", "Nikola Jokic", (30.5, -190)),
            out("Over", "Derrick Jones", (8.5, -110)), out("Under", "Derrick Jones", (8.5, -110)),
            out("Over", "Some Rookie", (5.5, -110)), out("Under", "Some Rookie", (5.5, -110))]}]},
        {"key": "bookB", "title": "Book B", "markets": [{"key": "player_points", "last_update": "2026-11-25T20:38:00Z", "outcomes": [
            out("Over", "Nikola Jokic", (28.5, -110)), out("Under", "Nikola Jokic", (28.5, -110))]}]}]}


class Fake:
    """The Odds API: tracks credits; events are free; each odds response costs 1 unless empty."""
    def __init__(self, remaining=300, empty=(), errors=None, cost=None, no_headers=False):
        self.remaining, self.calls, self.empty, self.errors, self.cost, self.no_headers = remaining, [], set(empty), errors or {}, cost, no_headers

    def __call__(self, url, key):
        self.calls.append(url)
        if "/events?" in url:
            return {"body": json.dumps(EVENTS).encode(), "headers": {"x-requests-remaining": str(self.remaining), "x-requests-last": "0"}}, {}
        eid = url.split("/events/")[1].split("/")[0]
        if eid in self.errors:
            e = self.errors[eid]
            raise urllib.error.HTTPError(url, e, "err", {"Retry-After": "1"}, None)
        empty = eid in self.empty
        c = 0 if empty else (self.cost or 1)
        self.remaining -= c
        h = {} if self.no_headers else {"x-requests-remaining": str(self.remaining), "x-requests-last": str(c)}
        return {"body": json.dumps(_odds(eid, empty)).encode(), "headers": h}, {}


def _run(tmp_path, fake, mode="main", now=NOW, lines=True, store=None):
    st = store or LocalStore(tmp_path / "r2")
    return OP.run(mode, KEY, BOARD, st, st, now, 10, lines, None, http=fake, sleep=lambda s: None), st


# ------------------------------------------------------------------ budget
def test_budget_reserves_game_lines_and_safety():
    b = OP.budget(325, date(2026, 11, 24), 10, True, 0)
    assert b["days_left"] == 16 and b["reserve"] == 12 * 15 + 30 and b["allowance"] == 7      # (325-210)/16
    assert OP.budget(325, date(2026, 11, 24), 10, False, 0)["reserve"] == 12 * 16 + 30
    assert OP.budget(200, date(2026, 11, 24), 10, True, 0)["allowance"] == 0                   # below the reserve
    assert OP.budget(500, date(2026, 12, 10), 10, True, 0)["allowance"] == min(15, (500 - (12 * 30 + 30)) // 31)
    assert OP.budget(5000, date(2026, 11, 24), 10, True, 0)["allowance"] == 15                  # daily ceiling
    assert OP.budget(325, date(2026, 11, 24), 10, True, 5)["allowance"] == 2                    # 7 a day, 5 already billed


def test_may_request_never_dips_into_reserve_or_floor():
    assert OP.may_request(211, 210) and not OP.may_request(210, 210) and not OP.may_request(15, 0)


def test_cycle_reset_dates():
    assert OP.cycle_reset(date(2026, 11, 24), 10) == date(2026, 12, 10)
    assert OP.cycle_reset(date(2026, 12, 9), 10) == date(2026, 12, 10)
    assert OP.cycle_reset(date(2026, 12, 10), 10) == date(2027, 1, 10)


# ------------------------------------------------------------------ run
def test_waits_for_game_lines(tmp_path):
    f = Fake()
    out, _ = _run(tmp_path, f, lines=False)
    assert "game lines go first" in out["stopped"] and f.calls == []


def test_one_request_per_game_today_earliest_first_and_stored(tmp_path):
    f = Fake(remaining=325)
    out, st = _run(tmp_path, f)
    odds_calls = [c for c in f.calls if "/odds?" in c]
    assert [c.split("/events/")[1].split("/")[0] for c in odds_calls] == ["e2", "e1"]      # today, not started, earliest first
    assert out["captured"] == 2 and out["credits_billed"] == 2 and out["stopped"] is None
    assert all("regions=us" in c and "markets=player_points" in c for c in odds_calls)
    again, _ = _run(tmp_path, f, store=st)                                                   # second run same day: nothing
    assert [c for c in f.calls if "/odds?" in c] == odds_calls and again["to_request"] == 0
    v = MS.verify_day(st, "2026-11-25")
    assert v["ok"] and v["runs"] == 1 and v["objects"] == 5                                   # 2 raw + 2 rows + view
    view = json.loads(st.get(MS.read_latest(st, "2026-11-25")["view"]))
    p1 = view["games"]["G1"]["players"]["p1"]
    assert p1["consensus_line"] == 28.0 and {b["title"] for b in p1["books"]} == {"Book A", "Book B"}
    assert next(b for b in p1["books"] if b["book"] == "bookA")["line"] == 27.5 and p1["alternates"] == 1


def test_cap_skips_when_budget_exhausted(tmp_path):
    out, _ = _run(tmp_path, Fake(remaining=211))
    assert out["captured"] == 0 and out["skipped_cap"] == 2 and out["credits_billed"] == 0


def test_cap_limits_to_daily_allowance(tmp_path):
    out, _ = _run(tmp_path, Fake(remaining=225))                 # (225 - 12*14 - 30) // 15 = 1 a day
    assert out["budget"]["allowance"] == 1 and out["captured"] == 1 and out["skipped_cap"] == 1


def test_cost_above_one_or_missing_headers_stops(tmp_path):
    out, _ = _run(tmp_path, Fake(cost=3))
    assert "cost 3" in out["stopped"] and out["captured"] == 1               # stored what was paid for, then stopped
    out, _ = _run(tmp_path / "b", Fake(no_headers=True))
    assert "credit headers" in out["stopped"] and out["captured"] == 0


def test_empty_market_gets_one_followup_only(tmp_path):
    f = Fake(empty={"e2"})
    out, st = _run(tmp_path, f)
    assert out["empty"] == 1 and out["captured"] == 1 and out["credits_billed"] == 1
    f.empty = set()
    fu, _ = _run(tmp_path, f, mode="followup", store=st)
    assert fu["to_request"] == 1 and fu["captured"] == 1
    fu2, _ = _run(tmp_path, f, mode="followup", store=st)
    assert fu2["to_request"] == 0
    assert MS.verify_day(st, "2026-11-25")["runs"] == 2


def test_auth_failure_stops_and_never_leaks_key(tmp_path):
    out, _ = _run(tmp_path, Fake(errors={"e2": 401}))
    assert "HTTP 401" in out["stopped"] and KEY not in json.dumps(out)
    out, _ = _run(tmp_path / "b", Fake(errors={"e2": 500}))
    assert out["errors"] == 1 and out["captured"] == 1 and KEY not in json.dumps(out)


def test_run_output_has_no_prices_lines_or_book_names(tmp_path):
    out, _ = _run(tmp_path, Fake())
    s = json.dumps(out)
    assert "Book A" not in s and "bookA" not in s and "27.5" not in s and "Jokic" not in s and "-115" not in s


# ------------------------------------------------------------------ storage
def test_write_once_and_verification_detects_tampering(tmp_path):
    out, st = _run(tmp_path, Fake())
    raw = next(k for k in st.list(MS.PREFIX) if k.endswith(".raw.json"))
    with pytest.raises(ArchiveError):
        st.put_once(raw, b"x")
    (tmp_path / "r2" / raw).write_bytes(b"tampered")
    assert not MS.verify_day(st, "2026-11-25")["ok"]


def test_raw_bytes_kept_exactly(tmp_path):
    _, st = _run(tmp_path, Fake())
    raw = next(k for k in st.list(MS.PREFIX) if "/e1/" in k and k.endswith(".raw.json"))
    assert st.get(raw) == json.dumps(_odds("e1")).encode()


# ------------------------------------------------------------------ matching and main line
def test_player_matching_exact_suffix_accent_alias_and_never_fuzzy():
    g = BOARD["games"][0]
    assert PM.match_player("Nikola Jokic", g, {}) == ("p1", "exact")
    assert PM.match_player("Derrick Jones", g, {}) == ("p3", "exact")
    assert PM.match_player("Kyrie Irvin", g, {})[0] is None
    assert PM.match_player("Jayson Tatum", g, {})[0] is None                          # other game's player
    assert PM.match_player("K. Irving", g, {PM.norm_name("K. Irving"): "p2"}) == ("p2", "alias")


def test_game_matching_by_nickname_and_time():
    assert PM.match_game(EVENTS[1], BOARD["games"])["game_id"] == "G2"                # LA vs Los Angeles Clippers
    assert PM.match_game(EVENTS[3], BOARD["games"]) is None                           # a day later


def test_main_line_most_balanced_ties_lower_alternates_kept():
    rows = PM.rows_from_response(_odds("e1"), BOARD["games"][0], {}, "t", "h")
    jok = [r for r in rows if r["player_name"] == "Nikola Jokic" and r["book_key"] == "bookA"]
    assert {r["line"]: r["is_main"] for r in jok} == {27.5: True, 30.5: False}
    assert next(r for r in rows if r["player_name"] == "Some Rookie")["player_id"] is None
    tie = [{"book_key": "b", "player_name": "x", "line": 10.5, "over_novig": 0.48, "is_main": False},
           {"book_key": "b", "player_name": "x", "line": 9.5, "over_novig": 0.52, "is_main": False}]
    PM.mark_main(tie)
    assert [r["is_main"] for r in tie] == [False, True]
