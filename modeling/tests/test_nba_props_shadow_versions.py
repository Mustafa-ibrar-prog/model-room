"""The 0.2.3 candidates may run as shadows on the test site but can never become the published version."""
import pytest

from modelroom.nba.props import pipeline as P
from modelroom.nba.props import shadow as S


def test_shadow_candidates_accepted(monkeypatch):
    monkeypatch.setenv("MODELROOM_NBA_PROPS_SHADOW", "0.2.3a,0.2.3")
    assert P.shadow_versions("0.2.0") == ["0.2.3a", "0.2.3"]


def test_shadow_only_versions_cannot_publish(monkeypatch):
    for v in ("0.2.3a", "0.2.3", "0.2.3b", "0.2.3c"):
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


def test_disagreement_groups_and_no_grading_of_unprojected():
    import pandas as pd

    lad = {"points": {"10": 0.6, "15": 0.4, "mean": 12.0, "sd": 5.0}}
    def r(v, pid, team="AAA", tm=None):
        return {"key": f"g1|{pid}", "game_id": "g1", "player_id": pid, "player": f"P{pid}", "team": team, "version": v,
                "generated_at": "2026-11-08T01:00:00+00:00", "game_start": "2026-11-08T03:00:00+00:00", "proj_min": 20.0,
                "probabilities": lad, "status": None, "source": None, "conflict": None, "n_out": 0, "espn_only_out": False,
                "teammates_out": tm or []}
    out_list = [{"name": "P2", "status": "out", "source": "nba_official"}]
    pred = pd.DataFrame([r("0.2.0", "1"), r("0.2.3a", "1", tm=out_list), r("0.2.3", "1", tm=out_list),   # agreed
                         r("0.2.0", "2"),                                                                  # shadows ruled him out
                         r("0.2.3a", "3"), r("0.2.3", "3")])                                               # shadows only
    box = pd.DataFrame([{"game_id": "g1", "player_id": p, "played": pl} for p, pl in (("1", True), ("2", True), ("3", False))])
    d = S.disagreement(pred, box, ("0.2.0", "0.2.3a", "0.2.3"))
    assert d["groups"]["only 0.2.0"]["played"] == 1
    assert list(d["groups"]["only 0.2.0"]["reasons"]) == ["out (nba_official)"]
    assert d["groups"]["only 0.2.3a + 0.2.3"]["did_not_play"] == 1
    assert d["availability_by_version"]["0.2.3a"] == {"projected_and_played": 1, "projected_but_did_not_play": 1, "excluded_but_played": 1, "excluded_and_sat": 0}
    assert d["availability_by_version"]["0.2.0"] == {"projected_and_played": 2, "projected_but_did_not_play": 0, "excluded_but_played": 0, "excluded_and_sat": 1}


def test_023c_is_023b_plus_the_measured_blowout_cut_only(monkeypatch):
    from dataclasses import asdict
    from modelroom.nba.props.config import PropParams, SHADOW_FILES
    b, c = PropParams.load(SHADOW_FILES["0.2.3b"]), PropParams.load(SHADOW_FILES["0.2.3c"])
    db, dc = asdict(b.settings), asdict(c.settings)
    assert {k for k in db if db[k] != dc[k]} == {"blowout_strength"} and dc["blowout_strength"] == 0.007
    monkeypatch.setenv("MODELROOM_NBA_PROPS_SHADOW", "0.2.3b,0.2.3c")
    assert P.shadow_versions("0.2.0") == ["0.2.3b", "0.2.3c"]


def test_024_is_023c_plus_matchup_defense_only_and_never_publishes(monkeypatch):
    from dataclasses import asdict
    from modelroom.nba.props.config import PropParams, SHADOW_FILES
    c, d = PropParams.load(SHADOW_FILES["0.2.3c"]), PropParams.load(SHADOW_FILES["0.2.4"])
    dc, dd = asdict(c.settings), asdict(d.settings)
    assert {k for k in dc if dc[k] != dd[k]} == {"matchup_model", "role_model"}
    rates = {r for r, _, _ in d.settings.matchup_model}
    assert rates == {"blk", "fg2m", "fg3m", "ftm", "stl"}            # assists and rebounds keep the listed-position factor
    assert len(d.settings.role_model[3]) == 5                          # five roles
    monkeypatch.setenv("MODELROOM_NBA_PROPS_VERSION", "0.2.4")
    with pytest.raises(ValueError):
        P.active_version()
    monkeypatch.setenv("MODELROOM_NBA_PROPS_SHADOW", "0.2.3c,0.2.4")
    assert P.shadow_versions("0.2.0") == ["0.2.3c", "0.2.4"]


def test_matchup_model_off_leaves_earlier_params_hashes_unchanged():
    from modelroom.nba.props.config import PropParams, SHADOW_FILES, PARAMS_FILE
    for f in (PARAMS_FILE, SHADOW_FILES["0.2.3b"], SHADOW_FILES["0.2.3c"]):
        j = PropParams.load(f).to_json()["settings"]
        assert "matchup_model" not in j and "role_model" not in j
