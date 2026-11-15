"""Picks are graded on the side that was selected and stored, never on which side of the model's number the result fell.
The cases are the ones in the brief: NBA totals, point spreads, moneylines, player props, pushes, voids, pending."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from modelroom import picks as P
from modelroom.common import ledger

UTC = timezone.utc
GAME = {"game_id": "g1", "date": "2026-11-13", "home": "AAA", "away": "BBB"}
REC = {"seq": 7, "hash": "h" * 64, "generated_at": "2026-11-13T20:00:00+00:00", "game_start": "2026-11-14T00:00:00+00:00",
       "model_version": "1.1.0", "home_win_prob": 0.7, "pred_margin": 9.0, "pred_total": 228.0}
final = lambda home, away: {"home": home, "away": away}  # noqa: E731


def pick(market, selection, line=None, **kw):
    return {"market": market, "selection": selection, "line": line, **kw}


# ---------------------------------------------------------------- totals
@pytest.mark.parametrize("side,line,total,want", [
    ("over", 225.5, 228, "hit"),     # picks Over 225.5, final 228
    ("under", 225.5, 220, "hit"),    # picks Under 225.5, final 220
    ("under", 225.5, 230, "miss"),   # picks Under 225.5, final 230
    ("over", 225.5, 220, "miss"),
    ("over", 226, 226, "push"),
    ("under", 226, 226, "push"),
])
def test_totals(side, line, total, want):
    assert P.grade(pick("total", side, line), "final", final(total - 100, 100)) == want


def test_total_is_graded_on_the_selected_side_not_the_model_number():
    # The model projected 228 and took Under 230.5. The final, 229, is ABOVE the model's number and still a hit.
    assert P.grade(pick("total", "under", 230.5, model_number=228.0), "final", final(119, 110)) == "hit"
    # The model projected 228 and took Over 225.5. The final, 226, is BELOW the model's number and still a hit.
    assert P.grade(pick("total", "over", 225.5, model_number=228.0), "final", final(116, 110)) == "hit"


# ---------------------------------------------------------------- spreads (line is the selected team's own line)
@pytest.mark.parametrize("side,line,home,away,want", [
    ("home", -7.5, 122, 100, "hit"),   # Team A -7.5, wins by 22
    ("home", -7.5, 105, 100, "miss"),  # Team A -7.5, wins by 5
    ("away", +7.5, 103, 100, "hit"),   # Team B +7.5, loses by 3
    ("away", +7.5, 112, 100, "miss"),  # Team B +7.5, loses by 12
    ("away", -3.0, 100, 110, "hit"),   # road favourite covers
    ("home", +3.0, 100, 110, "miss"),
    ("home", -7.0, 107, 100, "push"),
    ("away", +7.0, 107, 100, "push"),
    ("home", +2.5, 101, 100, "hit"),   # underdog wins outright
])
def test_spreads(side, line, home, away, want):
    assert P.grade(pick("spread", side, line), "final", final(home, away)) == want


# ---------------------------------------------------------------- moneyline
def test_moneyline():
    assert P.grade(pick("moneyline", "home"), "final", final(110, 100)) == "hit"
    assert P.grade(pick("moneyline", "home"), "final", final(100, 110)) == "miss"
    assert P.grade(pick("moneyline", "away"), "final", final(100, 110)) == "hit"
    assert P.grade(pick("moneyline", "away"), "final", final(110, 100)) == "miss"
    assert P.grade(pick("moneyline", "home"), "final", final(20, 20)) == "push"  # an NFL tie


# ---------------------------------------------------------------- player props
def test_props_at_the_models_own_threshold():
    assert P.grade(pick("prop", "at_least", 20), "final", final(1, 0), actual=24, played=True) == "hit"
    assert P.grade(pick("prop", "at_least", 20), "final", final(1, 0), actual=20, played=True) == "hit"   # "20 or more"
    assert P.grade(pick("prop", "at_least", 20), "final", final(1, 0), actual=19, played=True) == "miss"
    assert P.grade(pick("prop", "below", 20), "final", final(1, 0), actual=19, played=True) == "hit"
    assert P.grade(pick("prop", "below", 20), "final", final(1, 0), actual=20, played=True) == "miss"      # 20 is not under 20


def test_props_over_under_a_market_line_can_push():
    assert P.grade(pick("prop", "over", 24.5), "final", final(1, 0), actual=25, played=True) == "hit"      # must exceed the line
    assert P.grade(pick("prop", "over", 24.5), "final", final(1, 0), actual=24, played=True) == "miss"
    assert P.grade(pick("prop", "under", 24.5), "final", final(1, 0), actual=24, played=True) == "hit"     # must be below it
    assert P.grade(pick("prop", "under", 24.5), "final", final(1, 0), actual=25, played=True) == "miss"
    assert P.grade(pick("prop", "over", 25), "final", final(1, 0), actual=25, played=True) == "push"       # lands on the line
    assert P.grade(pick("prop", "under", 25), "final", final(1, 0), actual=25, played=True) == "push"


# ---------------------------------------------------------------- void, cancelled, pending
def test_void_cancelled_pending_are_never_hits_or_misses():
    assert P.grade(pick("prop", "at_least", 20), "final", final(1, 0), actual=None, played=False) == "void"   # did not play
    assert P.grade(pick("prop", "below", 20), "final", final(1, 0), actual=None, played=False) == "void"      # even on the "under" side
    assert P.grade(pick("prop", "at_least", 20), "final", final(1, 0), actual=None, played=None) == "pending"  # box score not in yet
    assert P.grade(pick("moneyline", "home"), "scheduled", None) == "pending"
    assert P.grade(pick("total", "over", 220.5), "in_progress", None) == "pending"
    for st in ("postponed", "Canceled", "cancelled"):
        assert P.grade(pick("spread", "home", -3.5), st, None) == "cancelled"
        assert P.grade(pick("prop", "at_least", 20), st, None) == "cancelled"
    rec = P.record_of(["hit", "hit", "miss", "push", "void", "cancelled", "pending", "pending"])
    assert (rec["hit"], rec["miss"], rec["push"], rec["void"], rec["cancelled"], rec["pending"]) == (2, 1, 1, 1, 1, 2)
    assert rec["graded"] == 4 and rec["hit_rate"] == round(2 / 3, 4)      # pushes are graded but not in the rate
    assert P.record_of(["pending", "void"])["hit_rate"] is None            # nothing decided: no rate at all


# ---------------------------------------------------------------- selection comes from the pre-game record
def test_selection_uses_the_recorded_projection_and_the_pregame_line():
    mk = {"spread": -7.5, "total": 225.5, "books": 9, "captured_at": "2026-11-13T23:00:00+00:00", "sources": {"the_odds_api"}}
    got = {p["market"]: p for p in P.game_picks("nba", GAME, REC, mk)}
    assert (got["moneyline"]["selection"], got["moneyline"]["team"], got["moneyline"]["model_prob"]) == ("home", "AAA", 0.7)
    assert (got["spread"]["selection"], got["spread"]["team"], got["spread"]["line"], got["spread"]["home_line"]) == ("home", "AAA", -7.5, -7.5)
    assert (got["total"]["selection"], got["total"]["line"]) == ("over", 225.5)
    # the other side of each: the model has the home team by 9, the market by 12.5 -> the pick is the road team plus the points
    got = {p["market"]: p for p in P.game_picks("nba", GAME, REC, {**mk, "spread": -12.5, "total": 231.0})}
    assert (got["spread"]["selection"], got["spread"]["team"], got["spread"]["line"]) == ("away", "BBB", 12.5)
    assert got["total"]["selection"] == "under"
    # no market line: nothing to pick a side of, so only the moneyline exists
    assert [p["market"] for p in P.game_picks("nba", GAME, REC, None)] == ["moneyline"]
    # a coin flip or a projection exactly on the line is not a pick
    flat = {**REC, "home_win_prob": 0.5, "pred_margin": 7.5, "pred_total": 225.5}
    assert P.game_picks("nba", GAME, flat, mk) == []
    assert P.game_picks("nba", GAME, None, mk) == []


def test_prop_selection_is_the_recorded_threshold_nearest_the_recorded_projection():
    rec = {**REC, "player": "A Player", "player_id": 9, "team": "AAA",
           "probabilities": {"points": {"15": 0.797, "20": 0.6, "30": 0.231, "mean": 22.8, "sd": 9.0},
                             "rebounds": {"2": 0.9, "4": 0.38, "mean": 3.3, "sd": 2.0},
                             "assists": {"5": 0.5, "mean": 5.0, "sd": 2.0}}}
    got = {p["stat"]: p for p in P.prop_picks("nba", GAME, rec, {"points": "Points", "rebounds": "Rebounds"})}
    assert (got["points"]["selection"], got["points"]["line"], got["points"]["model_prob"], got["points"]["line_kind"]) == ("at_least", 20.0, 0.6, "model_threshold")
    assert (got["rebounds"]["selection"], got["rebounds"]["line"], got["rebounds"]["model_prob"]) == ("below", 4.0, 0.62)
    assert "assists" not in got  # exactly 50%: no pick
    assert got["points"]["game_id"] == "nba:g1:prop:9:points" and got["points"]["source_seq"] == 7


# ---------------------------------------------------------------- frozen once, with an audit trail
def test_a_pick_is_written_once_and_a_changed_result_is_logged_as_a_correction(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path))
    now = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)
    mk = {"spread": -7.5, "total": 225.5, "books": 9, "captured_at": "x", "sources": {"the_odds_api"}}
    first = P.game_picks("nba", GAME, REC, mk)
    assert P.freeze("nba", first, now, backfilled_before=now.isoformat())["game_picks_added"] == 3
    # Tomorrow's data would pick the other side. The stored pick does not move, and nothing is appended.
    later = P.game_picks("nba", GAME, {**REC, "pred_margin": 2.0, "pred_total": 210.0, "home_win_prob": 0.4}, mk)
    assert {p["selection"] for p in later} == {"away", "under"}
    assert P.freeze("nba", later, now + timedelta(days=1)) == {"game_picks_added": 0, "prop_picks_added": 0, "rejected": 0}
    stored = P.read_picks("nba")
    assert stored["nba:g1:spread"]["selection"] == "home" and stored["nba:g1:total"]["selection"] == "over"
    assert stored["nba:g1:moneyline"]["backfilled"] is True
    assert ledger.verify(P.picks_path("nba")) == 3
    # a record made after the game started can never become a pick
    late = P.game_picks("nba", {**GAME, "game_id": "g2"}, {**REC, "generated_at": "2026-11-14T01:00:00+00:00"}, None)
    assert P.freeze("nba", late, now)["rejected"] == 1 and "nba:g2:moneyline" not in P.read_picks("nba")

    ev = {"home_score": 105, "away_score": 100}
    g = [{"pick_id": "nba:g1:spread", "result": P.grade(stored["nba:g1:spread"], "final", final(105, 100)), "evidence": ev}]
    assert g[0]["result"] == "miss"
    assert P.record_grades("nba", g, now) == {"settled": 1, "corrections": 0}
    assert P.record_grades("nba", g, now + timedelta(hours=1)) == {"settled": 0, "corrections": 0}   # unchanged: nothing written
    # the league corrects the score to 109-100: the same stored pick now grades as a hit, and the log says why
    ev2 = {"home_score": 109, "away_score": 100}
    g2 = [{"pick_id": "nba:g1:spread", "result": P.grade(stored["nba:g1:spread"], "final", final(109, 100)), "evidence": ev2}]
    assert P.record_grades("nba", g2, now + timedelta(days=1)) == {"settled": 0, "corrections": 1}
    lines = [json.loads(x) for f in P.grades_files("nba") for x in f.read_text().splitlines()]
    assert [x["kind"] for x in lines] == ["settled", "correction"]
    assert lines[1]["previous"]["result"] == "miss" and lines[1]["result"] == "hit" and "100-105" in lines[1]["reason"] and "100-109" in lines[1]["reason"]
    assert sum(P.verify_grades("nba").values()) == 2
    # tampering with the log is detected
    f = P.grades_files("nba")[0]
    f.write_text(f.read_text().replace('"result":"miss"', '"result":"hit"', 1))
    with pytest.raises(ledger.LedgerError):
        P.verify_grades("nba")
