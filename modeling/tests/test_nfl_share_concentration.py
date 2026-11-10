"""NFL props 0.1.3 (shadow-only experiment): within-position concentration keeps group totals, leaves other groups
untouched, and 0.1.3 differs from 0.1.1 only by that setting and can never be the published version."""
import os
import pandas as pd
import pytest
from dataclasses import asdict
from modelroom.nfl.props import model as M
from modelroom.nfl.props.config import CONC_FILE, INJURY_FILE, PropParams, PropSettings


def test_concentrate_keeps_group_total_and_moves_to_lead():
    sh = pd.Series({"rb1": 0.45, "rb2": 0.25, "rb3": 0.08, "wr1": 0.04, "qb": 0.12})
    gr = pd.Series({"rb1": "RB", "rb2": "RB", "rb3": "RB", "wr1": "WR", "qb": "QB"})
    out = M.concentrate(sh, gr, "RB", 1.25)
    rb = ["rb1", "rb2", "rb3"]
    assert out[rb].sum() == pytest.approx(sh[rb].sum(), abs=1e-12)
    assert out["rb1"] > sh["rb1"] and out["rb3"] < sh["rb3"]
    assert out["wr1"] == sh["wr1"] and out["qb"] == sh["qb"]
    assert M.concentrate(sh, gr, "RB", 1.0).equals(sh.astype(float))


def test_concentrate_single_or_zero_players_unchanged():
    sh = pd.Series({"te1": 0.2, "te2": 0.0})
    gr = pd.Series({"te1": "TE", "te2": "TE"})
    assert M.concentrate(sh, gr, "TE", 1.15).equals(sh.astype(float))


def test_0_1_3_differs_from_0_1_1_only_by_concentration():
    a, b = PropParams.load(INJURY_FILE), PropParams.load(CONC_FILE)
    da, db = asdict(a.settings), asdict(b.settings)
    assert [k for k in da if da[k] != db[k]] == ["share_concentration"]
    assert b.settings.share_concentration == (("c", "RB", 1.25), ("t", "TE", 1.15))
    assert a.calibration == b.calibration and a.volume == b.volume
    assert PropSettings().share_concentration == ()  # off by default


def test_0_1_3_is_shadow_only(monkeypatch):
    from modelroom.nfl.props import pipeline as P
    monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", "0.1.3")
    with pytest.raises(ValueError, match="shadow-only"):
        P.active_version()
    monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", "0.1.1")
    monkeypatch.setenv("MODELROOM_NFL_PROPS_SHADOW", "0.1.0,0.1.3")
    assert P.active_version() == "0.1.1" and P.shadow_versions("0.1.1") == ["0.1.0", "0.1.3"]
