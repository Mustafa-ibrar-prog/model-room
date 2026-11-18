"""Only the published prop version ever becomes a pick or a shown result; shadows sharing a ledger are ignored."""
import re
from pathlib import Path

from modelroom import published as PUB
from modelroom.history import _pregame

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "preview.yml"


def _env(name):
    m = re.search(rf"^\s*{name}:\s*\"([^\"]*)\"", WORKFLOW.read_text(), re.M)
    return m.group(1) if m else None


def test_timeline_matches_the_workflow():
    for lg in ("nba", "nfl"):
        assert PUB.TIMELINE[lg][-1][1] == _env(f"MODELROOM_{lg.upper()}_PROPS_VERSION"), \
            f"{lg}: add the active-version switch to modelroom/published.py"
        shadows = [v for v in (_env(f"MODELROOM_{lg.upper()}_PROPS_SHADOW") or "").split(",") if v]
        assert PUB.TIMELINE[lg][-1][1] not in shadows


def test_published_version_at_switches():
    assert PUB.published_version("nba", "2026-11-03T12:00:00+00:00") == "0.1.0"
    assert PUB.published_version("nba", "2026-11-05T00:00:00+00:00") == "0.2.1"
    assert PUB.published_version("nba", "2026-11-08T02:22:42+00:00") == "0.2.1"
    assert PUB.published_version("nba", "2026-11-08T02:22:43+00:00") == "0.2.0"
    assert PUB.published_version("nfl", "2026-11-04T17:00:00+00:00") == "0.1.0"
    assert PUB.published_version("nfl", "2026-11-20T00:00:00+00:00") == "0.1.1"


def test_shadow_record_never_wins_even_when_newer():
    base = {"game_id": "g|p", "game_start": "2026-11-20T01:00:00+00:00"}
    recs = [{**base, "model_version": "0.1.1", "generated_at": "2026-11-19T20:00:00+00:00"},
            {**base, "model_version": "0.1.5", "generated_at": "2026-11-20T00:30:00+00:00"},   # newer shadow
            {**base, "model_version": "0.1.0", "generated_at": "2026-11-20T00:31:00+00:00"}]   # newer shadow
    kept = _pregame([r for r in recs if PUB.is_published("nfl", r)])
    assert kept["g|p"]["model_version"] == "0.1.1"
    # the old behaviour, for the record: the newest record of any version would have been used
    assert _pregame(recs)["g|p"]["model_version"] == "0.1.0"


def _settle(monkeypatch, picks):
    """Run history's pick settlement on stored picks with every ledger write stubbed out; returns (summary, day rows)."""
    from datetime import datetime, timezone
    from modelroom import history as H
    from modelroom import picks as P
    written = {}
    monkeypatch.setattr(P, "freeze", lambda *a, **k: {})
    monkeypatch.setattr(P, "read_picks", lambda league: {p["game_id"]: p for p in picks})
    monkeypatch.setattr(P, "record_grades", lambda *a, **k: {})
    monkeypatch.setattr(H, "write_board", lambda path, body: written.__setitem__(path.name, body))
    day = "2026-11-09"
    days_out = {day: {}}
    games = [{"game_id": "401", "final": {"home": 100, "away": 90}, "status": "final"}]
    stats = {("401", "p1"): {"pts": 25.0}, ("401", "p2"): {"pts": 10.0}}
    H._settle_picks("nba", [], {day: games}, days_out, stats, {"points": "pts"}, {"401"}, datetime(2026, 11, 18, tzinfo=timezone.utc), False, {})
    return written["picks_summary.json"], days_out[day]["picks"]


def _pick(pid, version, generated_at, line, sel="at_least"):
    return {"game_id": f"nba:401:prop:{pid}:points", "league_game_id": "401", "market": "prop", "selection": sel, "line": line,
            "player": pid, "player_id": pid, "stat": "points", "model_version": version, "generated_at": generated_at,
            "frozen_before_start": False, "model_number": 20.0, "model_prob": 0.6}


def test_unpublished_version_picks_are_kept_labelled_but_not_counted(monkeypatch):
    picks = [_pick("p1", "0.2.0", "2026-11-09T18:00:00+00:00", 20),    # published then: counts (hit)
             _pick("p2", "0.2.3a", "2026-11-09T18:00:00+00:00", 5)]    # shadow: graded (hit) but excluded
    summary, rows = _settle(monkeypatch, picks)
    assert summary["overall"]["prop"]["hit"] == 1 and summary["overall"]["prop"]["graded"] == 1
    assert summary["by_date"][0]["props"]["graded"] == 1
    assert summary["provenance"]["prop"]["reconstructed"] == 1
    ex = summary["excluded"]
    assert ex["total"] == 1 and ex["by_version"] == {"0.2.3a": 1} and ex["picks"][0]["published_version"] == "0.2.0"
    assert ex["record"]["hit"] == 1                       # still graded, just not counted
    lab = {r["player_id"]: r.get("excluded") for r in rows}
    assert lab == {"p1": None, "p2": "unpublished_version"}  # both stay on the day file, the shadow one labelled


def test_version_that_was_published_at_the_time_still_counts(monkeypatch):
    # 0.2.1 was the published version on 2026-11-05: its picks are official even though 0.2.0 is published today
    summary, _ = _settle(monkeypatch, [_pick("p1", "0.2.1", "2026-11-05T18:00:00+00:00", 20)])
    assert summary["overall"]["prop"]["graded"] == 1 and summary["excluded"]["total"] == 0
