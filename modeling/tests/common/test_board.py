from datetime import datetime, timezone

import pandas as pd
import pytest

from modelroom.common import board, ledger


def test_implied_probabilities_remove_vig():
    h, a = board.implied_probabilities(-110, -110)
    assert h == pytest.approx(0.5) and a == pytest.approx(0.5)
    h, a = board.implied_probabilities(320, -410)
    assert h + a == pytest.approx(1.0) and h < 0.25
    assert board.implied_probabilities(None, -110) == (None, None)


def test_model_vs_market_signs_and_missing():
    proj = {"spread": -3.0, "total": 220.0, "home_win_prob": 0.6}
    e = board.model_vs_market(proj, {"spread": -1.0, "total": 224.0, "home_ml": None, "away_ml": None})
    assert e["spread"] == 2.0      # market -1, model -3: value on the home side
    assert e["total"] == -4.0      # model under the market
    assert e["home_prob_market"] is None
    assert board.model_vs_market(proj, None) is None


def test_freshness_flags_missing_results_and_stale_ingest():
    now = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)
    g = pd.DataFrame({
        "game_id": [1, 2, 3],
        "start_time": pd.to_datetime(["2030-01-09T00:00Z", "2030-01-10T01:00Z", "2030-01-11T00:00Z"]),
        "status": ["final", "scheduled", "scheduled"],
        "game_date": ["2030-01-08", "2030-01-09", "2030-01-10"],
    })
    f = board.freshness(g, last_ingest="2030-01-10T10:00:00+00:00", now=now, grace_hours=4, stale_hours=36)
    assert f["status"] == "delayed" and f["missing_results"] == ["2"]
    g.loc[1, "status"] = "final"
    assert board.freshness(g, last_ingest="2030-01-10T10:00:00+00:00", now=now, grace_hours=4, stale_hours=36)["status"] == "current"
    assert board.freshness(g, last_ingest="2030-01-01T10:00:00+00:00", now=now, grace_hours=4, stale_hours=36)["status"] == "delayed"
    assert board.freshness(g, last_ingest=None, now=now, grace_hours=4, stale_hours=36)["status"] == "delayed"


def test_grade_ledger_joins_results_without_touching_ledger(tmp_path):
    path = tmp_path / "l.jsonl"
    ledger.append(path, [{
        "game_id": "g1", "model_version": "1.0.0", "inputs_hash": "x", "params_hash": "p",
        "generated_at": "2030-01-01T00:00:00+00:00", "game_start": "2030-01-02T00:00:00+00:00",
        "pred_margin": 3.0, "pred_total": 200.0, "home_win_prob": 0.6,
    }])
    before = path.read_text()
    out = board.grade_ledger(path, pd.DataFrame({"game_id": ["g1"], "home_score": [105], "away_score": [100]}))
    assert out["graded"] == 1 and out["by_version"]["1.0.0"]["margin_mae"] == 2.0
    assert path.read_text() == before


def test_ledger_new_params_are_not_deduplicated(tmp_path):
    path = tmp_path / "l.jsonl"
    rec = {"game_id": "g1", "model_version": "1.0.0", "inputs_hash": "x", "params_hash": "p1",
           "generated_at": "2030-01-01T00:00:00+00:00", "game_start": "2030-01-02T00:00:00+00:00"}
    ledger.append(path, [rec])
    r = ledger.append(path, [{**rec, "params_hash": "p2"}])
    assert r.appended == 1


def test_interval_is_symmetric_80_percent():
    lo, hi = board.interval(0.0, 10.0)
    assert lo == -12.8 and hi == 12.8
    assert board.interval(5.0, None) is None
