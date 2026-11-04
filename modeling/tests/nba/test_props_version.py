"""NBA prop model versioning (test site runs 0.2.0; 0.1.0 stays the default and the rollback) and the live monitor."""
import json

import pandas as pd
import pytest

from modelroom.nba.props import monitor, pipeline
from modelroom.nba.props.config import CANDIDATE_FILE, MODEL_VERSION, PARAMS_FILE


def test_default_is_the_old_model(monkeypatch):
    monkeypatch.delenv("MODELROOM_NBA_PROPS_VERSION", raising=False)
    assert pipeline.active_version() == MODEL_VERSION == "0.1.0"
    assert pipeline.VERSIONS["0.1.0"] == PARAMS_FILE


def test_candidate_selected_by_env_and_unknown_refused(monkeypatch):
    monkeypatch.setenv("MODELROOM_NBA_PROPS_VERSION", "0.2.0")
    assert pipeline.active_version() == "0.2.0"
    assert json.loads(CANDIDATE_FILE.read_text())["model_version"] == "0.2.0"
    monkeypatch.setenv("MODELROOM_NBA_PROPS_VERSION", "9.9")
    with pytest.raises(ValueError):
        pipeline.active_version()


def test_both_parameter_files_present():
    old = json.loads(PARAMS_FILE.read_text())
    new = json.loads(CANDIDATE_FILE.read_text())
    assert old["model_version"] == "0.1.0" and new["model_version"] == "0.2.0"
    assert new["settings"]["rate_prior_kind"] == "role" and old["settings"].get("rate_prior_kind", "position") == "position"


def _rec(version, gen, pts_mean, p20, starter, freed=0.0):
    return {"kind": "player_props", "game_id": "g1|p1", "nba_game_id": "g1", "player_id": "p1", "player": "A", "team": "X",
            "model_version": version, "generated_at": gen, "game_start": "2030-01-02T00:00:00+00:00", "projected_minutes": 30.0,
            "starter_rate": starter, "usage_freed_by_absences": freed,
            "probabilities": {"points": {"20": p20, "mean": pts_mean, "sd": 5.0}, "pra": {"30": 0.5, "mean": 30.0, "sd": 7.0}}}


def test_monitor_uses_last_pregame_prediction_per_version():
    recs = [_rec("0.1.0", "2030-01-01T10:00:00+00:00", 20.0, 0.6, 1.0),
            _rec("0.1.0", "2030-01-01T20:00:00+00:00", 22.0, 0.7, 1.0),   # latest pre-game 0.1.0
            _rec("0.2.0", "2030-01-01T20:00:00+00:00", 19.0, 0.4, 1.0, 0.1),
            _rec("0.2.0", "2030-01-02T01:00:00+00:00", 30.0, 0.9, 1.0)]  # after tip-off: ignored
    pred = monitor._pregame(recs)
    box = pd.DataFrame([{"game_id": "g1", "player_id": "p1", "played": True, "minutes": 32.0, "pts": 21.0, "reb": 5, "ast": 4,
                         "pra": 30.0, "fg3m": 2, "stl": 1, "blk": 0, "starter": True}])
    rep = monitor.build(pred, box)
    v1, v2 = rep["versions"]["0.1.0"], rep["versions"]["0.2.0"]
    assert v1["markets"]["points"]["all"]["mean_proj"] == 22.0
    assert v2["markets"]["points"]["all"]["mean_proj"] == 19.0
    assert v1["minutes"]["all"]["bias"] == -2.0
    assert v1["markets"]["points"]["calibration"]["over_leans"] == {"n": 1, "priced": 0.7, "hit": 1.0}
    assert v2["markets"]["points"]["calibration"]["under_leans"] == {"n": 1, "priced": 0.6, "hit": 0.0}
    assert "teammate_out" in v2["markets"]["points"]["by_injury"]
