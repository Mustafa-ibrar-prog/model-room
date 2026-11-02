import json

import numpy as np
import pytest

from modelroom.common import ledger
from modelroom.common.linalg import ridge_to_prior
from modelroom.common.metrics import against_line, calibration_table, error_summary, normal_cdf
from modelroom.common.publish import write_board


def _pred(game_id, gen="2030-01-01T00:00:00+00:00", start="2030-01-02T00:00:00+00:00", h="abc"):
    return {"game_id": game_id, "model_version": "1.0.0", "inputs_hash": h, "generated_at": gen,
            "game_start": start, "projection": {"margin": 3.5}}


def test_ledger_appends_and_verifies(tmp_path):
    p = tmp_path / "l.jsonl"
    r = ledger.append(p, [_pred("g1"), _pred("g2")])
    assert (r.appended, r.skipped_duplicate, r.rejected_started) == (2, 0, 0)
    assert ledger.verify(p) == 2


def test_ledger_rejects_predictions_after_start(tmp_path):
    p = tmp_path / "l.jsonl"
    r = ledger.append(p, [_pred("g1", gen="2030-01-02T00:00:00+00:00")])
    assert r.rejected_started == 1 and not p.exists()


def test_ledger_is_idempotent(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, [_pred("g1")])
    r = ledger.append(p, [_pred("g1")])
    assert r.skipped_duplicate == 1 and ledger.verify(p) == 1


def test_ledger_detects_edits(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, [_pred("g1"), _pred("g2")])
    lines = p.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["projection"]["margin"] = 9.0  # rewrite history
    lines[0] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(ledger.LedgerError):
        ledger.verify(p)


def test_ledger_detects_deleted_line(tmp_path):
    p = tmp_path / "l.jsonl"
    ledger.append(p, [_pred("g1"), _pred("g2"), _pred("g3")])
    lines = p.read_text().splitlines()
    p.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(ledger.LedgerError):
        ledger.verify(p)


def test_ridge_with_no_data_returns_prior():
    prior = np.array([1.0, -2.0])
    out = ridge_to_prior(np.zeros((0, 2)), np.zeros(0), np.zeros(0), prior, np.ones(2))
    assert np.allclose(out, prior)


def test_ridge_recovers_coefficients_with_tiny_penalty():
    rng = np.random.default_rng(0)  # test data only
    X = rng.normal(size=(200, 3))
    beta = np.array([2.0, -1.0, 0.5])
    y = X @ beta
    out = ridge_to_prior(X, y, np.ones(200), np.zeros(3), np.full(3, 1e-9))
    assert np.allclose(out, beta, atol=1e-6)


def test_ridge_shrinks_toward_prior():
    X = np.ones((1, 1))
    out = ridge_to_prior(X, np.array([10.0]), np.ones(1), np.array([0.0]), np.array([1.0]))
    assert out[0] == pytest.approx(5.0)  # one observation vs one game of prior


def test_metrics():
    assert normal_cdf(0.0) == pytest.approx(0.5)
    assert error_summary(np.array([1, 3]), np.array([2, 2]))["mae"] == 1.0
    rows = calibration_table(np.array([0.05, 0.95]), np.array([0, 1]))
    assert rows[0]["actual"] == 0.0 and rows[-1]["actual"] == 1.0


def test_against_line_excludes_pushes_and_missing():
    r = against_line(np.array([5.0, 2.0, np.nan]), np.array([3.0, 2.0, 1.0]), np.array([4.0, 2.0, 0.0]))
    assert r["n"] == 1 and r["wins"] == 1


def test_publish_turns_nan_into_null(tmp_path):
    p = write_board(tmp_path / "b.json", {"games": [{"market_spread": float("nan")}]})
    assert json.loads(p.read_text())["games"][0]["market_spread"] is None
