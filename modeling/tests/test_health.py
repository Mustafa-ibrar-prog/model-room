"""Scheduler health check: incident detection and duplicate-free alert planning."""
from datetime import UTC, datetime, timedelta

from modelroom import health as H

NOW = datetime(2026, 11, 8, 22, 13, tzinfo=UTC)
OK_STATUS = {"last_success": {"at": (NOW - timedelta(minutes=70)).isoformat(), "slot": "midday:2026-11-08"}, "missed": []}
# A healthy scheduler now sleeps between refresh slots: the next wake is in the future, a run reported it, and the
# last dispatch may be hours old. Quiet is normal; an overdue wake or unanswered dispatches are not.
OK_SUPA = {"ok": True, "enabled": "on", "token_stored": True, "failures_24h": 0,
           "last_accepted": (NOW - timedelta(hours=4)).isoformat(), "last_dispatch": (NOW - timedelta(hours=4)).isoformat(),
           "next_check_at": (NOW + timedelta(hours=1)).isoformat(), "next_check_reason": "next slot midday:2026-11-09",
           "plan_updated_at": (NOW - timedelta(hours=4)).isoformat(), "dispatches_since_update": 0,
           "minutes_overdue": 0, "plan_stale": False}
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
    for bad in ({"enabled": "off"}, {"token_stored": False}, {"failures_24h": 2}, {"last_accepted": None},
                {"minutes_overdue": 45},            # a wake time passed and no run started
                {"plan_stale": True},               # no run has reported back for over 6 hours
                {"dispatches_since_update": 12}):   # dispatches going unanswered
        assert keys(H.evaluate(NOW, OK_STATUS, OK_RUNS, {**OK_SUPA, **bad})) == ["supabase-dispatch"], bad
    # A long quiet stretch between slots is not an incident any more.
    assert H.evaluate(NOW, OK_STATUS, OK_RUNS, {**OK_SUPA, "last_dispatch": (NOW - timedelta(hours=5)).isoformat()}) == []
    assert H.evaluate(NOW, OK_STATUS, OK_RUNS, {**OK_SUPA, "minutes_overdue": 15}) == []


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


def test_supabase_api_restriction_is_an_incident():
    assert H.evaluate(NOW, OK_STATUS, OK_RUNS, OK_SUPA, {"status": 200, "reason": None}) == []
    inc = H.evaluate(NOW, OK_STATUS, OK_RUNS, OK_SUPA, {"status": 402, "reason": "exceed_db_size_quota"})
    assert keys(inc) == ["supabase-api"]
    assert "HTTP 402: exceed_db_size_quota" in inc[0]["detail"] and "resetting passwords will not help" in inc[0]["detail"]
    assert keys(H.evaluate(NOW, OK_STATUS, OK_RUNS, OK_SUPA, {"status": None})) == ["supabase-api"]
    assert H.evaluate(NOW, OK_STATUS, OK_RUNS, OK_SUPA, None) == []          # no probe = old behaviour


# ------------------------------------------------------------------ storage, audit growth, egress (Phase 4, 2026-11-24)
MB = 1_000_000


def _storage(db_mb, audit_mb=12.0, audit_share=0.4, other_share=0.0):
    return {"db_bytes": int(db_mb * MB), "storage_bytes": 0, "storage_objects": 0,
            "tables": [{"name": "odds.potd_model_outputs", "bytes": int(audit_mb * MB), "share_7d": audit_share},
                       {"name": "odds.reports", "bytes": int(60 * MB), "share_7d": other_share},
                       {"name": "public.config", "bytes": 10_000, "share_7d": None}]}


def test_growth_and_forecast():
    g = H.growth(_storage(130, audit_mb=70, audit_share=0.7))   # 70 MB × 0.7 / 7 = 7 MB a day
    assert round(g["per_day"] / MB, 3) == 7.0 and round(g["audit_per_day"] / MB, 3) == 7.0
    assert round(g["days_to_limit"]) == round((500 - 130) / 7)
    assert H.growth({"db_bytes": 100 * MB, "tables": []})["days_to_limit"] is None      # nothing growing: no forecast


def test_small_quiet_database_raises_nothing():
    assert H.evaluate_storage(_storage(130, audit_mb=12, audit_share=0.1), {"bytes_24h": 50 * MB, "runs_counted": 8}) == []


def test_size_threshold_and_forecast_alerts():
    assert [i["key"] for i in H.evaluate_storage(_storage(360, audit_share=0.0), None)] == ["supabase-db-size"]   # 72 %
    # 130 MB but growing 15 MB a day: limit in ~25 days
    inc = H.evaluate_storage(_storage(130, audit_mb=105, audit_share=1.0), None)
    assert [i["key"] for i in inc] == ["supabase-db-size", "supabase-audit-growth"]
    assert "about 25 days" in inc[0]["detail"] and "odds.potd_model_outputs" in inc[0]["detail"]


def test_audit_growth_threshold():
    assert H.evaluate_storage(_storage(130, audit_mb=35, audit_share=1.0), None) == []                    # 5.0 MB/day: not over
    assert [i["key"] for i in H.evaluate_storage(_storage(130, audit_mb=42, audit_share=1.0), None)] == ["supabase-audit-growth"]


def test_egress_projection():
    assert H.evaluate_storage(None, {"bytes_24h": 99 * MB, "runs_counted": 9}) == []                      # 2.97 GB/month
    inc = H.evaluate_storage(None, {"bytes_24h": 101 * MB, "runs_counted": 9})
    assert [i["key"] for i in inc] == ["supabase-egress"] and "3.0 GB a month" in inc[0]["detail"]


def test_missing_inputs_are_not_incidents_but_show_in_summary():
    assert H.evaluate_storage(None, None) == [] and H.evaluate_storage({"ok": False, "error": "x"}, {}) == []
    assert "not read (x)" in H.storage_summary({"ok": False, "error": "x"}, None)
    s = H.storage_summary(_storage(130), {"bytes_24h": 40 * MB, "runs": 10, "runs_counted": 9})
    assert "130.0 MB of 500 MB (26%)" in s and "Growth by table" in s and "odds.potd_model_outputs" in s and "40.0 MB over 9 of 10" in s
