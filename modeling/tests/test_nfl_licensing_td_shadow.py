"""NFL props 0.1.4 (licensing-clean) and 0.1.5 (0.1.4 + touchdown scaling): shadow-only versions. 0.1.1 is unchanged,
each new version differs from its base only by its own settings, and neither can be published."""
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from modelroom.nfl.props import model as M
from modelroom.nfl.props.config import CLEAN_FILE, INJURY_FILE, TDS_FILE, PropParams, PropSettings
from modelroom.nfl.props.features import Context


def _diff(a, b):
    da, db = asdict(a.settings), asdict(b.settings)
    return sorted(k for k in da if da[k] != db[k])


def test_defaults_keep_0_1_1_behaviour():
    s = PropSettings()
    assert s.charting_data is True and s.td_scale == () and s.td_scale_points == 0.0
    assert PropParams.load(INJURY_FILE).settings.charting_data is True


def test_0_1_4_differs_from_0_1_1_only_by_charting():
    a, b = PropParams.load(INJURY_FILE), PropParams.load(CLEAN_FILE)
    assert _diff(a, b) == ["blitz_strength", "charting_data", "coverage_strength"]
    assert b.settings.charting_data is False and b.settings.blitz_strength == 0 and b.settings.coverage_strength == 0
    assert a.calibration == b.calibration and a.volume == b.volume


def test_0_1_5_differs_from_0_1_4_only_by_td_scaling():
    a, b = PropParams.load(CLEAN_FILE), PropParams.load(TDS_FILE)
    assert _diff(a, b) == ["td_scale", "td_scale_points"]
    assert [k for k, *_ in b.settings.td_scale] == ["rush", "rec", "pass"]
    assert b.settings.td_scale_points > 0
    changed = sorted(m for m in a.calibration if a.calibration[m] != b.calibration[m])
    assert set(changed) <= {"anytime_td", "passing_tds", "fantasy_points"}
    assert a.volume == b.volume


@pytest.mark.parametrize("v", ["0.1.4", "0.1.5"])
def test_new_versions_are_shadow_only(monkeypatch, v):
    from modelroom.nfl.props import pipeline as P
    monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", v)
    with pytest.raises(ValueError, match="shadow-only"):
        P.active_version()
    monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", "0.1.1")
    monkeypatch.setenv("MODELROOM_NFL_PROPS_SHADOW", f"0.1.0,0.1.3,{v}")
    assert P.shadow_versions("0.1.1") == ["0.1.0", "0.1.3", v]


def test_td_scaling_follows_team_points_and_leaves_context_alone():
    players = pd.DataFrame({"team": ["A", "A", "B"], "rush_td_rate": [0.03, 0.01, 0.02], "rec_td_rate": [0.05, 0.04, 0.06],
                            "pass_td_rate": [0.045, 0.0, 0.0]}, index=["p1", "p2", "p3"])
    ctx = Context(pd.Timestamp("2025-10-01"), 2025, players, pd.DataFrame(), pd.DataFrame(), {}, {})
    s = PropSettings(td_scale=(("rush", 0.0, 0.7), ("rec", -0.01, 0.8), ("pass", 0.0, 0.7)), td_scale_points=22.0)
    # average game (team at 22 points): only the level term a
    c = M._td_scaled(ctx, "A", margin=0.0, total=44.0, s=s)
    assert c.players["rush_td_rate"].tolist() == pytest.approx(players["rush_td_rate"].tolist())
    assert c.players["rec_td_rate"].tolist() == pytest.approx((players["rec_td_rate"] * np.exp(-0.01)).tolist())
    # team projected for 30: rates rise by (30/22)^b
    hi = M._td_scaled(ctx, "A", margin=10.0, total=50.0, s=s)
    assert hi.players.at["p1", "rush_td_rate"] == pytest.approx(0.03 * (30 / 22) ** 0.7)
    lo = M._td_scaled(ctx, "A", margin=-10.0, total=30.0, s=s)
    assert lo.players.at["p1", "pass_td_rate"] < players.at["p1", "pass_td_rate"]
    assert ctx.players.equals(players)  # the shared context is never changed
