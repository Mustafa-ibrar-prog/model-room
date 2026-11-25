"""NBA player points lines from The Odds API, one request per game per day, stored in private R2 (TEST; Moose,
approved 2026-11-24). No Supabase. Never estimates a line; the model never reads these.

Request: GET /v4/sports/basketball_nba/events/{event_id}/odds?regions=us&markets=player_points
  cost = markets returned x regions = 1 credit (0 when the book hasn't posted the market). The events list is free.

Schedule (Moose, 2026-11-25): 5:30 AM PT main run (every game today not yet requested) and a 9:30 AM PT retry ONLY
for games whose single paid request came back with no player points. Each mode runs once a day (write-once R2 lock;
a completed mode is never repeated), and every paid request leaves a write-once attempt marker before anything else,
so duplicate triggers can never pay twice for a game.

Credit rules (Moose, 2026-11-24): game lines (NBA + NFL, 7 AM and noon PT) always come first. Their reserve is
GAME_LINES_PER_DAY x the game-line days left in the credit cycle (360 a month = 12 a day), plus a SAFETY margin of 30.
Props may use only what is above that, spread evenly over the days left in the cycle, at most MAX_PER_DAY a day:

  allowance today = min(MAX_PER_DAY, floor((remaining + billed earlier today - reserve) / days left incl. today))
                    - billed earlier today

remaining is the live x-requests-remaining from the provider (the free events call), so the budget follows actual
usage. Before EVERY request: remaining - 1 must stay >= reserve and >= FLOOR, else the run stops. A response costing
more than 1 credit, or one with no credit headers, stops the run at once. Nothing is ever bought or upgraded.

Output in logs: counts only. No prices, lines, sportsbook names or player-line pairs (the repository is public).
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from modelroom.archive import market_snapshots as MS
from modelroom.archive.store import sha256
from modelroom.markets import prop_matching as PM

PT = ZoneInfo("America/Los_Angeles")
BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
GAME_LINES_PER_DAY = 12          # 360 a month reserved for the existing NBA + NFL game-line fetches
SAFETY = 30
FLOOR = 15                       # the game-line client's own minimum (sources/odds.py MIN_CREDITS)
MAX_PER_DAY = 15
START_BUFFER = timedelta(minutes=10)


class StopRun(RuntimeError):
    pass


def scrub(text: str, key: str | None) -> str:
    return text.replace(key, "***") if key else text


# ------------------------------------------------------------------ budget
def cycle_reset(today: date, reset_day: int) -> date:
    """The next credit reset date (day of month) after today."""
    d = min(reset_day, 28)
    if today.day < d:
        return today.replace(day=d)
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return date(y, m, d)


def budget(remaining: int, today: date, reset_day: int, lines_done_today: bool, billed_today: int) -> dict:
    days_left = max((cycle_reset(today, reset_day) - today).days, 1)                    # includes today
    line_days = days_left - (1 if lines_done_today else 0)
    reserve = GAME_LINES_PER_DAY * line_days + SAFETY
    day_total = max(0, math.floor((remaining + billed_today - reserve) / days_left))
    allowance = max(0, min(MAX_PER_DAY, day_total) - billed_today)
    return {"remaining": remaining, "reserve": reserve, "days_left": days_left, "reset": cycle_reset(today, reset_day).isoformat(),
            "billed_today": billed_today, "allowance": allowance}


def may_request(remaining: int, reserve: int) -> bool:
    return remaining - 1 >= reserve and remaining - 1 >= FLOOR


# ------------------------------------------------------------------ HTTP
def _http(url: str, key: str) -> tuple[dict, dict]:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ModelRoom/0.1"}), timeout=30) as r:
        body = r.read()
        hdr = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-requests") or k.lower() == "retry-after"}
    return {"body": body, "headers": hdr}, hdr


def get(url: str, key: str, http=_http, sleep=time.sleep) -> dict:
    """401/403 stop the run; 429 waits Retry-After (60 s max) once; 5xx and timeouts retry once after 30 s."""
    for attempt in (1, 2):
        try:
            res, _ = http(url, key)
            return res
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise StopRun(f"provider refused the key or plan (HTTP {e.code})") from None
            if e.code == 429 and attempt == 1:
                sleep(min(60, int(float(e.headers.get("Retry-After", "30") or 30))))
                continue
            if e.code >= 500 and attempt == 1:
                sleep(30)
                continue
            raise RuntimeError(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 1:
                sleep(30)
                continue
            raise RuntimeError(scrub(type(e).__name__, key)) from None
    raise RuntimeError("no response")


def _credits(h: dict) -> tuple[int, int]:
    if "x-requests-remaining" not in h or "x-requests-last" not in h:
        raise StopRun("response had no credit headers: the cap can't be enforced")
    return int(float(h["x-requests-remaining"])), int(float(h["x-requests-last"]))


# ------------------------------------------------------------------ run
def today_events(events: list[dict], now: datetime) -> list[dict]:
    t = now.astimezone(PT).date()
    out = [e for e in events if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) > now + START_BUFFER
           and datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(PT).date() == t]
    return sorted(out, key=lambda e: (e["commence_time"], e["id"]))


def day_history(reader, day: str) -> dict:
    """What has been done today, from R2:
      - write-once attempt markers (one per PAID request, written before anything else): attempts per game, the
        newest outcome (captured | empty) and credits billed. They are the authority, so a run that died before its
        manifest still counts.
      - manifests: which modes completed, and games never requested (skipped_cap, error) so a later main run of the
        same day doesn't pick them up again."""
    status, attempts, billed, modes, newest = {}, {}, 0, set(), {}
    for k in reader.list(f"{MS.day_prefix(day)}/"):
        parts = k.rsplit("/", 2)
        if len(parts) == 3 and parts[2].startswith("attempt-") and parts[2].endswith(".json"):
            eid = parts[1]
            m = json.loads(reader.get(k))
            attempts[eid] = attempts.get(eid, 0) + 1
            billed += int(m.get("cost", 0))
            if parts[2] > newest.get(eid, ""):
                newest[eid] = parts[2]
                status[eid] = m["status"]
    latest = MS.read_latest(reader, day)
    key = latest["manifest"] if latest else None
    seen = set()
    while key and key not in seen:
        seen.add(key)
        m = json.loads(reader.get(key))
        modes.add(m.get("mode"))
        for r in m.get("requests", []):
            status.setdefault(r["event_id"], r["status"])
        key = m.get("prev_manifest")
    return {"status": status, "attempts": attempts, "billed": billed, "modes": modes}


LOCK_STALE = timedelta(minutes=30)        # the job times out at 15 minutes, so an older lock's run is gone
MAX_LOCKS = 3


def acquire_lock(store, reader, day: str, mode: str, now: datetime, run_ts: str) -> tuple[bool, str]:
    """A write-once lock per day and mode, so two triggers (scheduler + GitHub backup) can never run the same
    mode at the same time. A lock younger than 30 minutes means another run is active or just finished: skip. An
    older lock whose run never completed may be taken over, at most MAX_LOCKS times a day."""
    from modelroom.archive.store import ArchiveError
    for k in range(1, MAX_LOCKS + 1):
        lk = f"{MS.day_prefix(day)}/locks/{mode}-{k}.json"
        try:
            store.put_once(lk, json.dumps({"run_ts": run_ts, "at": now.isoformat(timespec="seconds")}).encode())
            return True, lk
        except ArchiveError:
            held = json.loads(reader.get(lk))
            if now - datetime.fromisoformat(held["at"]) < LOCK_STALE:
                return False, f"another {mode} run started at {held['at']} (lock {k})"
    return False, f"{mode} already attempted {MAX_LOCKS} times today"


def run(mode: str, key: str, board: dict, store, reader, now: datetime | None = None, reset_day: int = 10,
        lines_done_today: bool = False, aliases_path: Path | None = None, http=_http, sleep=time.sleep) -> dict:
    """mode 'main' (every game not yet requested today) or 'followup' (only games whose market was empty earlier)."""
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(PT).date()
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")       # unique per run, even within one second
    hist0 = day_history(reader, day.isoformat())
    if mode in hist0["modes"]:
        return {"mode": mode, "date": day.isoformat(), "skipped": f"{mode} run already completed today", "requested": 0}
    ok, why = acquire_lock(store, reader, day.isoformat(), mode, now, run_ts)
    if not ok:
        return {"mode": mode, "date": day.isoformat(), "skipped": why, "requested": 0}
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), PT).astimezone(timezone.utc)
    ev = get(f"{BASE}/events?apiKey={key}&dateFormat=iso&commenceTimeFrom={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
             f"&commenceTimeTo={end.strftime('%Y-%m-%dT%H:%M:%SZ')}", key, http, sleep)
    remaining, cost = _credits(ev["headers"])
    if cost != 0:
        raise StopRun(f"the events list cost {cost} credits (expected 0)")
    events = today_events(json.loads(ev["body"]), now)
    hist = day_history(reader, day.isoformat())
    b = budget(remaining, day, reset_day, False, hist["billed"])   # today's 12 game-line credits always held back
    if mode == "followup":                                          # retry ONLY games whose one paid attempt was empty
        todo = [e for e in events if hist["status"].get(e["id"]) == "empty" and hist["attempts"].get(e["id"], 0) == 1]
    else:
        todo = [e for e in events if e["id"] not in hist["status"]]
    aliases = PM.load_aliases(aliases_path)
    games = board.get("games") or []
    requests, objects, views = [], [], []
    billed, skipped_cap, stop = 0, 0, None
    for e in todo:
        if billed >= b["allowance"] or not may_request(remaining, b["reserve"]):
            skipped_cap += 1
            requests.append({"event_id": e["id"], "status": "skipped_cap"})
            continue
        try:
            res = get(f"{BASE}/events/{e['id']}/odds?apiKey={key}&regions=us&markets=player_points&oddsFormat=american&dateFormat=iso",
                      key, http, sleep)
            remaining, cost = _credits(res["headers"])
        except StopRun as s:
            stop = scrub(str(s), key)
            break
        except Exception as x:  # noqa: BLE001  one game failed: skip it today, keep going
            requests.append({"event_id": e["id"], "status": "error", "error": scrub(str(x), key)[:120]})
            continue
        billed += cost
        if cost > 1:
            stop = f"a request cost {cost} credits (cap is 1)"
        body = res["body"]
        data = json.loads(body)
        game = PM.match_game(e, games)
        n_out = sum(len(m.get("outcomes") or []) for bk in data.get("bookmakers") or [] for m in bk.get("markets") or [] if m.get("key") == "player_points")
        try:
            MS.put_verified(store, reader, f"{MS.day_prefix(day.isoformat())}/{e['id']}/attempt-{run_ts}.json",
                            json.dumps({"mode": mode, "status": "captured" if n_out else "empty", "cost": cost, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}).encode())
        except Exception:  # noqa: BLE001  can't record the attempt: stop before spending more
            stop = "could not record a request in R2: stopping before any further request"
        if n_out == 0:                                              # genuinely empty: no player points offered yet
            requests.append({"event_id": e["id"], "status": "empty", "cost": cost, "game_id": game["game_id"] if game else None})
            if stop:
                break
            continue
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cap = MS.stamp()
        base = f"{MS.day_prefix(day.isoformat())}/{e['id']}/{cap}"
        h = sha256(body)
        try:
            raw = MS.put_verified(store, reader, f"{base}.raw.json", body)
            rows = PM.rows_from_response(data, game, aliases, fetched, h)
            rbody = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
            rput = MS.put_verified(store, reader, f"{base}.rows.jsonl", rbody)
        except Exception as x:  # noqa: BLE001  credit spent, response discarded; never re-requested today
            requests.append({"event_id": e["id"], "status": "error", "cost": cost, "error": f"upload failed: {type(x).__name__}"})
            if stop:
                break
            continue
        objects += [{"key": raw["key"], "bytes": raw["bytes"], "sha256": raw["sha256"], "kind": "raw", "event_id": e["id"]},
                    {"key": rput["key"], "bytes": rput["bytes"], "sha256": rput["sha256"], "kind": "rows", "event_id": e["id"]}]
        views.append(PM.view_for_game(rows, game, fetched))
        requests.append({"event_id": e["id"], "status": "captured", "cost": cost, "game_id": game["game_id"] if game else None,
                         "books": len(data["bookmakers"]), "players": len({r["player_name"] for r in rows}),
                         "matched_players": len({r["player_id"] for r in rows if r["player_id"]})})
        if stop:
            break
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {"mode": mode, "started_at": now.isoformat(timespec="seconds"), "finished_at": finished, "budget": b,
            "credits_billed": billed, "credits_remaining_after": remaining, "requests": requests, "stopped": stop,
            "source": "the_odds_api", "endpoint": "/v4/sports/basketball_nba/events/{event_id}/odds", "params": {"regions": "us", "markets": "player_points",
            "oddsFormat": "american"}}
    out = {"mode": mode, "date": day.isoformat(), "budget": b, "games_today": len(events), "to_request": len(todo),
           "captured": sum(r["status"] == "captured" for r in requests), "empty": sum(r["status"] == "empty" for r in requests),
           "errors": sum(r["status"] == "error" for r in requests), "skipped_cap": skipped_cap, "credits_billed": billed,
           "credits_remaining_after": remaining, "stopped": stop}
    if requests:
        w = MS.write_run(store, reader, day.isoformat(), run_ts, objects, views, meta)
        usage = {k: meta[k] for k in ("mode", "started_at", "finished_at", "budget", "credits_billed", "credits_remaining_after", "stopped")}
        MS.put_verified(store, reader, f"{MS.PREFIX}/_usage/{day.strftime('%Y-%m')}/{run_ts}.json", json.dumps(usage, sort_keys=True).encode())
        out.update(objects=len(objects) + 1, games_in_view=w["games_in_view"],
                   matched_players=sum(r.get("matched_players", 0) for r in requests), players=sum(r.get("players", 0) for r in requests))
    return out


WINDOWS = {"main": ((5, 30), (8, 30)), "followup": ((9, 30), (12, 30))}     # Pacific time


def in_window(mode: str, now: datetime) -> bool:
    """For backup (GitHub schedule) triggers: only inside the mode's Pacific-time window (handles daylight saving)."""
    t = now.astimezone(PT)
    (h0, m0), (h1, m1) = WINDOWS[mode]
    return (h0, m0) <= (t.hour, t.minute) < (h1, m1)


def lines_done(refresh_log: Path, day: date) -> bool:
    """Today's noon game-line refresh (midday slot) succeeded, per the refresh log on the preview branch."""
    want = f"midday:{day.isoformat()}"
    try:
        return any(json.loads(l).get("slot") == want and json.loads(l).get("status") == "success" for l in refresh_log.read_text().splitlines() if l.strip())
    except OSError:
        return False


def main(argv=None) -> int:
    import argparse
    from modelroom.archive.store import from_env, reader_from_env
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["plan", "fetch", "verify"])
    ap.add_argument("--mode", choices=["main", "followup"], default="main")
    ap.add_argument("--board", default="data/published/nba_props.json")
    ap.add_argument("--refresh-log", default="preview-ledger/refresh_log.jsonl")
    ap.add_argument("--date", default=None)
    ap.add_argument("--local", default=None, help="local folder instead of R2 (tests)")
    ap.add_argument("--only-in-window", action="store_true", help="skip unless now is inside the mode's Pacific window")
    a = ap.parse_args(argv)
    reset_day = int(os.environ.get("ODDS_API_CYCLE_DAY", "10") or 10)
    now = datetime.now(timezone.utc)
    day = now.astimezone(PT).date()
    reader = reader_from_env(a.local)
    if a.action == "verify":
        out = MS.verify_day(reader, a.date or day.isoformat())
        print(json.dumps(out))
        return 0 if out["ok"] else 1
    if a.action == "plan":                         # no paid request: budget from the last known remaining credits
        hist = day_history(reader, day.isoformat())
        rem = int(os.environ.get("ODDS_REMAINING_HINT", "0") or 0)
        print(json.dumps(budget(rem, day, reset_day, False, hist["billed"])))
        return 0
    if a.only_in_window and not in_window(a.mode, now):
        print(json.dumps({"mode": a.mode, "skipped": f"outside the {a.mode} window ({now.astimezone(PT):%H:%M} PT)"}))
        return 0
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        print(json.dumps({"stopped": "ODDS_API_KEY not set"}))
        return 1
    try:
        out = run(a.mode, key, json.loads(Path(a.board).read_text()), from_env(a.local), reader, now, reset_day, False,
                  Path("config/nba_player_aliases.csv"))
    except StopRun as s:
        out = {"mode": a.mode, "stopped": scrub(str(s), key)}
    except Exception as e:  # noqa: BLE001  never print a traceback that could carry the request URL
        out = {"mode": a.mode, "stopped": f"unexpected error: {type(e).__name__}: {scrub(str(e), key)[:200]}"}
    print(json.dumps(out))
    return 1 if out.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
