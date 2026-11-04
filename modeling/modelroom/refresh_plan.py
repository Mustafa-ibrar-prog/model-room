"""Refresh planner: decides whether a data refresh is due right now, and which one.

    python -m modelroom.refresh_plan due     [--now ISO]  → prints JSON; with GITHUB_OUTPUT set, writes run=, slots=, kind=
    python -m modelroom.refresh_plan record  --slots a,b --status success|failed [--note ...]

Standard library only, so the scheduler's every-few-minutes check runs in seconds without installing anything.

Slots (all Pacific time):
  morning   07:00 PT every day             injury reports, questionable / doubtful / out, depth charts
  midday    12:00 PT every day             updated designations, lineup changes
  inactives kickoff − 90 min, each NFL kickoff time   official NFL inactive lists (when a source is connected)
  pregame   start − 30 min, each game start time (NFL and NBA)   late scratches, confirmed lineups

A slot is due from its time until its window closes (morning / midday: 3 hours; inactives: until the pregame
slot; pregame: until the game starts). Games sharing a start time share one slot. A slot that succeeded is
never run again (no duplicate refreshes); a failed one is retried on the next check while its window is open.
Every attempt is appended to modeling/preview-ledger/refresh_log.jsonl (append-only; nothing is rewritten).
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parents[1]
LOG = Path(os.environ.get("MODELROOM_LEDGER_DIR", ROOT / "preview-ledger")) / "refresh_log.jsonl"
PUBLISHED = ROOT / "data" / "published"
DAILY = (("morning", 7, 0), ("midday", 12, 0))
DAILY_WINDOW = timedelta(hours=3)
INACTIVES_BEFORE = timedelta(minutes=90)
PREGAME_BEFORE = timedelta(minutes=30)


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


def slots(now: datetime) -> list[dict]:
    """Every slot whose window contains `now`."""
    local = now.astimezone(PT)
    out = []
    for day in (local.date() - timedelta(days=1), local.date()):
        for name, h, m in DAILY:
            at = datetime(day.year, day.month, day.day, h, m, tzinfo=PT).astimezone(timezone.utc)
            out.append({"id": f"{name}:{day.isoformat()}", "kind": name, "at": at, "until": at + DAILY_WINDOW})
    starts = upcoming_starts(now)
    for lg, ts in starts.items():
        for t in ts:
            if lg == "nfl":
                out.append({"id": f"inactives:nfl:{t.isoformat()}", "kind": "inactives", "at": t - INACTIVES_BEFORE, "until": t - PREGAME_BEFORE})
            out.append({"id": f"pregame:{lg}:{t.isoformat()}", "kind": "pregame", "at": t - PREGAME_BEFORE, "until": t})
    return [s for s in out if s["at"] <= now < s["until"]]


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


def record(slot_ids: list[str], status: str, note: str | None = None, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        for s in slot_ids:
            if s:
                f.write(json.dumps({"slot": s, "status": status, "at": now.isoformat(timespec="seconds"), "note": note}) + "\n")


def status(now: datetime | None = None) -> dict:
    """Latest successful refresh and recent failures, for the site."""
    rows = log_entries()
    ok = [r for r in rows if r.get("status") == "success"]
    bad = [r for r in rows if r.get("status") == "failed"][-10:]
    return {"last_success": ok[-1] if ok else None, "recent_failures": bad, "schedule": "07:00 PT, 12:00 PT, NFL kickoff − 90 min, every game − 30 min"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["due", "record", "status"])
    ap.add_argument("--now")
    ap.add_argument("--slots", default="")
    ap.add_argument("--status", default="success", choices=["success", "failed"])
    ap.add_argument("--note")
    a = ap.parse_args(argv)
    now = _ts(a.now) if a.now else datetime.now(timezone.utc)
    if a.cmd == "record":
        record(a.slots.split(","), a.status, a.note, now)
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
