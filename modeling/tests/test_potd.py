"""Pick of the Day (player props only): selection rule, no invented lines, no forced picks, once-a-day immutable records,
grading (props, and the game-market picks recorded before the change), published file."""
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from modelroom import potd
from modelroom.common import ledger
from modelroom.common.paths import ledger_path

PREC = {"player": "A. Player", "player_id": "p1", "team": "PHI", "game_start": "2026-11-22T21:25:00+00:00", "model_version": "0.1.1",
        "generated_at": "2026-11-22T15:00:00+00:00", "seq": 9, "hash": "cd" * 32,
        "probabilities": {"receiving_yards": {"mean": 71.0, "sd": 25.0, "50": 0.80, "60": 0.68, "70": 0.52, "80": 0.36},
                          "receptions": {"mean": 5.1, "4": 0.70, "5": 0.55, "6": 0.40}}}
GAME = {"game_id": "G1", "home": "PHI", "away": "PIT"}


def _q(market="receiving_yards", line=59.5, **kw):
    return {"player_id": "p1", "league_game_id": "G1", "market": market, "line": line, "source": "test", "captured_at": "2026-11-22T15:30:00+00:00", **kw}


def test_prop_candidate_reads_the_ladder_at_the_line():
    c = potd.prop_candidates("nfl", GAME, PREC, _q(line=59.5))[0]
    assert c["selection"] == "over" and c["model_prob"] == 0.68 and c["projection"] == 71.0 and c["difference"] == 11.5
    assert c["market_prob"] is None and c["reference_prob"] == 0.5 and c["qualifies"]
    u = potd.prop_candidates("nfl", GAME, PREC, _q(line=79.5))[0]
    assert u["selection"] == "under" and u["model_prob"] == 0.64


def test_integer_line_has_push_probability():
    c = potd.prop_candidates("nfl", GAME, PREC, _q("receptions", 5.0))[0]
    assert c["push_prob"] == round(0.55 - 0.40, 4) and c["selection"] == "under" and c["model_prob"] == 0.45


def test_market_price_sets_the_edge_and_unknown_lines_are_never_invented():
    c = potd.prop_candidates("nfl", GAME, PREC, _q(line=59.5, over_prob=0.66, under_prob=0.38))[0]
    assert c["market_prob"] == 0.66 and c["edge"] == 0.02 and not c["qualifies"]
    assert potd.prop_candidates("nfl", GAME, PREC, _q(line=99.5)) == []            # outside the model's ladder: skip
    assert potd.prop_candidates("nfl", GAME, PREC, _q("rushing_yards", 30.5)) == []  # no model record for that stat


def _games(status="scheduled"):
    return pd.DataFrame([{"game_id": "G1", "home": "PHI", "away": "PIT", "start_time": pd.Timestamp("2026-11-22 21:25", tz="UTC"),
                          "status": status, "home_score": 24 if status == "final" else None, "away_score": 20 if status == "final" else None,
                          "game_date": "2026-11-22", "season": 2026}])


NOW = datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc)


def test_no_approved_source_means_no_pick_with_reason():
    r = potd.select_day("nfl", NOW, _games(), {("G1", "p1"): PREC}, [])
    assert r["status"] == "no_pick" and r["reason"] == "no approved player-prop line source" and r["format"] == "player_prop"
    assert potd.select_day("nfl", datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc), _games(), {}, []) is None   # no games left


def test_ineligible_stats_and_weak_props_never_forced():
    weak = [_q(line=69.5)]                                                       # 52%: below the bar
    assert potd.select_day("nfl", NOW, _games(), {("G1", "p1"): PREC}, weak)["reason"] == "no prop cleared the bar"
    odd = [_q("longest_reception", 20.5)]
    assert potd.select_day("nfl", NOW, _games(), {("G1", "p1"): PREC}, odd)["candidates_considered"] == 0


@pytest.mark.parametrize("sel,line,actual,status,want", [
    ("over", 59.5, 72, "final", "hit"), ("over", 59.5, 40, "final", "miss"), ("under", 5.0, 5, "final", "push"),
    ("over", 59.5, None, "final", "void"), ("over", 59.5, None, "scheduled", "pending"), ("over", 59.5, None, "postponed", "void")])
def test_prop_grading(sel, line, actual, status, want):
    assert potd.grade_prop({"selection": sel, "line": line}, {"status": status}, actual) == want


@pytest.mark.parametrize("market,sel,line,hs,as_,want", [
    ("spread", "home", -3.0, 24, 20, "hit"), ("spread", "away", 12.5, 30, 20, "hit"), ("total", "under", 46.5, 24, 20, "hit"),
    ("moneyline", "away", None, 24, 20, "miss")])
def test_game_market_picks_recorded_before_the_change_still_grade(market, sel, line, hs, as_, want):
    p = {"status": "pick", "market": market, "selection": sel, "line": line}
    assert potd.grade(p, {"status": "final", "home_score": hs, "away_score": as_}) == want


def test_run_freezes_once_per_day_and_grades_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path)); monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path / "data"))
    from modelroom import history as H
    from modelroom import published as PUB
    state = {"games": _games(), "lines": [_q(line=59.5)], "rec": PREC}
    monkeypatch.setattr(H, "_games_table", lambda lg: state["games"])
    monkeypatch.setattr(H, "_pregame", lambda recs: {"k": {**state["rec"], "nfl_game_id": "G1"}})
    monkeypatch.setattr(PUB, "is_published", lambda lg, r: True)
    monkeypatch.setattr(H, "_player_stats", lambda lg: ({("G1", "p1"): {"rec_yds": 72.0}}, {"receiving_yards": "rec_yds"}, {}))
    monkeypatch.setitem(potd.PROP_LINE_SOURCES, "test", lambda lg, now: state["lines"])
    potd.run(("nfl",), now=NOW)
    first = potd.read()
    assert len(first) == 1 and first[0]["market"] == "prop" and first[0]["line"] == 59.5 and first[0]["selection"] == "over"
    state["lines"] = [_q(line=49.5)]; state["rec"] = {**PREC, "player": "Changed"}           # later the same day: ignored
    potd.run(("nfl",), now=datetime(2026, 11, 22, 20, 0, tzinfo=timezone.utc))
    assert potd.read() == first
    state["games"] = _games("final")
    out = potd.run(("nfl",), now=datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc))
    assert out["graded"] == 1 and potd.read() == first and potd.read_grades()["potd:nfl:2026-11-22"]["result"] == "hit"
    potd.run(("nfl",), now=datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc))
    assert len(ledger.read_series(ledger_path("potd_grades"))) == 1
    for f in ledger.series_files(ledger_path("potd")) + ledger.series_files(ledger_path("potd_grades")):
        ledger.verify(f)
    pub = json.loads((tmp_path / "data" / "published" / "pick_of_the_day.json").read_text())
    row = pub["history"][0]
    assert row["result"] == "hit" and row["player"] == "A. Player" and row["stat"] == "receiving_yards"
    assert pub["record"]["nfl"]["validated"] is False and "Unvalidated" in pub["notice"]


def test_real_run_has_no_line_source_configured():
    assert potd.PROP_LINE_SOURCES == {}                # nothing is fetched or estimated until a source is approved


def test_game_line_recorded_before_props_only_is_kept_but_not_shown_or_counted():
    now = datetime(2026, 11, 19, 19, 0, tzinfo=timezone.utc)
    old = {"pick_key": "potd:nfl:2026-11-19", "date": "2026-11-19", "league": "nfl", "status": "pick", "market": "spread",
           "selection": "away", "team": "IND", "line": 12.5, "selected_at": "2026-11-19T08:02:00+00:00",
           "home": "HOU", "away": "IND", "model_prob": 0.7179, "projection": -5.0, "difference": 7.5}
    pub = potd.publish([old], {"potd:nfl:2026-11-19": {"result": "hit"}}, now)
    card = pub["today"]["nfl"]
    assert card["status"] == "no_pick" and card["reason"] == "no approved player-prop line source"
    assert pub["history"][0]["format"] == "game_line_before_props_only" and pub["history"][0]["line"] == 12.5   # kept as recorded
    assert pub["record"]["nfl"]["hit"] == 0 and pub["record"]["nfl"]["graded"] == 0                         # not counted
