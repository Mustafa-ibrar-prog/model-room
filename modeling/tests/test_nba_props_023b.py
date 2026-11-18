"""NBA props 0.2.3b (shadow only): 0.2.3a + the minutes fix, nothing else; can't be published."""
from dataclasses import asdict

import pytest

from modelroom.nba.props.config import SHADOW_FILES, PropParams, PropSettings


def test_0_2_3b_differs_from_0_2_3a_only_by_the_minutes_fix():
    a, b = PropParams.load(SHADOW_FILES["0.2.3a"]), PropParams.load(SHADOW_FILES["0.2.3b"])
    da, db = asdict(a.settings), asdict(b.settings)
    assert sorted(k for k in da if da[k] != db[k]) == ["fill_keep", "role_minutes_k", "start_model"]
    assert len(b.settings.start_model) == 8 and len(b.settings.fill_keep) == 2
    assert a.calibration == b.calibration
    s = PropSettings()
    assert s.start_model == () and s.fill_keep == () and s.role_minutes_k == 0.0   # off by default


def test_0_2_3a_params_hash_unchanged_by_new_settings():
    # settings added later are left out of to_json at their defaults, so 0.2.3a's stored params hash does not move
    d = PropParams.load(SHADOW_FILES["0.2.3a"]).to_json()["settings"]
    assert "start_model" not in d and "fill_keep" not in d and "role_minutes_k" not in d


def test_0_2_3b_is_shadow_only(monkeypatch):
    from modelroom.nba.props import pipeline as P
    monkeypatch.setenv("MODELROOM_NBA_PROPS_VERSION", "0.2.3b")
    with pytest.raises(ValueError):
        P.active_version()
    monkeypatch.setenv("MODELROOM_NBA_PROPS_VERSION", "0.2.0")
    monkeypatch.setenv("MODELROOM_NBA_PROPS_SHADOW", "0.2.3a,0.2.3,0.2.3b")
    assert P.shadow_versions("0.2.0") == ["0.2.3a", "0.2.3", "0.2.3b"]
