"""Refresh planner: decides whether a data refresh is due right now, and which one.

    python -m modelroom.refresh_plan due     [--now ISO]  → prints JSON; with GITHUB_OUTPUT set, writes run=, slots=, kind=
    python -m modelroom.refresh_plan next    [--now ISO]  → when the scheduler should next ask (JSON: at, reason)
    python -m modelroom.refresh_plan record  --slots a,b --status success|failed [--note ...]

Standard library only, so the scheduler's every-few-minutes check runs in seconds without installing anything.

Slots (all Pacific time):
  morning   07:00 PT every day             injury reports, questionable / doubtful / out, depth charts
  midday    12:00 PT every day             updated designations, lineup changes
  afternoon 16:00 PT every day             late reports before evening games
  inactives kickoff − 90 min, each NFL kickoff time   official NFL inactive lists (when a source is connected)
  pregame   start − 30 min, each game start time (NFL and NBA)   late scratches, confirmed lineups

A slot is due from its time until its window closes (morning / midday / afternoon: 3 hours; inactives: until the pregame
slot; pregame: until the game starts). Games sharing a start time share one slot. A slot that succeeded is
never run again (no duplicate refreshes); a failed one is retried on the next check while its window is open.
Every attempt is appended to modeling/preview-ledger/refresh_log.jsonl (append-only; nothing is rewritten).

`next` is what keeps the scheduler cheap: Supabase only dispatches a workflow once this time has arrived
(supabase/migrations/20261113000100_scheduler_wake.sql), instead of starting one every 5 minutes to ask. The slot
rules below stay the only source of truth; SQL never computes a slot time.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parents[1]
LOG = Path(os.environ.get("MODELROOM_LEDGER_DIR", ROOT / "preview-ledger")) / "refresh_log.jsonl"
PUBLISHED = ROOT / "data" / "published"
DAILY = (("morning", 7, 0), ("midday", 12, 0), ("afternoon", 16, 0))
DAILY_WINDOW = timedelta(hours=3)
INACTIVES_BEFORE = timedelta(minutes=90)
PREGAME_BEFORE = timedelta(minutes=30)
# A slot that is due but has not succeeded is retried this often while its window is open.
RETRY_AFTER = timedelta(minutes=10)
# Never tell the scheduler to sleep longer than this, however far off the next slot looks: a game added to the
# schedule after this run would otherwise be missed.
MAX_SLEEP = timedelta(hours=4)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def upcoming_starts(now: datetime) -> dict[str, set[datetime]]:
    """{league: start times} of scheduled games in the next 36 hours, from the published boards."""
    out: dict[str, set[datetime]] = {"nfl": set(), "nba": set()}
    for lg in out:
        f = PUBLISHED / f"{lg}.json"
        if not f.exists():
            continue
        try:
            games = json.loads(f.read_text()).get("upcoming") or []
        except (OSError, ValueError):
            continue
        for g in games:
            st = g.get("start_time")
            if not st or g.get("status") not in (None, "scheduled"):
                continue
            t = _ts(st)
            if now - timedelta(hours=1) <= t <= now + timedelta(hours=36):
                out[lg].add(t)
    return out


def recent_starts(now: datetime, hours: float = 36) -> dict[str, set[datetime]]:
    """{league: start times} of games that started in the last `hours` (published boards, upcoming + recent)."""
    out: dict[str, set[datetime]] = {"nfl": set(), "nba": set()}
    for lg in out:
        f = PUBLISHED / f"{lg}.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for g in (d.get("upcoming") or []) + (d.get("recent") or []):
            st = g.get("start_time")
            if st and now - timedelta(hours=hours) <= _ts(st) <= now:
                out[lg].add(_ts(st))
    return out


def all_slots(now: datetime) -> list[dict]:
    """Every slot around `now`: the daily ones for yesterday, today and tomorrow, and one per game start time
    on the published boards (which reach 36 hours ahead)."""
    local = now.astimezone(PT)
    out = []
    for day in (local.date() - timedelta(days=1), local.date(), local.date() + timedelta(days=1)):
        for name, h, m in DAILY:
            at = datetime(day.year, day.month, day.day, h, m, tzinfo=PT).astimezone(UTC)
            out.append({"id": f"{name}:{day.isoformat()}", "kind": name, "at": at, "until": at + DAILY_WINDOW})
    starts = upcoming_starts(now)
    for lg, ts in starts.items():
        for t in ts:
            if lg == "nfl":
                out.append({"id": f"inactives:nfl:{t.isoformat()}", "kind": "inactives", "at": t - INACTIVES_BEFORE, "until": t - PREGAME_BEFORE})
            out.append({"id": f"pregame:{lg}:{t.isoformat()}", "kind": "pregame", "at": t - PREGAME_BEFORE, "until": t})
    return out


def slots(now: datetime) -> list[dict]:
    """Every slot whose window contains `now`."""
    return [s for s in all_slots(now) if s["at"] <= now < s["until"]]


def log_entries() -> list[dict]:
    if not LOG.exists():
        return []
    rows = []
    for line in LOG.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def due(now: datetime) -> list[dict]:
    done = {r["slot"] for r in log_entries() if r.get("status") == "success"}
    return sorted((s for s in slots(now) if s["id"] not in done), key=lambda s: s["at"])


def next_check(now: datetime) -> tuple[datetime, str]:
    """When the scheduler should next ask whether a refresh is due, and why.

    Something still due now  → a short retry, so a failed slot is tried again while its window is open.
    Nothing due              → the start of the next slot that has not succeeded, never more than MAX_SLEEP away.
    Earlier than `now` is never returned, so the scheduler cannot be put into a dispatch loop."""
    d = due(now)
    if d:
        return now + RETRY_AFTER, "retry: " + ",".join(s["id"] for s in d[:4])
    done = {r["slot"] for r in log_entries() if r.get("status") == "success"}
    ahead = sorted((s for s in all_slots(now) if s["at"] > now and s["id"] not in done), key=lambda s: s["at"])
    if not ahead:
        return now + MAX_SLEEP, "no slot ahead on the boards; sleeping the maximum"
    nxt = ahead[0]
    if nxt["at"] <= now + MAX_SLEEP:
        return nxt["at"], f"next slot {nxt['id']}"
    return now + MAX_SLEEP, f"sleeping the maximum; next slot {nxt['id']} at {nxt['at'].isoformat(timespec='minutes')}"


def record(slot_ids: list[str], status: str, note: str | None = None, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        for s in slot_ids:
            if s:
                f.write(json.dumps({"slot": s, "status": status, "at": now.isoformat(timespec="seconds"), "note": note}) + "\n")


def pending(slot_ids: list[str]) -> list[str]:
    """The given slots that have not succeeded yet (a queued run re-checks before refreshing: no duplicates)."""
    done = {r["slot"] for r in log_entries() if r.get("status") == "success"}
    return [s for s in slot_ids if s and s not in done]


def status(now: datetime | None = None) -> dict:
    """For the site: the latest success, the latest success of each kind, recent failures, and missed slots
    (a daily slot whose window closed without a successful run in the last two days, or a game slot that
    only ever failed)."""
    now = now or datetime.now(UTC)
    rows = log_entries()
    ok = [r for r in rows if r.get("status") == "success"]
    bad = [r for r in rows if r.get("status") == "failed"][-10:]
    done = {r["slot"] for r in ok}
    by_kind = {}
    for r in ok:
        by_kind[r["slot"].split(":")[0]] = r
    missed = []
    local = now.astimezone(PT)
    for day in (local.date() - timedelta(days=1), local.date()):
        for name, h, m in DAILY:
            at = datetime(day.year, day.month, day.day, h, m, tzinfo=PT).astimezone(UTC)
            sid = f"{name}:{day.isoformat()}"
            if at + DAILY_WINDOW <= now and sid not in done:
                missed.append(sid)
    # Game slots come from the games' start times, so a pregame refresh that never started still counts as
    # missed (not only ones that were attempted and failed).
    for lg, ts in recent_starts(now).items():
        for t in sorted(ts):
            if lg == "nfl" and f"inactives:nfl:{t.isoformat()}" not in done and t - PREGAME_BEFORE <= now:
                missed.append(f"inactives:nfl:{t.isoformat()}")
            if f"pregame:{lg}:{t.isoformat()}" not in done:
                missed.append(f"pregame:{lg}:{t.isoformat()}")
    for r in rows:
        sl = r.get("slot", "")
        if sl.startswith(("pregame:", "inactives:")) and sl not in done and sl not in missed:
            try:
                if _ts(sl.split(":", 2)[2]) <= now:
                    missed.append(sl)
            except ValueError:
                pass
    return {"last_success": ok[-1] if ok else None, "last_success_by_kind": by_kind, "recent_failures": bad, "missed": missed[-20:],
            "schedule": "7:00 AM, 12:00 PM and 4:00 PM PT, NFL kickoff − 90 min, every game − 30 min",
            "next_check": next_check(now)[0].isoformat(timespec="seconds"),
            "triggers": "Supabase wakes a run only when a slot is due (pg_cron checks every 5 min inside Postgres); "
                        "GitHub's own schedule every 6 hours is the backup"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["due", "next", "record", "status", "pending"])
    ap.add_argument("--now")
    ap.add_argument("--slots", default="")
    ap.add_argument("--status", default="success", choices=["success", "failed"])
    ap.add_argument("--note")
    a = ap.parse_args(argv)
    now = _ts(a.now) if a.now else datetime.now(UTC)
    if a.cmd == "record":
        record(a.slots.split(","), a.status, a.note, now)
        return 0
    if a.cmd == "pending":
        left = pending(a.slots.split(","))
        print(json.dumps({"pending": left}))
        gh = os.environ.get("GITHUB_OUTPUT")
        if gh:
            with open(gh, "a") as f:
                f.write(f"pending={','.join(left)}\n")
        return 0
    if a.cmd == "next":
        at, why = next_check(now)
        print(json.dumps({"at": at.isoformat(timespec="seconds"), "reason": why}))
        gh = os.environ.get("GITHUB_OUTPUT")
        if gh:
            with open(gh, "a") as f:
                f.write(f"next_check={at.isoformat(timespec='seconds')}\nnext_reason={why}\n")
        return 0
    if a.cmd == "status":
        print(json.dumps(status(now), indent=1, default=str))
        return 0
    d = due(now)
    kinds = sorted({s["kind"] for s in d})
    out = {"run": bool(d), "slots": [s["id"] for s in d], "kinds": kinds}
    print(json.dumps(out))
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"run={'yes' if d else 'no'}\nslots={','.join(out['slots'])}\nkinds={','.join(kinds)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
