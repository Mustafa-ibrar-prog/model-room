"""Injury feed: parsing, the combine rules, and the scenarios the engines must handle.

Real samples (tests/fixtures/injuries): ESPN's Ravens roster / depth chart / injury feed and the official NBA
injury report, both fetched 2026-11-04 (Lamar Jackson and Tyler Huntley out, Joe Fagnano starting).
"""
import json
from datetime import UTC
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modelroom.injuries import espn as E
from modelroom.injuries import merge as MG
from modelroom.injuries import nba_official as N
from modelroom.injuries import schema as S

FIX = Path(__file__).parent / "fixtures" / "injuries"
NOW = pd.Timestamp("2026-11-04T17:05:00Z")


def _feed(path):
    d = json.loads(path.read_text())
    out = {}
    for t in d["injuries"]:
        for i in t["injuries"]:
            aid = i["athlete"]["links"][0]["href"].split("/id/")[-1].split("/")[0]
            out[aid] = {k: i.get(k) for k in ("status", "date", "shortComment", "longComment", "details", "type")}
    return out


def _ravens():
    rows, people = E.parse_team("nfl", json.loads((FIX / "espn_nfl_bal_roster.json").read_text()), _feed(FIX / "espn_nfl_injuries_bal.json"), NOW)
    dep = E.depth("nfl", json.loads((FIX / "espn_nfl_bal_depth.json").read_text()), "BAL", NOW)
    return {"rows": pd.DataFrame(rows, columns=S.COLUMNS), "roster": pd.DataFrame(people), "depth": pd.DataFrame(dep), "starters": pd.DataFrame(), "errors": []}


def _sched(teams=("BAL",), prev="2026-11-02T18:00:00Z", nxt="2026-11-06T01:15:00Z", gid="2026_09_JAX_BAL", gdate="2026-11-05"):
    return pd.DataFrame([{"team": t, "prev_start": pd.Timestamp(prev), "next_start": pd.Timestamp(nxt), "next_game_id": gid, "next_game_date": gdate} for t in teams])


# ---------------------------------------------------------------- Ravens QB case (NFL)

def test_ravens_statuses_from_espn():
    e = _ravens()
    qbs = e["rows"][e["rows"]["position"] == "QB"].set_index("player")
    assert qbs.loc["Lamar Jackson", "status"] == "out"
    assert qbs.loc["Tyler Huntley", "status"] == "out" and qbs.loc["Tyler Huntley", "long_term"]  # season-ending toe
    assert qbs.loc["Joe Fagnano", "status"] == "available"
    assert (e["rows"]["kind"] == "report").all()                  # ESPN = reports, never "official"
    exp = e["roster"].set_index("player")["experience_years"]
    assert exp["Joe Fagnano"] == 0 and exp["Lamar Jackson"] == 9


def test_ravens_starter_is_the_first_available_qb_on_the_depth_chart():
    from modelroom.nfl.starters import first_available

    e = _ravens()
    ids = {"3916387": "lamar", "4035671": "huntley", "4429582": "fagnano", "4428512": "slovis"}
    feed, _ = MG.combine("nfl", e, None, None, _sched(), ids, {}, None, NOW)
    out = set(feed[feed["current"] & feed["status"].isin(["out", "doubtful"])]["player_id"])
    assert {"lamar", "huntley"} <= out
    qb = e["depth"][e["depth"]["pos"] == "QB"].sort_values("rank")
    ranks = {ids[i]: r for i, r in zip(qb["source_player_id"], qb["rank"]) if i in ids}
    assert first_available(ranks, [p for p in ids.values() if p not in out]) == "fagnano"
    # With Fagnano also ruled out, the next QB on the chart starts.
    assert first_available(ranks, ["slovis"]) == "slovis"


def test_inexperienced_qb_scales_the_whole_passing_game():
    from pathlib import Path as P

    from modelroom.nfl.props.config import PropParams

    p = PropParams.load(P(__file__).resolve().parents[1] / "modelroom" / "nfl" / "props" / "params_0.1.1.json")
    assert p.settings.inexp_qb_attempts == 150 and p.settings.inexp_qb_yards == pytest.approx(0.931)
    p0 = PropParams.load()
    assert p0.settings.inexp_qb_attempts == 0  # 0.1.0 unchanged


# ---------------------------------------------------------------- official NBA report

def test_official_report_parses_every_team_and_status():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    rows, filings = N.parse((FIX / "nba_official_sample.pdf").read_bytes(), datetime(2026, 11, 4, 12, 0, tzinfo=ZoneInfo("America/New_York")))
    assert len(rows) > 100 and set(rows["status"]) <= {"out", "doubtful", "questionable", "probable", "available"}
    assert set(rows["team"]) <= set(N.TEAMS.values())             # page headers never become a team
    assert (rows["kind"] == "official").all()
    duren = rows[rows["player"] == "Duren, Jalen"].iloc[0]
    assert duren["team"] == "DET" and duren["status"] == "out" and duren["game_date"] == "2026-11-04"
    assert any(not f["submitted"] for f in filings)               # "NOT YET SUBMITTED" teams are kept as such


def test_candidate_urls_step_back_every_15_minutes():
    from datetime import datetime

    u = N.candidate_urls(datetime(2026, 11, 4, 17, 7, tzinfo=UTC), hours_back=1)
    assert u[0][0].endswith("Injury-Report_2026-11-04_12_00PM.pdf")
    assert u[1][0].endswith("Injury-Report_2026-11-04_12PM.pdf")   # older hourly name for the same hour
    assert u[2][0].endswith("Injury-Report_2026-11-04_11_45AM.pdf")


# ---------------------------------------------------------------- combine rules

def _row(**k):
    base = {c: None for c in S.COLUMNS}
    base.update(league="nba", team="DET", player="Jalen Duren", source_player_id="1", player_id="1", restriction=False, returning=False,
                long_term=False, fetched_at=NOW)
    base.update(k)
    return base


def _df(*rows):
    return pd.DataFrame([_row(**r) for r in rows], columns=S.COLUMNS)


def _espn(*rows):
    return {"rows": _df(*rows), "roster": pd.DataFrame([{"team": "DET", "source_player_id": "1", "player": "Jalen Duren", "position": "C"},
                                                         {"team": "DET", "source_player_id": "2", "player": "Isaiah Joe", "position": "G"}]),
            "depth": pd.DataFrame(), "starters": pd.DataFrame(), "errors": []}


def test_stale_designation_is_never_current():
    e = _espn({"source": "espn", "kind": "report", "status": "questionable", "raw_status": "Questionable", "report_time": pd.Timestamp("2026-11-01T12:00Z")})
    f, _ = MG.combine("nba", e, None, None, _sched(("DET",), prev="2026-11-03T00:00Z", gdate="2026-11-04"), {}, {}, None, NOW)
    r = f.iloc[0]
    assert r["stale"] and not r["current"] and "earlier game" in r["stale_reason"]


def test_out_report_older_than_his_last_game_is_stale():
    e = _espn({"source": "espn", "kind": "report", "status": "out", "raw_status": "Out", "report_time": pd.Timestamp("2026-10-30T12:00Z")})
    f, _ = MG.combine("nba", e, None, None, _sched(("DET",), gdate="2026-11-04"), {}, {"1": pd.Timestamp("2026-11-02T00:00Z")}, None, NOW)
    assert f.iloc[0]["stale"] and f.iloc[0]["stale_reason"] == "has played since this report"


def test_official_report_wins_and_the_conflict_is_kept():
    e = _espn({"source": "espn", "kind": "report", "status": "questionable", "raw_status": "Questionable", "report_time": pd.Timestamp("2026-11-04T16:00Z")})
    off = {"rows": _df({"source": "nba_official", "kind": "official", "status": "out", "raw_status": "Out", "player": "Duren, Jalen",
                        "player_id": None, "source_player_id": None, "report_time": pd.Timestamp("2026-11-04T17:00Z"), "game_date": "2026-11-04"}),
           "filings": [{"game_date": "2026-11-04", "team": "DET", "submitted": True}]}
    f, meta = MG.combine("nba", e, off, None, _sched(("DET",), gdate="2026-11-04"), {}, {}, None, NOW)
    cur = f[f["current"]].iloc[0]
    assert cur["status"] == "out" and cur["source"] == "nba_official" and cur["confirmed"]
    assert "espn: Questionable" in cur["conflict"] and meta["conflicts"] == 1


def test_not_listed_on_a_submitted_official_report_means_available():
    e = _espn({"source": "espn", "kind": "report", "status": "out", "raw_status": "Out", "report_time": pd.Timestamp("2026-11-04T15:00Z")})
    off = {"rows": _df({"source": "nba_official", "kind": "official", "status": "out", "raw_status": "Out", "player": "Joe, Isaiah",
                        "player_id": None, "source_player_id": None, "report_time": pd.Timestamp("2026-11-04T17:00Z"), "game_date": "2026-11-04"}),
           "filings": [{"game_date": "2026-11-04", "team": "DET", "submitted": True}]}
    f, _ = MG.combine("nba", e, off, None, _sched(("DET",), gdate="2026-11-04"), {}, {}, None, NOW)
    duren = f[f["current"] & (f["player_id"] == "1")].iloc[0]
    assert duren["status"] == "available" and duren["source"] == "nba_official" and "not listed" in duren["conflict"]


def test_unsubmitted_team_report_is_flagged_not_assumed():
    e = _espn({"source": "espn", "kind": "report", "status": "questionable", "raw_status": "Questionable", "report_time": pd.Timestamp("2026-11-04T15:00Z")})
    off = {"rows": _df(), "filings": [{"game_date": "2026-11-04", "team": "DET", "submitted": False}]}
    f, _ = MG.combine("nba", e, off, None, _sched(("DET",), gdate="2026-11-04"), {}, {}, None, NOW)
    r = f[f["current"]].iloc[0]
    assert r["status"] == "questionable" and r["team_report"] == "not yet submitted" and not r["confirmed"]


def test_late_scratch_is_flagged():
    e = _espn({"source": "espn", "kind": "report", "status": "out", "raw_status": "Out", "report_time": pd.Timestamp("2026-11-04T23:30Z")})
    prev = pd.DataFrame([{"player_id": "1", "status": "probable"}])
    f, _ = MG.combine("nba", e, None, None, _sched(("DET",), nxt="2026-11-05T00:30Z", gdate="2026-11-04"), {}, {}, prev, pd.Timestamp("2026-11-04T23:45Z"))
    assert f[f["current"]].iloc[0]["late_scratch"]
    f2, _ = MG.combine("nba", e, None, None, _sched(("DET",), nxt="2026-11-06T00:30Z", gdate="2026-11-05"), {}, {}, prev, pd.Timestamp("2026-11-04T23:45Z"))
    assert not f2[f2["current"]].iloc[0]["late_scratch"]          # two days out: a change, not a late scratch


def test_missing_data_returns_nothing_rather_than_healthy():
    f, _ = MG.combine("nba", None, None, None, _sched(("DET",)), {}, {}, None, NOW)
    assert f.empty


def test_restriction_and_return_text():
    assert S.restriction("He'll be on a minutes restriction of about 20 minutes.") == (True, 20.0)
    assert S.restriction("He is expected to have limited minutes.") == (True, None)
    assert S.restriction("Full participant.") == (False, None)
    assert S.returning("Smith is expected to return Friday") and not S.returning("Smith remains out")
    assert S.canonical("Injured Reserve") == "out" and S.canonical("Day-To-Day") == "questionable" and S.canonical("???") == "unknown"
    assert S.norm_name("Jackson Jr., Jaren") == S.norm_name("Jaren Jackson Jr.") == "jaren jackson"


def test_all_sources_failing_logs_and_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path))
    monkeypatch.setattr(MG, "data_root", lambda: tmp_path)

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(E, "fetch", boom)
    monkeypatch.setattr(N, "fetch", boom)
    with pytest.raises(RuntimeError, match="every source failed"):
        MG.run("nba", now=NOW)
    log = [json.loads(x) for x in (tmp_path / "injury_snapshots_nba.jsonl").read_text().splitlines()]
    assert log[-1]["status"] == "failed" and not log[-1]["sources"]["espn"]["ok"] and not log[-1]["sources"]["nba_official"]["ok"]


# ---------------------------------------------------------------- NBA prop model scenarios (0.2.1)

def _ctx(players):
    from modelroom.nba.props.model import Context

    P = pd.DataFrame(players).set_index("player_id")
    for c, v in {"usage_pm": 0.5, "fg2m_pm": 0.15, "fg3m_pm": 0.05, "ftm_pm": 0.1, "reb_pm": 0.2, "ast_pm": 0.1, "stl_pm": 0.03,
                 "blk_pm": 0.02, "n_games": 30, "n_minutes": 900, "last_game": pd.Timestamp("2026-11-02"), "team": "DET",
                 "starter_rate": 0.0, "missed_in_row": 0, "appear_rate": 1.0}.items():
        P[c] = P[c].fillna(v) if c in P else v
    P["minutes_high"] = P.get("minutes_high", P["minutes_when_playing"] + 4)
    return Context(pd.Timestamp("2026-11-04"), 2027, P, pd.DataFrame(index=pd.MultiIndex.from_tuples([], names=["opp", "group"])),
                   pd.Series(dtype=float), {"pace": 100.0})


ROSTER = [
    {"player_id": "c1", "name": "Starting C", "group": "C", "minutes_when_playing": 32.0, "starter_rate": 1.0, "reb_pm": 0.35, "usage_pm": 0.6},
    {"player_id": "c2", "name": "Backup C", "group": "C", "minutes_when_playing": 14.0, "reb_pm": 0.3},
    {"player_id": "pg", "name": "Starting PG", "group": "G", "minutes_when_playing": 34.0, "starter_rate": 1.0, "ast_pm": 0.25, "usage_pm": 0.8},
    {"player_id": "g2", "name": "Backup G", "group": "G", "minutes_when_playing": 18.0, "ast_pm": 0.15},
    {"player_id": "f1", "name": "Starting F", "group": "F", "minutes_when_playing": 33.0, "starter_rate": 1.0},
    {"player_id": "f2", "name": "Second F", "group": "F", "minutes_when_playing": 30.0, "starter_rate": 1.0},
    {"player_id": "w1", "name": "Wing", "group": "F", "minutes_when_playing": 31.0, "starter_rate": 1.0},
    {"player_id": "b1", "name": "Bench F", "group": "F", "minutes_when_playing": 20.0},
    {"player_id": "b2", "name": "Bench G", "group": "G", "minutes_when_playing": 16.0},
    {"player_id": "b3", "name": "Bench big", "group": "C", "minutes_when_playing": 12.0},
]


def _project(status: dict, roster=ROSTER, back=None, submitted=True, restriction=None):
    from dataclasses import replace

    from modelroom.nba.props import model as M
    from modelroom.nba.props.config import INJURY_FILE, PropParams

    p = PropParams.load(INJURY_FILE)
    p = replace(p, settings=replace(p.settings, sims=3000))
    feed = pd.DataFrame([{"player_id": k, "status": v, "raw_status": v.title(), "source": "nba_official", "kind": "official",
                          "report_time": NOW, "restriction": bool(restriction and k in restriction), "detail": None,
                          "restriction_minutes": (restriction or {}).get(k)} for k, v in status.items()],
                        columns=["player_id", "status", "raw_status", "source", "kind", "report_time", "restriction", "restriction_minutes", "detail"])
    av = M.availability(feed, back or {}, submitted, None)
    res = M.project_team(_ctx(roster), "g", "DET", "PHI", 0.0, None, p, np.random.default_rng(1), av)
    return {x.player_id: x for x in res}


def _minutes(proj):
    return {k: x.inputs["projected_minutes"] for k, x in proj.items()}


def test_starting_center_out_moves_minutes_and_rebounds_to_the_other_bigs():
    base, out = _project({}), _project({"c1": "out"})
    assert "c1" not in out
    m0, m1 = _minutes(base), _minutes(out)
    assert m1["c2"] > m0["c2"] and m1["b3"] >= m0["b3"]
    assert out["c2"].mean("reb") > base["c2"].mean("reb")
    assert out["c2"].inputs["usage_freed_by_absences"] > 0
    assert sum(m1.values()) == pytest.approx(sum(m0.values()), rel=0.02)   # the team's minutes are refilled, not inflated


def test_starting_point_guard_out_lifts_the_backup_guard():
    base, out = _project({}), _project({"pg": "out"})
    assert _minutes(out)["g2"] > _minutes(base)["g2"]
    assert out["g2"].mean("ast") > base["g2"].mean("ast") and out["g2"].mean("pts") > base["g2"].mean("pts")


def test_multiple_teammates_out_without_double_counting():
    one, two = _project({"pg": "out"}), _project({"pg": "out", "c1": "out"})
    f1, f2 = one["g2"].inputs["usage_freed_by_absences"], two["g2"].inputs["usage_freed_by_absences"]
    assert 0 < f1 < f2 < 1                                     # shares of one team total, so they can't exceed 100%
    assert max(_minutes(two).values()) <= 42.0                 # nobody pushed past the cap to absorb two absences
    from modelroom.nba.props.config import TEAM_MINUTES

    assert sum(_minutes(two).values()) <= TEAM_MINUTES + 1e-6       # two absences never create extra team minutes
    assert all(_minutes(two)[k] >= _minutes(one)[k] - 1e-6 for k in _minutes(two))   # each teammate gains or holds


def test_questionable_player_who_plays_is_projected_normally():
    base, q = _project({}), _project({"f1": "questionable"})
    assert "f1" in q and q["f1"].inputs["projected_minutes"] == pytest.approx(base["f1"].inputs["projected_minutes"])
    assert q["g2"].inputs["usage_freed_by_absences"] == base["g2"].inputs["usage_freed_by_absences"] == 0


def test_doubtful_frees_part_of_his_usage():
    out, dbt = _project({"pg": "out"}), _project({"pg": "doubtful"})
    assert "pg" not in dbt
    assert 0 < dbt["g2"].inputs["usage_freed_by_absences"] < out["g2"].inputs["usage_freed_by_absences"]


def test_returning_player_gets_the_measured_first_game_minutes():
    roster = [dict(r) for r in ROSTER]
    roster[4] = {**roster[4], "missed_in_row": 5, "appear_rate": 0.5}
    gone = _project({}, roster, submitted=False)                 # no report: the missed-games rule keeps him out
    assert "f1" not in gone
    back = _project({"f1": "available"}, roster)
    note = back["f1"].inputs["availability"]["notes"][0]
    assert "game 1 back" in note
    assert back["f1"].inputs["projected_minutes"] < 33.0 * 0.80  # x0.743 before the fill (fill may add a little)
    assert back["f1"].sd("minutes") > _project({}, ROSTER)["f1"].sd("minutes")


def test_stated_minutes_restriction_caps_minutes():
    r = _project({"pg": "probable"}, restriction={"pg": 20.0})
    assert r["pg"].inputs["projected_minutes"] <= 24.0
    assert any("restriction" in n for n in r["pg"].inputs["availability"]["notes"])


def test_version_020_ignores_the_feed():
    from dataclasses import replace

    from modelroom.nba.props import model as M
    from modelroom.nba.props.config import CANDIDATE_FILE, PropParams

    p = PropParams.load(CANDIDATE_FILE)
    p = replace(p, settings=replace(p.settings, sims=500))
    av = M.availability(pd.DataFrame([{"player_id": "pg", "status": "out", "raw_status": "Out", "source": "x", "kind": "official", "report_time": NOW,
                                       "restriction": False, "restriction_minutes": None, "detail": None}]), {}, True, None)
    res = {x.player_id for x in M.project_team(_ctx(ROSTER), "g", "DET", "PHI", 0.0, None, p, np.random.default_rng(1), av)}
    assert "pg" in res                                          # 0.2.0 doesn't read the injury feed


# ---------------------------------------------------------------- snapshots never overwritten

def test_changed_injury_picture_is_a_new_snapshot(tmp_path):
    from modelroom.common import ledger

    f = tmp_path / "x.jsonl"
    rec = {"sport": "nba", "kind": "player_props", "game_id": "g|1", "model_version": "0.2.1", "params_hash": "p", "inputs_hash": "a",
           "generated_at": "2026-11-04T15:00:00+00:00", "game_start": "2026-11-05T00:00:00+00:00", "probabilities": {}}
    ledger.append(f, [rec])
    first = f.read_text()
    ledger.append(f, [{**rec, "inputs_hash": "b", "generated_at": "2026-11-04T20:00:00+00:00"}])
    ledger.append(f, [{**rec, "inputs_hash": "b", "generated_at": "2026-11-04T23:00:00+00:00"}])   # same picture: deduped
    lines = f.read_text().splitlines()
    assert f.read_text().startswith(first) and len(lines) == 2


def test_no_lineups_posted_yet_is_not_an_error(tmp_path, monkeypatch):
    """Before ESPN posts lineups the starters table is empty; availability still builds (starters = unknown)."""
    from modelroom.injuries import use as U

    proc = tmp_path / "nba"
    proc.mkdir()
    feed = pd.DataFrame([{**_row(status="out", raw_status="Out", source="nba_official", kind="official", report_time=NOW), "current": True, "stale": False}])
    feed.to_parquet(proc / "injury_feed.parquet")
    pd.DataFrame(columns=E.STARTER_COLUMNS).to_parquet(proc / "starters_live.parquet")
    monkeypatch.setattr(U, "processed_dir", lambda lg: proc)
    monkeypatch.setattr(U, "live_meta", lambda lg: {"filings": [], "generated_at": NOW.isoformat()})
    up = pd.DataFrame([{"game_id": "401", "start_time": pd.Timestamp("2026-11-05T00:00Z"), "home_abbr": "DET", "away_abbr": "PHI"}])
    pg = pd.DataFrame([{"player_id": "1", "game_date": "2026-11-02", "played": True, "season": 2027}])
    av = U.nba_availability(up, pg)
    assert av[("401", "DET")]["players"]["1"]["status"] == "out" and av[("401", "DET")]["starters"] is None
    assert U.availability_hash("nba")
