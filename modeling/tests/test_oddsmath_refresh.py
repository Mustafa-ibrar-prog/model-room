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
