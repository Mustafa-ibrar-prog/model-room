"""Scheduler health check: incident detection and duplicate-free alert planning."""
from datetime import UTC, datetime, timedelta

from modelroom import health as H

NOW = datetime(2026, 11, 8, 22, 13, tzinfo=UTC)
OK_STATUS = {"last_success": {"at": (NOW - timedelta(minutes=70)).isoformat(), "slot": "midday:2026-11-08"}, "missed": []}
OK_SUPA = {"ok": True, "enabled": "on", "token_stored": True, "failures_24h": 0,
           "last_accepted": (NOW - timedelta(minutes=3)).isoformat(), "last_dispatch": (NOW - timedelta(minutes=3)).isoformat()}
OK_RUNS = [{"id": 1, "event": "workflow_dispatch", "status": "completed", "conclusion": "success", "created_at": (NOW - timedelta(hours=1)).isoformat()}]


def keys(inc):
    return sorted(i["key"] for i in inc)


def test_healthy_system_has_no_incidents():
    assert H.evaluate(NOW, OK_STATUS, OK_RUNS, OK_SUPA) == []


def test_stale_refresh_after_3_hours():
    st = {**OK_STATUS, "last_success": {"at": (NOW - timedelta(hours=3, minutes=1)).isoformat(), "slot": "morning"}}
    assert keys(H.evaluate(NOW, st, OK_RUNS, OK_SUPA)) == ["stale-refresh"]
    st = {**OK_STATUS, "last_success": {"at": (NOW - timedelta(hours=2, minutes=59)).isoformat(), "slot": "morning"}}
    assert H.evaluate(NOW, st, OK_RUNS, OK_SUPA) == []
    assert keys(H.evaluate(NOW, {"last_success": None, "missed": []}, OK_RUNS, OK_SUPA)) == ["stale-refresh"]


def test_missed_slots_and_workflow_problems():
    st = {**OK_STATUS, "missed": ["midday:2026-11-08", "pregame:nba:2026-11-08T03:00:00+00:00"]}
    runs = OK_RUNS + [{"id": 2, "event": "push", "status": "completed", "conclusion": "failure", "created_at": (NOW - timedelta(hours=2)).isoformat()},
                      {"id": 3, "event": "schedule", "status": "completed", "conclusion": "failure", "created_at": (NOW - timedelta(hours=30)).isoformat()},  # too old
                      {"id": 4, "event": "workflow_dispatch", "status": "in_progress", "conclusion": None, "created_at": (NOW - timedelta(minutes=75)).isoformat()}]
    inc = H.evaluate(NOW, st, runs, OK_SUPA)
    assert keys(inc) == ["missed-slots", "workflow-failures", "workflow-stuck"]
    assert "run 3" not in next(i for i in inc if i["key"] == "workflow-failures")["detail"]


def test_supabase_checks():
    assert keys(H.evaluate(NOW, OK_STATUS, OK_RUNS, {"ok": False, "error": "connection refused"})) == ["supabase-unreachable"]
    for bad in ({"enabled": "off"}, {"token_stored": False}, {"failures_24h": 2}, {"last_accepted": (NOW - timedelta(minutes=25)).isoformat()}, {"last_accepted": None}):
        assert keys(H.evaluate(NOW, OK_STATUS, OK_RUNS, {**OK_SUPA, **bad})) == ["supabase-dispatch"], bad


def test_plan_opens_updates_closes_without_duplicates():
    inc = [{"key": "stale-refresh", "title": "t", "detail": "d"}, {"key": "missed-slots", "title": "t", "detail": "d"}]
    open_issues = [{"number": 7, "title": H.title_of({"key": "stale-refresh", "title": "Latest successful refresh is older than 3 hours"}), "body": ""},
                   {"number": 8, "title": H.title_of({"key": "supabase-dispatch", "title": "x"}), "body": ""},
                   {"number": 9, "title": "unrelated issue", "body": ""}]
    acts = {(a["action"], a.get("number"), (a.get("incident") or {}).get("key") or a.get("key")) for a in H.plan(inc, open_issues)}
    assert acts == {("update", 7, "stale-refresh"), ("open", None, "missed-slots"), ("close", 8, "supabase-dispatch")}
    # same incidents again with both issues open: only silent updates, no new issue
    open2 = open_issues[:1] + [{"number": 10, "title": H.title_of({"key": "missed-slots", "title": "t"}), "body": ""}]
    assert {a["action"] for a in H.plan(inc, open2)} == {"update"}
    # nothing wrong: open alerts close; unrelated issues are never touched
    assert {(a["action"], a["number"]) for a in H.plan([], open_issues)} == {("close", 7), ("close", 8)}


def test_body_has_no_secret_fields():
    b = H.body_of({"key": "k", "title": "t", "detail": "d"}, NOW, H.summary_of(NOW, OK_STATUS, OK_RUNS, OK_SUPA))
    assert "token_stored" in b and "github_pat" not in b and "postgres" not in b.lower()
