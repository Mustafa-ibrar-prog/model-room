"""Pick of the Day: selection rule, no forced picks, once-a-day immutable records, grading, published file."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from modelroom import potd
from modelroom.common import ledger
from modelroom.common.paths import ledger_path

SIG = (13.0, 13.0)
REC = {"game_start": "2026-11-22T21:25:00+00:00", "model_version": "1.0.1", "generated_at": "2026-11-22T15:00:00+00:00",
       "seq": 5, "hash": "ab" * 32, "pred_margin": 7.0, "pred_total": 38.0, "home_win_prob": 0.70}
GAME = {"game_id": "G1", "home": "PHI", "away": "PIT"}


def test_candidates_use_the_stored_line_and_never_invent_a_market_price():
    c = {x["market"]: x for x in potd.candidates("nfl", GAME, REC, {"spread": -3.0, "total": 46.5, "sources": ["odds_api"], "books": 4}, SIG)}
    assert set(c) == {"spread", "total"}                      # no moneyline without consensus prices
    assert c["spread"]["selection"] == "home" and c["spread"]["line"] == -3.0 and c["spread"]["difference"] == 4.0
    assert c["total"]["selection"] == "under" and c["total"]["projection"] == 38.0 and c["total"]["difference"] == -8.5
    assert all(x["market_prob"] is None and x["price"] is None and x["reference_prob"] == 0.5 for x in c.values())


def test_moneyline_uses_devigged_consensus():
    c = potd.candidates("nfl", GAME, REC, {"home_ml": -150, "away_ml": 130, "books": 3}, SIG)
    assert len(c) == 1 and c[0]["market"] == "moneyline" and c[0]["selection"] == "home"
    assert 0.55 < c[0]["market_prob"] < 0.60 and c[0]["edge"] == round(0.70 - c[0]["market_prob"], 4)


def test_no_record_or_no_line_gives_no_candidates():
    assert potd.candidates("nfl", GAME, None, {"spread": -3.0}, SIG) == []
    assert potd.candidates("nfl", GAME, REC, None, SIG) == []


def test_thresholds_and_no_forced_pick():
    weak = {**REC, "pred_margin": 3.5, "pred_total": 46.0}
    c = potd.candidates("nfl", GAME, weak, {"spread": -3.0, "total": 46.5}, SIG)
    assert c and not any(x["qualifies"] for x in c) and potd.choose(c) is None


def _games(status="scheduled", hs=None, as_=None):
    return pd.DataFrame([{"game_id": "G1", "home": "PHI", "away": "PIT", "start_time": pd.Timestamp("2026-11-22 21:25", tz="UTC"),
                          "status": status, "home_score": hs, "away_score": as_, "game_date": "2026-11-22", "season": 2026}])


def test_select_day_waits_for_lines_and_records_no_pick():
    now = datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc)
    assert potd.select_day("nfl", now, _games(), {"G1": REC}, {}, SIG) is None          # no line yet: decide later
    weak = {**REC, "pred_margin": 3.5, "pred_total": 46.0}
    r = potd.select_day("nfl", now, _games(), {"G1": weak}, {"G1": {"spread": -3.0, "total": 46.5}}, SIG)
    assert r["status"] == "no_pick" and r["date"] == "2026-11-22" and r["pick_key"] == "potd:nfl:2026-11-22"
    r = potd.select_day("nfl", now, _games(), {"G1": REC}, {"G1": {"spread": -3.0, "total": 46.5}}, SIG)
    assert r["status"] == "pick" and r["market"] == "total" and r["model_version"] == "1.0.1" and r["explanation"]


@pytest.mark.parametrize("market,sel,line,hs,as_,want", [
    ("spread", "home", -3.0, 24, 20, "hit"), ("spread", "home", -3.0, 23, 20, "push"), ("spread", "away", 3.0, 24, 20, "miss"),
    ("spread", "away", 3.0, 22, 20, "hit"), ("total", "under", 46.5, 24, 20, "hit"), ("total", "over", 44.0, 24, 20, "push"),
    ("moneyline", "home", None, 24, 20, "hit"), ("moneyline", "away", None, 24, 20, "miss")])
def test_grading(market, sel, line, hs, as_, want):
    p = {"status": "pick", "market": market, "selection": sel, "line": line}
    assert potd.grade(p, {"status": "final", "home_score": hs, "away_score": as_}) == want


def test_grading_pending_and_void():
    p = {"status": "pick", "market": "total", "selection": "over", "line": 40}
    assert potd.grade(p, {"status": "scheduled", "home_score": None}) == "pending"
    assert potd.grade(p, {"status": "postponed", "home_score": None}) == "void"
    assert potd.grade(p, None) == "pending"


def test_run_freezes_once_per_day_and_grades_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path)); monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path / "data"))
    from modelroom import history as H
    state = {"games": _games(), "market": {"G1": {"spread": -3.0, "total": 46.5}}, "rec": REC}
    monkeypatch.setattr(H, "_games_table", lambda lg: state["games"])
    monkeypatch.setattr(H, "_pregame", lambda recs: {"G1": state["rec"]})
    monkeypatch.setattr(H, "_market", lambda lg: state["market"])
    monkeypatch.setattr(H, "_sigmas", lambda lg: SIG)
    potd.run(("nfl",), now=datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc))
    first = potd.read()
    assert len(first) == 1 and first[0]["market"] == "total" and first[0]["line"] == 46.5
    # the line moves and the model changes later the same day: the published pick is NOT re-selected or edited
    state["market"] = {"G1": {"spread": -6.5, "total": 41.0}}; state["rec"] = {**REC, "pred_total": 52.0}
    potd.run(("nfl",), now=datetime(2026, 11, 22, 20, 0, tzinfo=timezone.utc))
    assert potd.read() == first
    # final score arrives: a grade record is added, the pick record stays byte-identical
    state["games"] = _games("final", 24, 20)
    out = potd.run(("nfl",), now=datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc))
    assert out["graded"] == 1 and potd.read() == first and potd.read_grades()["potd:nfl:2026-11-22"]["result"] == "hit"
    potd.run(("nfl",), now=datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc))
    assert len(ledger.read_series(ledger_path("potd_grades"))) == 1        # no duplicate grade
    for f in ledger.series_files(ledger_path("potd")) + ledger.series_files(ledger_path("potd_grades")):
        ledger.verify(f)
    import json
    pub = json.loads((tmp_path / "data" / "published" / "pick_of_the_day.json").read_text())
    assert pub["history"][0]["result"] == "hit" and pub["record"]["nfl"]["hit"] == 1 and pub["record"]["nfl"]["validated"] is False
    assert "Unvalidated" in pub["notice"] and "guarantee" not in json.dumps(pub["history"]).lower()
