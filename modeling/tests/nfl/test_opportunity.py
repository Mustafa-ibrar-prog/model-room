"""NFL opportunity redistribution (0.3.0) and prop-model versioning."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from modelroom.nfl.props import model as M
from modelroom.nfl.props import monitor, pipeline
from modelroom.nfl.props.config import MODEL_VERSION, OPP_FILE, OPP_VERSION, PARAMS_FILE

S = SimpleNamespace(redist_decay=0.5, redist_up=1.0, redist_up_decay=1.0, redist_in_group=1.0, redist_concentration=1.0)


def _team():
    idx = ["rb1", "rb2", "rb3", "wr1", "wr2"]
    raw = pd.Series([0.30, 0.10, 0.05, 0.40, 0.15], index=idx)
    grp = pd.Series(["RB", "RB", "RB", "WR", "WR"], index=idx)
    rank = pd.Series([1, 2, 3, 1, 2], index=idx, dtype=float)
    return raw, grp, rank


def test_nobody_missing_only_scales_to_the_team_total():
    raw, grp, rank = _team()
    out = M.redistribute(raw, grp, pd.Series(1.0, index=raw.index), rank, 0.95, S)
    assert out.sum() == pytest.approx(0.95)
    assert (out / raw).round(6).nunique() == 1  # no player singled out


def test_missing_starter_goes_to_next_man_down_first():
    raw, grp, rank = _team()
    pp = pd.Series([0.0, 1.0, 1.0, 1.0, 1.0], index=raw.index)
    base = M.redistribute(raw, grp, pd.Series(1.0, index=raw.index), rank, 1.0, S)
    out = M.redistribute(raw, grp, pp, rank, 1.0, S)
    assert out["rb1"] == 0.0
    gain = out - base
    assert gain["rb2"] > gain["rb3"] > 0          # RB2 first, then RB3
    assert gain[["wr1", "wr2"]].abs().max() < 1e-12  # stays in the position group (in_group = 1)
    # Expected total is conserved: nothing created, nothing lost.
    assert (out * pp).sum() == pytest.approx(1.0)


def test_missing_backup_goes_mostly_up_to_the_starters():
    raw, grp, rank = _team()
    pp = pd.Series([1.0, 1.0, 0.0, 1.0, 1.0], index=raw.index)
    base = M.redistribute(raw, grp, pd.Series(1.0, index=raw.index), rank, 1.0, S)
    gain = M.redistribute(raw, grp, pp, rank, 1.0, S) - base
    assert gain["rb1"] > gain["rb2"] > 0


def test_versions(monkeypatch):
    monkeypatch.delenv("MODELROOM_NFL_PROPS_VERSION", raising=False)
    assert pipeline.active_version() == MODEL_VERSION == "0.1.0"
    assert pipeline.VERSIONS["0.1.0"] == PARAMS_FILE
    monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", OPP_VERSION)
    assert pipeline.active_version() == "0.3.0"
    assert json.loads(OPP_FILE.read_text())["settings"]["opp_redistribution"] == "depth"
    assert json.loads(PARAMS_FILE.read_text())["settings"].get("opp_redistribution", "proportional") == "proportional"
    monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", "9.9")
    with pytest.raises(ValueError):
        pipeline.active_version()


def test_monitor_ranks_every_version_the_same_way():
    def rec(v, gen, tg):
        return {"kind": "player_props", "game_id": "g|p1", "nfl_game_id": "g", "player_id": "p1", "team": "X", "model_version": v,
                "generated_at": gen, "game_start": "2030-01-02T18:00:00+00:00", "injury_status": None,
                "opportunity": {"targets": tg, "carries": 0.0} if tg is not None else None,
                "probabilities": {"receptions": {"4": 0.6, "mean": 4.5, "sd": 2.0}}}
    pred = monitor._pregame([rec("0.1.0", "2030-01-01T00:00:00+00:00", None), rec("0.3.0", "2030-01-01T00:00:00+00:00", 7.0)])
    box = pd.DataFrame([{"game_id": "g", "player_id": "p1", "team": "X", "group": "WR", "season": 2030, "week": 1, "targets": 8.0, "carries": 0.0,
                         "receptions": 5.0}])
    rep = monitor.build(pred, box, ranks=lambda s, w, c: {"p1": 1})
    assert rep["versions"]["0.3.0"]["by_depth"]["WR1"]["targets"]["bias"] == -1.0
    assert rep["versions"]["0.1.0"]["by_depth"]["WR1"]["targets"] == {"n": 0}
    assert rep["versions"]["0.1.0"]["by_depth"]["WR1"]["receptions"]["proj"] == 4.5
    assert rep["versions"]["0.1.0"]["markets"]["receptions"]["calibration"]["over_leans"]["hit"] == 1.0


def _ctx():
    P = pd.DataFrame({"group": ["WR", "WR", "TE"]}, index=["a", "b", "c"])
    return SimpleNamespace(players=P, cutoff=pd.Timestamp("2025-10-01"))


def test_gameday_drops_players_on_the_inactive_list():
    roster = pd.DataFrame({"team": ["X"] * 3, "gsis_id": ["a", "b", "c"], "status": ["ACT", "INA", "ACT"]})
    assert set(M.candidates(_ctx(), "X", roster, None).index) == {"a", "b", "c"}          # 0.1.0 behaviour
    assert set(M.candidates(_ctx(), "X", roster, None, gameday=True).index) == {"a", "c"}  # after inactives


def test_questionable_split_keeps_the_team_total_and_stays_in_group():
    c = pd.DataFrame({"group": ["WR", "WR", "TE"], "injury_status": ["Questionable", None, None],
                      "out": [False, False, False], "p_play": [0.9, 0.9, 0.9]}, index=["a", "b", "c"])
    t = pd.Series([0.3, 0.2, 0.1], index=c.index)
    s = SimpleNamespace(play_model="depth", gameday_inactives=True, redist_decay=0.5, questionable_factor=0.8)
    s = __import__("dataclasses").make_dataclass("S", list(vars(s)))(**vars(s))
    t2, c2, info = M._questionable_split(c, c, c, t, pd.Series(dtype=float), s, {"a": 1, "b": 2, "c": 1})
    assert t2.sum() == pytest.approx(t.sum())
    assert t2["c"] == pytest.approx(0.1)            # other group untouched
    assert t2["a"] < 0.3 and t2["b"] > 0.2          # role-if-active trimmed, rest to the next WR
    assert info["a"]["play_chance"] == 1.0           # active after the inactive list → known to play
