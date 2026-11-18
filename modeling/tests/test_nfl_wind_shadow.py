"""NFL 0.1.6a / 0.1.6 (TEST shadows): recalibration control and pregame forecast wind, reduce-only.

Forecast handling: only runs issued >= 5 h before kickoff and retrieved before the prediction are used; malformed, missing,
late or future data leaves the projection unchanged; domes, retractable roofs and neutral / international sites are never
adjusted; nothing about 0.1.5 changes."""
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from modelroom.nfl import weather as WX
from modelroom.nfl.props import wind as WIND
from modelroom.nfl.props.config import RECAL_FILE, TDS_FILE, WIND_FILE, PropParams, PropSettings


def _payload(runtime="2026-11-22 06:00", start="2026-11-22 12:00", n=8, wsp=18, wdr=270):
    t0 = pd.Timestamp(start)
    return {"data": [{"runtime": runtime, "ftime": str(t0 + pd.Timedelta(hours=3 * i)), "wsp": wsp, "wdr": wdr} for i in range(n)]}


# ------------------------------------------------------------------ versions
def test_016a_is_015_with_only_calibration_changed():
    a, b = PropParams.load(TDS_FILE), PropParams.load(RECAL_FILE)
    assert asdict(a.settings) == asdict(b.settings) and a.volume == b.volume
    assert a.calibration != b.calibration and set(b.calibration) >= set(a.calibration)


def test_016_is_016a_plus_wind_only():
    b, c = PropParams.load(RECAL_FILE), PropParams.load(WIND_FILE)
    db, dc = asdict(b.settings), asdict(c.settings)
    assert sorted(k for k in db if db[k] != dc[k]) == ["wind_adjust", "wind_reduce_only"]
    assert c.settings.wind_reduce_only is True and len(c.settings.wind_adjust) == 6
    assert {m for m, *_ in c.settings.wind_adjust} == {"passing_yards", "passing_completions", "passing_attempts", "passing_tds",
                                                       "receiving_yards", "receptions"}
    for _, a_, b_, w in c.settings.wind_adjust:
        assert b_ < 0 and a_ > 0 and 5 < w < 15        # more wind -> lower, around the fitted average


def test_015_params_and_hash_untouched_by_new_settings():
    d = PropParams.load(TDS_FILE).to_json()["settings"]
    assert "wind_adjust" not in d and "wind_reduce_only" not in d and "wind_max_mph" not in d
    s = PropSettings()
    assert s.wind_adjust == () and s.wind_reduce_only is False


def test_new_versions_are_shadow_only(monkeypatch):
    from modelroom.nfl.props import pipeline as P
    for v in ("0.1.6", "0.1.6a"):
        monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", v)
        with pytest.raises(ValueError):
            P.active_version()
    monkeypatch.setenv("MODELROOM_NFL_PROPS_VERSION", "0.1.1")
    monkeypatch.setenv("MODELROOM_NFL_PROPS_SHADOW", "0.1.5,0.1.6a,0.1.6")
    assert P.shadow_versions("0.1.1") == ["0.1.5", "0.1.6a", "0.1.6"]


# ------------------------------------------------------------------ parsing bad data
def test_parse_rejects_malformed_and_drops_impossible_values():
    with pytest.raises(ValueError):
        WX.parse({}, "KPIT")
    with pytest.raises(ValueError):
        WX.parse({"data": []}, "KPIT")
    two = _payload()["data"] + _payload(runtime="2026-11-22 12:00")["data"]
    with pytest.raises(ValueError):
        WX.parse({"data": two}, "KPIT")                       # mixed runs: refuse rather than guess
    bad = _payload()
    bad["data"][0]["wsp"] = "N/A"; bad["data"][1]["wsp"] = 250; bad["data"][2]["wsp"] = None; bad["data"][3]["wdr"] = 999
    issued, rows = WX.parse(bad, "KPIT")
    assert len(rows) == 5 and rows[0]["wind_dir"] is None   # 3 impossible winds dropped; bad direction kept as unknown
    with pytest.raises(ValueError):
        WX.parse(_payload(wsp=None), "KPIT")


# ------------------------------------------------------------------ fetch: storage, failures, roofs
def _games():
    return pd.DataFrame({"game_id": ["2026_12_X_PIT", "2026_12_Y_ATL", "2026_12_Z_LON", "2026_12_W_PIT"],
                         "start_time": pd.to_datetime(["2026-11-22 18:00", "2026-11-22 18:00", "2026-11-22 14:30", "2026-11-26 18:00"], utc=True),
                         "stadium_id": ["PIT00", "ATL97", "LON02", "PIT00"]})


def test_fetch_stores_only_open_air_games_in_window_with_times(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path))
    calls = []
    getter = lambda st: (calls.append(st), _payload())[1]
    out = WX.fetch(_games(), pd.Timestamp("2026-11-22 11:00", tz="UTC"), getter=getter)
    assert out["open_air"] == 1 and out["stored"] == 1 and calls == ["KAGC"]    # dome, international, >40 h out: skipped
    r = WX.load()[0]
    assert r["nfl_game_id"] == "2026_12_X_PIT" and r["stadium_id"] == "PIT00" and r["station"] == "KAGC"
    assert r["issued_at"].startswith("2026-11-22T06:00") and r["retrieved_at"].startswith("2026-11-22T11:00")
    assert all("wind_kt" in x and "wind_dir" in x for x in r["rows"])
    again = WX.fetch(_games(), pd.Timestamp("2026-11-22 11:30", tz="UTC"), getter=getter)
    assert again["stored"] == 0 and again["duplicate"] == 1                     # same run: first copy kept as written


def test_fetch_failures_never_raise_and_store_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path))

    def boom(st):
        raise OSError("timeout")
    out = WX.fetch(_games(), pd.Timestamp("2026-11-22 11:00", tz="UTC"), getter=boom)
    assert out["stored"] == 0 and len(out["problems"]) == 2                    # primary + fallback station both tried
    fut = WX.fetch(_games(), pd.Timestamp("2026-11-22 05:00", tz="UTC"), getter=lambda st: _payload(runtime="2026-11-22 06:00"))
    assert fut["stored"] == 0 and "future" in fut["problems"][0]["error"]
    assert WX.load() == []


def test_no_forecast_recorded_after_kickoff(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path))
    out = WX.fetch(_games(), pd.Timestamp("2026-11-22 18:30", tz="UTC"), getter=lambda st: _payload())
    assert out["stored"] == 0 and WX.load() == []


# ------------------------------------------------------------------ selection: what a prediction may use
def _rec(issued, retrieved, wsp=18, gid="G"):
    t0 = pd.Timestamp("2026-11-22 15:00", tz="UTC")
    return {"nfl_game_id": gid, "source": WX.SOURCE, "station": "KAGC", "issued_at": pd.Timestamp(issued, tz="UTC").isoformat(),
            "retrieved_at": pd.Timestamp(retrieved, tz="UTC").isoformat(),
            "rows": [{"valid": (t0 + pd.Timedelta(hours=3 * i)).isoformat(), "wind_kt": wsp, "wind_dir": 270} for i in range(4)]}


KICK = pd.Timestamp("2026-11-22 18:00", tz="UTC")


def test_select_uses_only_runs_issued_5h_before_kickoff_and_seen_before_the_prediction():
    early = _rec("2026-11-22 06:00", "2026-11-22 11:00", wsp=10)
    late = _rec("2026-11-22 12:00", "2026-11-22 16:30", wsp=25)           # issued 6 h before: usable once retrieved
    revised = _rec("2026-11-22 14:00", "2026-11-22 17:30", wsp=40)         # issued 4 h before kickoff: never usable
    recs = [early, late, revised]
    s = WX.select(recs, "G", KICK, pd.Timestamp("2026-11-22 16:00", tz="UTC"))
    assert s["usable"] and s["issued_at"].startswith("2026-11-22T06:00")   # 12Z run not yet retrieved at 16:00
    s = WX.select(recs, "G", KICK, pd.Timestamp("2026-11-22 17:45", tz="UTC"))
    assert s["usable"] and s["issued_at"].startswith("2026-11-22T12:00") and s["wind_mph"] == round(25 * WX.KT_TO_MPH, 1)
    assert WX.select([revised], "G", KICK, KICK)["usable"] is False
    assert WX.select(recs, "G", KICK, pd.Timestamp("2026-11-22 10:00", tz="UTC"))["reason"] == "no forecast retrieved before this prediction"
    assert WX.select([], "G", KICK, KICK)["reason"] == "no forecast stored"


def test_select_refuses_a_run_that_does_not_cover_the_game():
    r = _rec("2026-11-22 06:00", "2026-11-22 11:00")
    r["rows"] = r["rows"][:1]                                               # only 15:00Z: game middle is 19:30Z
    assert WX.select([r], "G", KICK, KICK)["reason"] == "forecast does not cover the game"


def test_for_games_never_adjusts_domes_retractables_or_neutral_sites():
    g = _games()
    sel = WX.for_games(g, KICK, recs=[_rec("2026-11-22 06:00", "2026-11-22 11:00", gid=x) for x in g["game_id"]])
    assert not sel["2026_12_Y_ATL"]["usable"] and not sel["2026_12_Z_LON"]["usable"]
    assert sel["2026_12_X_PIT"]["usable"]


# ------------------------------------------------------------------ the adjustment
class _P:
    def __init__(self, gid, group, sims):
        self.game_id, self.player_id, self.group, self.sims = gid, "p" + group, group, sims


def _sims(rng):
    att = rng.poisson(34, 4000).astype(float)
    return {"pass_yds": rng.normal(240, 60, 4000), "pass_cmp": np.minimum(rng.poisson(22, 4000).astype(float), att), "pass_att": att,
            "pass_td": rng.poisson(1.6, 4000).astype(float), "rec_yds": rng.normal(50, 25, 4000), "receptions": rng.poisson(4, 4000).astype(float),
            "rush_rec_yds": rng.normal(60, 25, 4000), "fantasy_ppr": rng.normal(15, 6, 4000)}


S16 = PropParams.load(WIND_FILE).settings


def test_reduce_only_lowers_in_wind_and_never_raises_in_calm():
    rng = np.random.default_rng(1)
    qb, wr, calm_qb = _P("W", "QB", _sims(rng)), _P("W", "WR", _sims(rng)), _P("C", "QB", _sims(rng))
    before = {id(x): {k: v.copy() for k, v in x.sims.items()} for x in (qb, wr, calm_qb)}
    used = WIND.apply([qb, wr, calm_qb], {"W": {"usable": True, "wind_mph": 22.0}, "C": {"usable": True, "wind_mph": 3.0}}, S16, seed=7)
    assert all(f <= 1.0 for f in used["W"].values()) and all(f == 1.0 for f in used["C"].values())
    for k, v in calm_qb.sims.items():
        assert np.array_equal(v, before[id(calm_qb)][k])                    # calm: exactly unchanged
    assert qb.sims["pass_yds"].mean() < before[id(qb)]["pass_yds"].mean()
    assert abs(qb.sims["pass_yds"].mean() / before[id(qb)]["pass_yds"].mean() - used["W"]["passing_yards"]) < 1e-4    # factor is recorded to 4 decimals
    assert np.all(qb.sims["pass_cmp"] <= qb.sims["pass_att"]) and np.all(qb.sims["pass_cmp"] % 1 == 0)
    assert wr.sims["rec_yds"].mean() < before[id(wr)]["rec_yds"].mean()
    assert np.array_equal(wr.sims["pass_yds"], before[id(wr)]["pass_yds"])  # a receiver's passing stats are not touched


def test_missing_or_unusable_forecast_leaves_projection_unchanged():
    rng = np.random.default_rng(2)
    a, b = _P("A", "QB", _sims(rng)), _P("B", "TE", _sims(rng))
    before = {id(x): {k: v.copy() for k, v in x.sims.items()} for x in (a, b)}
    used = WIND.apply([a, b], {"A": {"usable": False, "reason": "no forecast stored"}}, S16, seed=7)
    assert used == {}
    for x in (a, b):
        for k, v in x.sims.items():
            assert np.array_equal(v, before[id(x)][k])


def test_wind_above_fit_range_is_capped():
    f = dict(zip(("a", "b", "wbar"), PropParams.load(WIND_FILE).settings.wind_adjust[0][1:]))
    assert WIND.factor(f, 45, 30.0, True) == WIND.factor(f, 30, 30.0, True) < 1.0
