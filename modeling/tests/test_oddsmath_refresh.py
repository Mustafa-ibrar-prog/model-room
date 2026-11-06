import json
from datetime import datetime, timezone

import pytest

from modelroom import refresh_plan as R
from modelroom.common import oddsmath as O
from modelroom.history import market_picks


def test_prices_and_fair_odds():
    assert O.implied(-110) == pytest.approx(110 / 210)
    assert O.implied(150) == pytest.approx(0.4)
    assert O.devig(-110, -110) == pytest.approx((0.5, 0.5))
    assert O.fair_american(0.6) == -150 and O.fair_american(0.4) == 150
    assert O.ev(0.55, 0.0, -110) == pytest.approx(0.55 * 100 / 110 - 0.45)
    assert O.ev(0.5, 0.1, 100) == pytest.approx(0.5 - 0.4)  # push returns the stake


def test_whole_number_lines_push():
    p = O.over_probs(45, 13, 45)
    assert p["push"] > 0 and sum(p.values()) == pytest.approx(1)
    assert O.over_probs(45, 13, 45.5)["push"] == 0
    c = O.cover_probs(3.0, 13, -3.0)  # model margin exactly the line
    assert c["home"] == pytest.approx(c["away"]) and c["push"] > 0


def test_ladder_probs_need_the_thresholds():
    g = {"2": 0.7, "3": 0.5, "4": 0.3}
    assert O.ladder_probs(g, 2.5) == {"over": 0.5, "push": 0.0, "under": 0.5}
    assert O.ladder_probs(g, 3) == pytest.approx({"over": 0.3, "push": 0.2, "under": 0.5})
    assert O.ladder_probs(g, 7.5) is None  # never extrapolated


def test_market_picks_grade_against_the_line():
    pre = {"pred_margin": 6.0, "pred_total": 40.0}
    m = {"spread": -3.0, "total": 46.5, "sources": ["nflverse"], "captured_at": None}
    out = market_picks(pre, m, {"home": 20, "away": 17}, (13.0, 13.0))
    assert out["spread"]["pick"] == "home" and out["spread"]["result"] == "push"
    assert out["total"]["pick"] == "under" and out["total"]["result"] == "win"
    assert out["implied_scores"] == {"home": 24.8, "away": 21.8}
    assert market_picks(pre, m, None, (13.0, 13.0))["spread"]["result"] is None  # not final: ungraded


def test_refresh_slots_and_no_duplicates(tmp_path, monkeypatch):
    pub = tmp_path / "published"
    pub.mkdir()
    (pub / "nfl.json").write_text(json.dumps({"upcoming": [{"start_time": "2026-11-08T18:00:00+00:00", "status": "scheduled"}]}))
    monkeypatch.setattr(R, "PUBLISHED", pub)
    monkeypatch.setattr(R, "LOG", tmp_path / "log.jsonl")
    t = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731
    assert [s["kind"] for s in R.due(t("2026-11-08T16:35:00"))] == ["morning", "inactives"]  # 1:00 PM ET kickoff − 85 min
    assert [s["kind"] for s in R.due(t("2026-11-08T17:35:00"))] == ["morning", "pregame"]
    assert [s["kind"] for s in R.due(t("2026-11-08T15:10:00"))] == ["morning"]     # 7:10 AM PT
    R.record(["morning:2026-11-08"], "failed")
    assert R.due(t("2026-11-08T15:20:00"))                                          # failed → retried
    R.record(["morning:2026-11-08"], "success")
    assert not R.due(t("2026-11-08T15:30:00"))                                      # done → never twice
    assert not R.due(t("2026-11-08T18:30:00"))                                      # game started: window closed
    assert [s["kind"] for s in R.due(t("2026-11-09T00:05:00"))] == ["afternoon"]   # 4:05 PM PT, its own slot


def test_failed_runs_are_retried_reported_and_missed(tmp_path, monkeypatch):
    pub = tmp_path / "published"
    pub.mkdir()
    monkeypatch.setattr(R, "PUBLISHED", pub)
    monkeypatch.setattr(R, "LOG", tmp_path / "log.jsonl")
    t = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731
    R.record(["midday:2026-11-08"], "failed", "schedule run 1", t("2026-11-08T20:05:00"))
    assert [s["id"] for s in R.due(t("2026-11-08T20:15:00"))] == ["midday:2026-11-08"]   # retried while the window is open
    assert R.pending(["midday:2026-11-08", "morning:2026-11-08"]) == ["midday:2026-11-08", "morning:2026-11-08"]
    R.record(["midday:2026-11-08"], "success", "schedule run 2", t("2026-11-08T20:20:00"))
    assert R.pending(["midday:2026-11-08"]) == []                # a queued duplicate run sees it's done
    st = R.status(t("2026-11-09T01:00:00"))                      # 5 PM PT: morning window long closed, never ran
    assert "morning:2026-11-08" in st["missed"] and "midday:2026-11-08" not in st["missed"]
    assert st["recent_failures"][-1]["note"] == "schedule run 1" and st["last_success_by_kind"]["midday"]["note"] == "schedule run 2"


def test_pregame_slots_that_never_started_are_missed(tmp_path, monkeypatch):
    pub = tmp_path / "published"
    pub.mkdir()
    (pub / "nba.json").write_text(json.dumps({"upcoming": [], "recent": [{"start_time": "2026-11-05T00:00:00+00:00"}, {"start_time": "2026-11-05T02:00:00+00:00"}]}))
    (pub / "nfl.json").write_text(json.dumps({"upcoming": [], "recent": [{"start_time": "2026-11-06T01:15:00+00:00"}]}))
    monkeypatch.setattr(R, "PUBLISHED", pub)
    monkeypatch.setattr(R, "LOG", tmp_path / "log.jsonl")
    t = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731
    R.record(["pregame:nba:2026-11-05T02:00:00+00:00"], "success", None, t("2026-11-05T01:44:00"))
    m = R.status(t("2026-11-06T03:00:00"))["missed"]
    assert "pregame:nba:2026-11-05T00:00:00+00:00" in m                 # never attempted: still missed
    assert "pregame:nba:2026-11-05T02:00:00+00:00" not in m             # ran
    assert {"inactives:nfl:2026-11-06T01:15:00+00:00", "pregame:nfl:2026-11-06T01:15:00+00:00"} <= set(m)
