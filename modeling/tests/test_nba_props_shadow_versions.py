"""The 0.2.3 candidates may run as shadows on the test site but can never become the published version."""
import pytest

from modelroom.nba.props import pipeline as P
from modelroom.nba.props import shadow as S


def test_shadow_candidates_accepted(monkeypatch):
    monkeypatch.setenv("MODELROOM_NBA_PROPS_SHADOW", "0.2.3a,0.2.3")
    assert P.shadow_versions("0.2.0") == ["0.2.3a", "0.2.3"]


def test_shadow_only_versions_cannot_publish(monkeypatch):
    for v in ("0.2.3a", "0.2.3"):
        monkeypatch.setenv("MODELROOM_NBA_PROPS_VERSION", v)
        with pytest.raises(ValueError):
            P.active_version()


def test_unknown_shadow_rejected(monkeypatch):
    monkeypatch.setenv("MODELROOM_NBA_PROPS_SHADOW", "9.9.9")
    with pytest.raises(ValueError):
        P.shadow_versions("0.2.0")


def test_ladder_interpolation():
    lad = {"10": 0.8, "15": 0.5, "20": 0.2, "mean": 15.0, "sd": 5.0}
    assert S._p_at(lad, 15) == pytest.approx(0.5)
    assert 0.5 < S._p_at(lad, 12) < 0.8
    assert S._p_at(lad, 25) is None
