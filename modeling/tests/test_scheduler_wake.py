"""The refresh scheduler only starts a GitHub Actions run when a slot is due, and never goes quiet.

Two halves: the planner's `next_check` (pure Python), and the Postgres gate from
supabase/migrations/20261113000100_scheduler_wake.sql, applied to a scratch database with stand-ins for the
Supabase pieces (pg_net, Vault, private.app_settings) that cannot run locally.
"""
import json
import os
import re
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from modelroom import refresh_plan as R

PG = os.environ.get("MODELROOM_TEST_PG", "")
MIGRATION = Path(__file__).resolve().parents[2] / "supabase/migrations/20261113000100_scheduler_wake.sql"

STANDINS = """
create schema if not exists private;
create table if not exists private.app_settings (key text primary key, value text);
create schema if not exists vault;
create table if not exists vault.secrets (name text primary key);
create or replace view vault.decrypted_secrets as select name, 'test-token' as decrypted_secret from vault.secrets;
create schema if not exists net;
create sequence if not exists net.req_seq;
create table if not exists net._http_response (id bigint, status_code int, content text, error_msg text);
create or replace function net.http_post(url text, body jsonb default null, params jsonb default null,
                                         headers jsonb default null, timeout_milliseconds int default 5000)
  returns bigint language sql as $f$ select nextval('net.req_seq') $f$;
create schema if not exists scheduler;
create table if not exists scheduler.dispatch_log (
  id bigserial primary key, requested_at timestamptz not null default now(), request_id bigint,
  status_code integer, response text, error text, checked_at timestamptz);
"""


# ------------------------------------------------------------------ the planner
def _plan(tmp_path, monkeypatch, log_rows=(), games=()):
    monkeypatch.setattr(R, "LOG", tmp_path / "refresh_log.jsonl")
    monkeypatch.setattr(R, "PUBLISHED", tmp_path)
    R.LOG.write_text("".join(json.dumps(r) + "\n" for r in log_rows))
    (tmp_path / "nba.json").write_text(json.dumps({"upcoming": [{"start_time": t, "status": "scheduled"} for t in games]}))
    (tmp_path / "nfl.json").write_text(json.dumps({"upcoming": []}))


def test_next_check_waits_for_the_next_slot(tmp_path, monkeypatch):
    # 9:30 PT on a day whose three daily slots have all succeeded, one game at 19:00 PT tomorrow.
    now = datetime(2026, 11, 13, 17, 30, tzinfo=UTC)  # 09:30 PT
    done = [{"slot": f"{k}:2026-11-12", "status": "success"} for k in ("morning", "midday", "afternoon")]
    done += [{"slot": "morning:2026-11-13", "status": "success"}]
    _plan(tmp_path, monkeypatch, done, games=["2026-11-14T03:00:00+00:00"])
    at, why = R.next_check(now)
    assert at == datetime(2026, 11, 13, 20, 0, tzinfo=UTC)  # midday 12:00 PT, the next slot
    assert "midday:2026-11-13" in why
    # Nothing is dispatched before then: the scheduler sleeps through 2.5 hours it used to spend waking up.
    assert at - now == timedelta(hours=2, minutes=30)


def test_a_slot_still_due_asks_for_a_retry(tmp_path, monkeypatch):
    now = datetime(2026, 11, 13, 16, 0, tzinfo=UTC)  # 08:00 PT, inside the 07:00 window
    _plan(tmp_path, monkeypatch, [{"slot": "morning:2026-11-13", "status": "failed"}])
    at, why = R.next_check(now)
    assert at == now + timedelta(minutes=10) and "retry" in why and "morning:2026-11-13" in why


def test_never_sleeps_longer_than_four_hours(tmp_path, monkeypatch):
    now = datetime(2026, 11, 13, 7, 0, tzinfo=UTC)  # 23:00 PT, next slot is 07:00 PT, 8 hours away
    done = [{"slot": f"{k}:2026-11-12", "status": "success"} for k in ("morning", "midday", "afternoon")]
    _plan(tmp_path, monkeypatch, done)
    at, why = R.next_check(now)
    assert at == now + R.MAX_SLEEP and "maximum" in why
    assert at > now  # never in the past, whatever the state


def test_pregame_slot_is_the_next_wake(tmp_path, monkeypatch):
    now = datetime(2026, 11, 13, 21, 0, tzinfo=UTC)  # 13:00 PT
    done = [{"slot": f"{k}:2026-11-13", "status": "success"} for k in ("morning", "midday")]
    _plan(tmp_path, monkeypatch, done, games=["2026-11-13T23:00:00+00:00"])
    at, why = R.next_check(now)
    assert at == datetime(2026, 11, 13, 22, 30, tzinfo=UTC)  # start − 30 min, before the 16:00 PT daily slot
    assert "pregame:nba" in why


def test_missed_slots_stop_being_reported_once_they_are_old(tmp_path, monkeypatch):
    """A game slot that failed days ago can never be refreshed now, so it must drop out of `missed` and let the
    health alert close. Six such slots from 2026-11-08 were keeping the missed-slots alert permanently open."""
    now = datetime(2026, 11, 13, 17, 30, tzinfo=UTC)
    rows = [{"slot": f"{k}:2026-11-12", "status": "success", "at": "2026-11-12T15:00:00+00:00"} for k in ("morning", "midday", "afternoon")]
    rows += [{"slot": f"{k}:2026-11-13", "status": "success", "at": "2026-11-13T15:00:00+00:00"} for k in ("morning",)]
    rows += [{"slot": "pregame:nba:2026-11-08T20:30:00+00:00", "status": "failed", "at": "2026-11-08T20:30:00+00:00"},
             {"slot": "pregame:nfl:2026-11-12T20:30:00+00:00", "status": "failed", "at": "2026-11-12T20:30:00+00:00"}]
    _plan(tmp_path, monkeypatch, rows)
    missed = R.status(now)["missed"]
    assert "pregame:nfl:2026-11-12T20:30:00+00:00" in missed      # yesterday: still actionable, still reported
    assert "pregame:nba:2026-11-08T20:30:00+00:00" not in missed  # five days ago: gone, so the alert can clear


# ------------------------------------------------------------------ the Postgres gate
@pytest.fixture
def db():
    if not PG:
        pytest.skip("MODELROOM_TEST_PG not set")
    import psycopg
    name = "mr_sched_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"create database {name}")
    url = re.sub(r"dbname=\S+", f"dbname={name}", PG) if "dbname=" in PG else PG + f" dbname={name}"
    c = psycopg.connect(url, autocommit=True)
    c.execute(STANDINS)
    c.execute(MIGRATION.read_text())
    c.execute("insert into private.app_settings values ('refresh_scheduler', 'on')")
    c.execute("insert into vault.secrets values ('model_room_github_dispatch')")
    yield c
    c.close()
    admin.execute(f"drop database {name} with (force)")
    admin.close()


def dispatches(c) -> int:
    return c.execute("select count(*) from scheduler.dispatch_log where request_id is not null").fetchone()[0]


def plan_row(c) -> dict:
    cols = "next_check_at, reason, updated_at, dispatches_since_update"
    r = c.execute(f"select {cols} from scheduler.plan where id").fetchone()
    return dict(zip(cols.replace(" ", "").split(","), r))


def test_the_owner_dashboard_keeps_its_read_on_the_health_view(db):
    """The migration drops and recreates scheduler.health, which loses its grants, so it re-grants them. The owner
    dashboard reads that view as owner_reader and would show nothing without this."""
    db.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 'owner_reader') "
               "then create role owner_reader; end if; end $$")
    db.execute("revoke all on scheduler.health from owner_reader")
    assert not db.execute("select has_table_privilege('owner_reader', 'scheduler.health', 'select')").fetchone()[0]
    db.execute(MIGRATION.read_text())  # idempotent; this time the role exists
    assert db.execute("select has_table_privilege('owner_reader', 'scheduler.health', 'select')").fetchone()[0]
    # and only select: the dashboard can never change the wake plan
    for priv in ("insert", "update", "delete"):
        assert not db.execute(f"select has_table_privilege('owner_reader', 'scheduler.health', '{priv}')").fetchone()[0]
    assert not db.execute("select has_table_privilege('owner_reader', 'scheduler.plan', 'select')").fetchone()[0]


def test_the_refresh_script_records_the_next_check(db):
    """The step every refresh ends with. It runs the real script against the real function, because the failure
    mode here is in the plumbing, not the logic: psql does not interpolate :'var' into a -c string."""
    repo = Path(__file__).resolve().parents[2]
    env = {**os.environ, "MODELROOM_ODDS_DB_URL": db.info.dsn, "GITHUB_RUN_ID": "test-run-42"}
    p = subprocess.run(["bash", "scripts/scheduler-next.sh"], cwd=repo, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "next check" in p.stdout and "could not" not in p.stdout, p.stdout
    at, why, by = db.execute("select next_check_at, reason, updated_by from scheduler.plan where id").fetchone()
    assert by == "test-run-42" and at > datetime.now(UTC) - timedelta(minutes=1) and why
    # The script never fails a refresh, whatever the database does.
    broken = {**os.environ, "MODELROOM_ODDS_DB_URL": "host=127.0.0.1 port=1 dbname=nope", "SUPABASE_DB_URL": ""}
    q = subprocess.run(["bash", "scripts/scheduler-next.sh"], cwd=repo, env=broken, capture_output=True, text=True)
    assert q.returncode == 0 and "safety nets apply" in q.stdout, q.stdout


def test_dispatch_only_when_the_wake_time_has_arrived(db):
    assert dispatches(db) == 0
    db.execute("select scheduler.dispatch_refresh()")
    assert dispatches(db) == 1  # the migration leaves the plan due, so the first tick goes out
    p = plan_row(db)
    assert p["dispatches_since_update"] == 1
    assert p["next_check_at"] > datetime.now(UTC) + timedelta(minutes=10)  # 15-minute lease

    # A run reports: the next slot is two hours away. Every tick until then is free.
    db.execute("select scheduler.set_next_check(now() + interval '2 hours', 'next slot midday:2026-11-13', 'run-1')")
    assert plan_row(db)["dispatches_since_update"] == 0
    for _ in range(5):
        db.execute("select scheduler.dispatch_refresh()")
    assert dispatches(db) == 1

    # Once it arrives, one dispatch goes out and the lease stops the next tick repeating it.
    db.execute("update scheduler.dispatch_log set requested_at = requested_at - interval '10 minutes'")  # past the 4-min guard
    db.execute("update scheduler.plan set next_check_at = now() - interval '1 minute'")
    db.execute("select scheduler.dispatch_refresh()")
    assert dispatches(db) == 2
    db.execute("update scheduler.dispatch_log set requested_at = requested_at - interval '10 minutes'")
    db.execute("select scheduler.dispatch_refresh()")
    assert dispatches(db) == 2, "the lease must hold the scheduler off while the run works"


def test_switched_off_dispatches_nothing(db):
    db.execute("update private.app_settings set value = 'off' where key = 'refresh_scheduler'")
    db.execute("select scheduler.dispatch_refresh()")
    assert dispatches(db) == 0


def test_a_plan_nobody_updates_still_wakes_the_scheduler(db):
    # Worst case: a wake time far in the future and no run reporting back. It must not go quiet.
    db.execute("""update scheduler.plan set next_check_at = now() + interval '5 hours',
                         updated_at = now() - interval '7 hours'""")
    db.execute("select scheduler.dispatch_refresh()")
    assert dispatches(db) == 1


def test_runs_that_never_report_slow_the_scheduler_down_but_do_not_stop_it(db):
    db.execute("update scheduler.plan set dispatches_since_update = 12")
    db.execute("select scheduler.dispatch_refresh()")
    assert dispatches(db) == 1
    p = plan_row(db)
    assert p["dispatches_since_update"] == 13
    assert p["next_check_at"] > datetime.now(UTC) + timedelta(minutes=25)  # 30-minute lease, not 15
    note = db.execute("select error from scheduler.dispatch_log where error like 'no run has reported%'").fetchone()
    assert note, "the daily health check needs a note it can alert on"


def test_set_next_check_clamps_absurd_values(db):
    far = db.execute("select scheduler.set_next_check(now() + interval '3 days', 'way off', 'run-x')").fetchone()[0]
    assert far < datetime.now(UTC) + timedelta(hours=6, minutes=1)
    past = db.execute("select scheduler.set_next_check(now() - interval '2 days', 'in the past', 'run-x')").fetchone()[0]
    assert past >= datetime.now(UTC) - timedelta(seconds=5)  # never leaves the scheduler dispatching in a loop


def test_health_view_reports_the_wake_plan(db):
    # A wake time that arrived 45 minutes ago and no dispatch: what the daily health check alerts on.
    db.execute("select scheduler.set_next_check(now(), 'overdue', 'run-9')")
    db.execute("update scheduler.plan set next_check_at = now() - interval '45 minutes'")
    h = db.execute("select row_to_json(h) from scheduler.health h").fetchone()[0]
    assert h["enabled"] == "on" and h["token_stored"] is True
    assert h["minutes_overdue"] >= 44 and h["plan_stale"] is False
    assert h["next_check_reason"] == "overdue" and h["plan_updated_by"] == "run-9"


# ------------------------------------------------------------------ the two schedulers, side by side
def _run_week(tmp_path, monkeypatch, label, new_scheduler: bool):
    """Replay a week on a 5-minute grid: an NBA game most evenings and an NFL Sunday.
    Returns (slots successfully refreshed, GitHub Actions runs started)."""
    start = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)  # Mon 00:00 PT
    end = start + timedelta(days=7)
    nba, nfl = [], []
    for d in range(8):
        day = start + timedelta(days=d)
        for h in (3, 3.5, 4):  # 19:00, 19:30, 20:00 PT, the evening cluster
            nba.append((day + timedelta(hours=19 + h)).isoformat())
        if (day.astimezone(UTC).weekday()) == 6:  # Sunday: three kickoff times
            nfl += [(day + timedelta(hours=18)).isoformat(), (day + timedelta(hours=21, minutes=5)).isoformat(),
                    (day + timedelta(hours=25, minutes=20)).isoformat()]
    home = tmp_path / label
    home.mkdir()
    monkeypatch.setattr(R, "LOG", home / "refresh_log.jsonl")
    monkeypatch.setattr(R, "PUBLISHED", home)
    (home / "nba.json").write_text(json.dumps({"upcoming": [{"start_time": t, "status": "scheduled"} for t in nba]}))
    (home / "nfl.json").write_text(json.dumps({"upcoming": [{"start_time": t, "status": "scheduled"} for t in nfl]}))
    R.LOG.write_text("")
    runs, t = 0, start
    next_check, reported_at = start, start
    while t < end:
        wake = (not new_scheduler) or t >= next_check or reported_at <= t - timedelta(hours=6)
        if wake:
            runs += 1  # one dispatch = one GitHub Actions run
            d = R.due(t)
            if d:
                R.record([s["id"] for s in d], "success", note=label, now=t)
            if new_scheduler:
                next_check, _ = R.next_check(t)
                reported_at = t
        t += timedelta(minutes=5)
    return {r["slot"] for r in R.log_entries() if r["status"] == "success"}, runs


def test_the_same_slots_are_covered_with_far_fewer_runs(tmp_path, monkeypatch):
    old_slots, old_runs = _run_week(tmp_path, monkeypatch, "old", new_scheduler=False)
    new_slots, new_runs = _run_week(tmp_path, monkeypatch, "new", new_scheduler=True)
    assert new_slots == old_slots, f"coverage changed: {old_slots ^ new_slots}"
    assert len(new_slots) >= 7 * 3, "the three daily slots must run every day"
    assert {s.split(":")[0] for s in new_slots} == {"morning", "midday", "afternoon", "pregame", "inactives"}
    assert old_runs == 7 * 24 * 12  # every 5 minutes, all week
    assert new_runs < old_runs / 10, f"{new_runs} runs vs {old_runs}"
    print(f"\na week: {len(new_slots)} slots covered by both; runs {old_runs} -> {new_runs} "
          f"({new_runs / 7:.1f} a day, {100 - new_runs / old_runs * 100:.1f}% fewer)")
