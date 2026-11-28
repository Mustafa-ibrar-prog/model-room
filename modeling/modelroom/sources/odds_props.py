"""NBA player points lines from The Odds API, one request per game per day, stored in private R2 (TEST; Moose,
approved 2026-11-24). No Supabase. Never estimates a line; the model never reads these.

Request: GET /v4/sports/basketball_nba/events/{event_id}/odds?regions=us&markets=player_points
  cost = markets returned x regions = 1 credit (0 when the book hasn't posted the market). The events list is free.

Which games when the allowance is short (Moose, 2026-11-27): a deterministic golden-ratio rotation over the day's
start order (rotation() below), so later West Coast games get the same share as early ones over a month. Every
requested, credit-limited and unattempted game is recorded in the manifest's "selection" for auditing.

Schedule (Moose, 2026-11-25): 5:30 AM PT main run (every game today not yet requested) and a 9:30 AM PT retry ONLY
for games whose single paid request came back with no player points. Each mode runs once a day (write-once R2 lock;
a completed mode is never repeated), and every paid request leaves a write-once attempt marker before anything else,
so duplicate triggers can never pay twice for a game.

Storage date: every snapshot sits under its game's Pacific date. Only today's games are ever requested (tomorrow's
stay Pending until their own 5:30 AM run, Moose 2026-11-27), so the run day and the game date are the same.

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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Sport:
    """One league's player-prop collection: where to ask, which single market (1 credit per game), where to store."""
    name: str
    base: str
    market: str
    prefix: str


NFL_BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
NBA = Sport("nba", BASE, "player_points", MS.PREFIX)
NFL = Sport("nfl", NFL_BASE, "player_reception_yds", MS.NFL_PREFIX)


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


# ------------------------------------------------------------------ rotation (Moose, 2026-11-27)
ROTATION_RULE = "golden-ratio rotation over the day's start order, v1"
PHI_FRAC = 0.6180339887498949            # golden ratio's fractional part: low-discrepancy, so every slot gets its turn
EPOCH = date(2026, 1, 1)


def rotation(events: list[dict], day: date) -> dict:
    """Deterministic, fair request order for one day's games. Games are numbered by start time (ties by event id); the
    day's start slot is floor(frac(day_index x 0.618...) x n), and the order runs round the slate from there. When the
    allowance covers only part of the slate, the covered part moves to a different stretch of the evening each day,
    so early and late (West Coast) games get the same share over a month. Same day + same slate = same order."""
    ordered = sorted(events, key=lambda e: (e["commence_time"], e["id"]))
    n = len(ordered)
    if not n:
        return {"rule": ROTATION_RULE, "day_index": (day - EPOCH).days, "n": 0, "offset": 0, "order": []}
    di = (day - EPOCH).days
    off = math.floor(((di * PHI_FRAC) % 1.0) * n)
    order = ordered[off:] + ordered[:off]
    return {"rule": ROTATION_RULE, "day_index": di, "n": n, "offset": off, "order": order}


# ------------------------------------------------------------------ run
def today_events(events: list[dict], now: datetime) -> list[dict]:
    t = now.astimezone(PT).date()
    out = [e for e in events if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) > now + START_BUFFER
           and datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(PT).date() == t]
    return sorted(out, key=lambda e: (e["commence_time"], e["id"]))


def day_history(reader, day: str, prefix: str = MS.PREFIX) -> dict:
    """What has been done today, from R2:
      - write-once attempt markers (one per PAID request, written before anything else): attempts per game, the
        newest outcome (captured | empty) and credits billed. They are the authority, so a run that died before its
        manifest still counts.
      - manifests: which modes completed, and games never requested (skipped_cap, error) so a later main run of the
        same day doesn't pick them up again."""
    status, attempts, billed, modes, newest = {}, {}, 0, set(), {}
    for k in reader.list(f"{MS.day_prefix(day, prefix)}/"):
        parts = k.rsplit("/", 2)
        if len(parts) == 3 and parts[2].startswith("attempt-") and parts[2].endswith(".json"):
            eid = parts[1]
            m = json.loads(reader.get(k))
            attempts[eid] = attempts.get(eid, 0) + 1
            billed += int(m.get("cost", 0))
            if parts[2] > newest.get(eid, ""):
                newest[eid] = parts[2]
                status[eid] = m["status"]
    latest = MS.read_latest(reader, day, prefix)
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


def acquire_lock(store, reader, day: str, mode: str, now: datetime, run_ts: str, prefix: str = MS.PREFIX) -> tuple[bool, str]:
    """A write-once lock per day and mode, so two triggers (scheduler + GitHub backup) can never run the same
    mode at the same time. A lock younger than 30 minutes means another run is active or just finished: skip. An
    older lock whose run never completed may be taken over, at most MAX_LOCKS times a day."""
    from modelroom.archive.store import ArchiveError
    for k in range(1, MAX_LOCKS + 1):
        lk = f"{MS.day_prefix(day, prefix)}/locks/{mode}-{k}.json"
        try:
            store.put_once(lk, json.dumps({"run_ts": run_ts, "at": now.isoformat(timespec="seconds")}).encode())
            return True, lk
        except ArchiveError:
            held = json.loads(reader.get(lk))
            if now - datetime.fromisoformat(held["at"]) < LOCK_STALE:
                return False, f"another {mode} run started at {held['at']} (lock {k})"
    return False, f"{mode} already attempted {MAX_LOCKS} times today"


def run(mode: str, key: str, board: dict, store, reader, now: datetime | None = None, reset_day: int = 10,
        lines_done_today: bool = False, aliases_path: Path | None = None, http=_http, sleep=time.sleep,
        sport: Sport = NBA, cap: int | None = None, other_billed: int = 0) -> dict:
    """mode 'main' (every game not yet requested today) or 'followup' (only games whose market was empty earlier).
    sport: which league and market. cap: at most this many paid requests in this run (the day's share, see run_day).
    other_billed: credits the OTHER league's props already billed today, so the shared daily allowance holds."""
    P = sport.prefix
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(PT).date()
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")       # unique per run, even within one second
    hist0 = day_history(reader, day.isoformat(), P)
    if mode in hist0["modes"]:
        return {"mode": mode, "date": day.isoformat(), "skipped": f"{mode} run already completed today", "requested": 0}
    ok, why = acquire_lock(store, reader, day.isoformat(), mode, now, run_ts, P)
    if not ok:
        return {"mode": mode, "date": day.isoformat(), "skipped": why, "requested": 0}
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), PT).astimezone(timezone.utc)
    ev = get(f"{sport.base}/events?apiKey={key}&dateFormat=iso&commenceTimeFrom={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
             f"&commenceTimeTo={end.strftime('%Y-%m-%dT%H:%M:%SZ')}", key, http, sleep)
    remaining, cost = _credits(ev["headers"])
    if cost != 0:
        raise StopRun(f"the events list cost {cost} credits (expected 0)")
    events = today_events(json.loads(ev["body"]), now)
    hist = day_history(reader, day.isoformat(), P)
    b = budget(remaining, day, reset_day, False, hist["billed"] + other_billed)   # today's 12 game-line credits always held back
    limit = b["allowance"] if cap is None else min(b["allowance"], cap)
    if mode == "followup":                                          # retry ONLY games whose one paid attempt was empty
        todo = [e for e in events if hist["status"].get(e["id"]) == "empty" and hist["attempts"].get(e["id"], 0) == 1]
    else:
        todo = [e for e in events if e["id"] not in hist["status"]]
    rot = rotation(events, day)                                     # fair order across the slate, day by day
    pos = {e["id"]: i for i, e in enumerate(rot["order"])}
    todo.sort(key=lambda e: pos[e["id"]])
    start_slot = {e["id"]: i for i, e in enumerate(sorted(events, key=lambda e: (e["commence_time"], e["id"])))}
    aliases = PM.load_aliases(aliases_path)
    games = board.get("games") or []
    requests, objects, views = [], [], []
    billed, skipped_cap, stop = 0, 0, None
    for e in todo:
        if billed >= limit or not may_request(remaining, b["reserve"]):
            skipped_cap += 1
            g0 = PM.match_game(e, games)
            requests.append({"event_id": e["id"], "status": "skipped_cap", "game_id": g0["game_id"] if g0 else None})
            continue
        try:
            res = get(f"{sport.base}/events/{e['id']}/odds?apiKey={key}&regions=us&markets={sport.market}&oddsFormat=american&dateFormat=iso",
                      key, http, sleep)
            remaining, cost = _credits(res["headers"])
        except StopRun as s:
            stop = scrub(str(s), key)
            break
        except Exception as x:  # noqa: BLE001  one game failed: skip it today, keep going
            g0 = PM.match_game(e, games)
            requests.append({"event_id": e["id"], "status": "error", "game_id": g0["game_id"] if g0 else None, "error": scrub(str(x), key)[:120]})
            continue
        billed += cost
        if cost > 1:
            stop = f"a request cost {cost} credits (cap is 1)"
        body = res["body"]
        data = json.loads(body)
        game = PM.match_game(e, games)
        n_out = sum(len(m.get("outcomes") or []) for bk in data.get("bookmakers") or [] for m in bk.get("markets") or [] if m.get("key") == sport.market)
        try:
            MS.put_verified(store, reader, f"{MS.day_prefix(day.isoformat(), P)}/{e['id']}/attempt-{run_ts}.json",
                            json.dumps({"mode": mode, "status": "captured" if n_out else "empty", "cost": cost, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}).encode())
        except Exception:  # noqa: BLE001  can't record the attempt: stop before spending more
            stop = "could not record a request in R2: stopping before any further request"
        if n_out == 0:                                              # genuinely empty: no player points offered yet
            requests.append({"event_id": e["id"], "status": "empty", "cost": cost, "game_id": game["game_id"] if game else None})
            if stop:
                break
            continue
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cap_ts = MS.stamp()
        base = f"{MS.day_prefix(day.isoformat(), P)}/{e['id']}/{cap_ts}"
        h = sha256(body)
        try:
            raw = MS.put_verified(store, reader, f"{base}.raw.json", body)
            rows = PM.rows_from_response(data, game, aliases, fetched, h, sport.market)
            rbody = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
            rput = MS.put_verified(store, reader, f"{base}.rows.jsonl", rbody)
        except Exception as x:  # noqa: BLE001  credit spent, response discarded; never re-requested today
            requests.append({"event_id": e["id"], "status": "error", "cost": cost, "game_id": game["game_id"] if game else None,
                             "error": f"upload failed: {type(x).__name__}"})
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
    selection = {"rule": rot["rule"], "day_index": rot["day_index"], "slate_size": rot["n"], "offset": rot["offset"],
                 "order": [{"event_id": e["id"], "start_slot": start_slot[e["id"]]} for e in rot["order"]],
                 "requested": [r["event_id"] for r in requests if r["status"] in ("captured", "empty", "error") and "cost" in r],
                 "credit_limited": [r["event_id"] for r in requests if r["status"] == "skipped_cap"],
                 "not_attempted": [e["id"] for e in events if e["id"] not in {r["event_id"] for r in requests} and e in todo]}
    meta = {"mode": mode, "started_at": now.isoformat(timespec="seconds"), "finished_at": finished, "budget": b, "selection": selection,
            "credits_billed": billed, "credits_remaining_after": remaining, "requests": requests, "stopped": stop,
            "source": "the_odds_api", "endpoint": f"{sport.base.split('/v4')[1]}/events/{{event_id}}/odds", "params": {"regions": "us", "markets": sport.market,
            "oddsFormat": "american"}}
    out = {"league": sport.name, "mode": mode, "date": day.isoformat(), "budget": b, "share": cap, "games_today": len(events), "to_request": len(todo),
           "rotation": {"offset": rot["offset"], "slate_size": rot["n"],
                        "requested_start_slots": sorted(start_slot[x] for x in selection["requested"]),
                        "credit_limited_start_slots": sorted(start_slot[x] for x in selection["credit_limited"])},
           "captured": sum(r["status"] == "captured" for r in requests), "empty": sum(r["status"] == "empty" for r in requests),
           "errors": sum(r["status"] == "error" for r in requests), "skipped_cap": skipped_cap, "credits_billed": billed,
           "credits_remaining_after": remaining, "stopped": stop}
    if requests:
        w = MS.write_run(store, reader, day.isoformat(), run_ts, objects, views, meta, P, sport.market)
        usage = {k: meta[k] for k in ("mode", "started_at", "finished_at", "budget", "credits_billed", "credits_remaining_after", "stopped")}
        usage["selection"] = {k: selection[k] for k in ("rule", "day_index", "slate_size", "offset")} | {
            "requested": len(selection["requested"]), "credit_limited": len(selection["credit_limited"])}
        MS.put_verified(store, reader, f"{P}/_usage/{day.strftime('%Y-%m')}/{run_ts}.json", json.dumps(usage, sort_keys=True).encode())
        out.update(objects=len(objects) + 1, games_in_view=w["games_in_view"],
                   matched_players=sum(r.get("matched_players", 0) for r in requests), players=sum(r.get("players", 0) for r in requests))
    return out


# ------------------------------------------------------------------ three full refreshes, today AND tomorrow (Moose, 2026-11-27)
REFRESH_SLOTS = ("morning", "midday", "afternoon")       # 7:00 AM, 12:30 PM, 4:00 PM PT (modelroom/refresh_plan.py)
MAX_ATTEMPTS = 3                                         # per game, across the three slots; captured games never again


def _pt_date(commence: str) -> str:
    return datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(PT).date().isoformat()


def window_events(events: list[dict], now: datetime) -> list[dict]:
    """Games starting more than 10 minutes from now whose Pacific date is today or tomorrow."""
    d0 = now.astimezone(PT).date()
    keep = {d0.isoformat(), (d0 + timedelta(days=1)).isoformat()}
    out = [e for e in events if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) > now + START_BUFFER
           and _pt_date(e["commence_time"]) in keep]
    return sorted(out, key=lambda e: (e["commence_time"], e["id"]))


def run_refresh(slot: str, key: str, board: dict, store, reader, now: datetime | None = None, reset_day: int = 10,
                aliases_path: Path | None = None, http=_http, sleep=time.sleep, sport: Sport = NBA, cap: int | None = None,
                other_billed: int = 0) -> dict:
    """One of the three daily refreshes. Covers today's AND tomorrow's games. Requests only games with no captured
    lines yet (a captured game is never requested again), at most MAX_ATTEMPTS times per game, today's games first,
    within the same daily allowance as before (game-line reserve, 30-credit margin, 15 floor, 15-a-day cap).

    Storage: each game's data, manifest and view go to its own game-date folder (the site reads lines by game date);
    the paid-attempt marker goes to TODAY's folder too, so today's billed credits are always counted in one place."""
    from modelroom.archive.store import ArchiveError
    now = now or datetime.now(timezone.utc)
    P = sport.prefix
    today = now.astimezone(PT).date()
    t = today.isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    done_key = f"{MS.day_prefix(t, P)}/locks/done-{slot}.json"
    try:
        reader.get(done_key)
        return {"league": sport.name, "mode": slot, "date": t, "skipped": f"{slot} refresh already completed today", "requested": 0}
    except Exception:  # noqa: BLE001  not done yet
        pass
    ok, why = acquire_lock(store, reader, t, slot, now, run_ts, P)
    if not ok:
        return {"league": sport.name, "mode": slot, "date": t, "skipped": why, "requested": 0}
    end = datetime.combine(today + timedelta(days=2), datetime.min.time(), PT).astimezone(timezone.utc)
    ev = get(f"{sport.base}/events?apiKey={key}&dateFormat=iso&commenceTimeFrom={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
             f"&commenceTimeTo={end.strftime('%Y-%m-%dT%H:%M:%SZ')}", key, http, sleep)
    remaining, cost = _credits(ev["headers"])
    if cost != 0:
        raise StopRun(f"the events list cost {cost} credits (expected 0)")
    events = window_events(json.loads(ev["body"]), now)
    h_today = day_history(reader, t, P)                     # billing for requests made today, and today's games
    h_tom = day_history(reader, tomorrow, P)                # tomorrow's games (captured / tried earlier today)
    status = {**h_tom["status"], **h_today["status"]}
    for eid, st in h_tom["status"].items():                 # "captured" anywhere wins
        if st == "captured":
            status[eid] = "captured"
    attempts = {e: h_today["attempts"].get(e, 0) + h_tom["attempts"].get(e, 0) for e in set(h_today["attempts"]) | set(h_tom["attempts"])}
    b = budget(remaining, today, reset_day, False, h_today["billed"] + other_billed)
    limit = b["allowance"] if cap is None else min(b["allowance"], cap)
    todo = [e for e in events if status.get(e["id"]) != "captured" and attempts.get(e["id"], 0) < MAX_ATTEMPTS]
    # Today's games first (lines are most likely posted), each date in the fair rotation order.
    groups = []
    for d in (t, tomorrow):
        day_ev = [e for e in events if _pt_date(e["commence_time"]) == d]
        pos = {e["id"]: i for i, e in enumerate(rotation(day_ev, date.fromisoformat(d))["order"])}
        groups += sorted([e for e in todo if _pt_date(e["commence_time"]) == d], key=lambda e: pos[e["id"]])
    todo = groups
    aliases = PM.load_aliases(aliases_path)
    games = board.get("games") or []
    per_date: dict[str, dict] = {}
    billed, skipped_cap, stop = 0, 0, None

    def bucket(d):
        return per_date.setdefault(d, {"requests": [], "objects": [], "views": []})

    for e in todo:
        d = _pt_date(e["commence_time"])
        g0 = PM.match_game(e, games)
        gid = g0["game_id"] if g0 else None
        if billed >= limit or not may_request(remaining, b["reserve"]):
            skipped_cap += 1
            bucket(d)["requests"].append({"event_id": e["id"], "status": "skipped_cap", "game_id": gid})
            continue
        try:
            res = get(f"{sport.base}/events/{e['id']}/odds?apiKey={key}&regions=us&markets={sport.market}&oddsFormat=american&dateFormat=iso",
                      key, http, sleep)
            remaining, cost = _credits(res["headers"])
        except StopRun as s_:
            stop = scrub(str(s_), key)
            break
        except Exception as x:  # noqa: BLE001
            bucket(d)["requests"].append({"event_id": e["id"], "status": "error", "game_id": gid, "error": scrub(str(x), key)[:120]})
            continue
        billed += cost
        if cost > 1:
            stop = f"a request cost {cost} credits (cap is 1)"
        body = res["body"]
        data = json.loads(body)
        n_out = sum(len(m.get("outcomes") or []) for bk in data.get("bookmakers") or [] for m in bk.get("markets") or [] if m.get("key") == sport.market)
        marker = json.dumps({"mode": slot, "status": "captured" if n_out else "empty", "cost": cost, "game_date": d,
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}).encode()
        try:
            MS.put_verified(store, reader, f"{MS.day_prefix(t, P)}/{e['id']}/attempt-{run_ts}.json", marker)   # billing: request day
            if d != t:
                # a copy in the game's own folder (named seen-, so it never counts as a second attempt or a second credit)
                MS.put_verified(store, reader, f"{MS.day_prefix(d, P)}/{e['id']}/seen-{run_ts}.json", json.dumps({**json.loads(marker), "billed_on": t}).encode())
        except Exception:  # noqa: BLE001
            stop = "could not record a request in R2: stopping before any further request"
        if n_out == 0:
            bucket(d)["requests"].append({"event_id": e["id"], "status": "empty", "cost": cost, "game_id": gid})
            if stop:
                break
            continue
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        base = f"{MS.day_prefix(d, P)}/{e['id']}/{MS.stamp()}"
        try:
            raw = MS.put_verified(store, reader, f"{base}.raw.json", body)
            rows = PM.rows_from_response(data, g0, aliases, fetched, sha256(body), sport.market)
            rbody = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
            rput = MS.put_verified(store, reader, f"{base}.rows.jsonl", rbody)
        except Exception as x:  # noqa: BLE001
            bucket(d)["requests"].append({"event_id": e["id"], "status": "error", "cost": cost, "game_id": gid, "error": f"upload failed: {type(x).__name__}"})
            if stop:
                break
            continue
        bk = bucket(d)
        bk["objects"] += [{"key": raw["key"], "bytes": raw["bytes"], "sha256": raw["sha256"], "kind": "raw", "event_id": e["id"]},
                          {"key": rput["key"], "bytes": rput["bytes"], "sha256": rput["sha256"], "kind": "rows", "event_id": e["id"]}]
        bk["views"].append(PM.view_for_game(rows, g0, fetched))
        bk["requests"].append({"event_id": e["id"], "status": "captured", "cost": cost, "game_id": gid, "books": len(data.get("bookmakers") or []),
                               "players": len({r["player_name"] for r in rows}), "matched_players": len({r["player_id"] for r in rows if r["player_id"]})})
        if stop:
            break
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for d, bk in per_date.items():
        if not bk["requests"]:
            continue
        meta = {"mode": slot, "started_at": now.isoformat(timespec="seconds"), "finished_at": finished, "budget": b, "requests": bk["requests"],
                "credits_billed_run": billed, "credits_remaining_after": remaining, "stopped": stop, "source": "the_odds_api",
                "endpoint": f"{sport.base.split('/v4')[1]}/events/{{event_id}}/odds", "params": {"regions": "us", "markets": sport.market, "oddsFormat": "american"},
                "window": [t, tomorrow]}
        MS.write_run(store, reader, d, f"{run_ts}-{slot}", bk["objects"], bk["views"], meta, P, sport.market)
    reqs = [r for bk in per_date.values() for r in bk["requests"]]
    usage = {"mode": slot, "started_at": now.isoformat(timespec="seconds"), "finished_at": finished, "budget": b, "credits_billed": billed,
             "credits_remaining_after": remaining, "stopped": stop, "window": [t, tomorrow], "requested": sum(1 for r in reqs if "cost" in r),
             "credit_limited": skipped_cap}
    if reqs:
        MS.put_verified(store, reader, f"{P}/_usage/{today.strftime('%Y-%m')}/{run_ts}.json", json.dumps(usage, sort_keys=True).encode())
    if not stop:
        try:
            store.put_once(done_key, json.dumps({"at": finished, "run_ts": run_ts}).encode())
        except ArchiveError:
            pass
    by_date = {d: {"captured": sum(r["status"] == "captured" for r in bk["requests"]), "empty": sum(r["status"] == "empty" for r in bk["requests"]),
                   "skipped_cap": sum(r["status"] == "skipped_cap" for r in bk["requests"]), "errors": sum(r["status"] == "error" for r in bk["requests"])}
               for d, bk in per_date.items()}
    return {"league": sport.name, "mode": slot, "date": t, "window": [t, tomorrow], "budget": b, "share": cap, "games_in_window": len(events),
            "already_captured": sum(1 for e in events if status.get(e["id"]) == "captured"), "to_request": len(todo), "by_date": by_date,
            "captured": sum(v["captured"] for v in by_date.values()), "empty": sum(v["empty"] for v in by_date.values()),
            "errors": sum(v["errors"] for v in by_date.values()), "skipped_cap": skipped_cap, "credits_billed": billed,
            "credits_remaining_after": remaining, "stopped": stop}


# ------------------------------------------------------------------ both leagues, one allowance (Moose, 2026-11-27)
def split_allowance(allowance: int, counts: dict[str, int]) -> dict[str, int]:
    """Share one day's prop allowance between leagues in proportion to the games each still needs (largest
    remainder; ties go to the league listed first). When there are at least as many credits as leagues with games,
    every such league gets at least one, so a single Thursday or Monday NFL game isn't starved by a full NBA slate."""
    out = {k: 0 for k in counts}
    live = {k: c for k, c in counts.items() if c > 0}
    if allowance <= 0 or not live:
        return out
    if allowance >= sum(live.values()):
        return {k: counts[k] for k in counts}
    left = allowance
    if allowance >= len(live):
        for k in live:
            out[k] = 1
        left -= len(live)
    rest = {k: live[k] - out[k] for k in live}
    tot = sum(rest.values())
    if left and tot:
        raw = {k: left * rest[k] / tot for k in rest}
        for k in rest:
            out[k] += math.floor(raw[k])
        extra = left - sum(math.floor(v) for v in raw.values())
        for k in sorted(rest, key=lambda k: (-(raw[k] % 1), list(counts).index(k)))[:extra]:
            out[k] += 1
    return out


def _events_today(sport: Sport, key: str, now: datetime, http, sleep) -> tuple[list[dict], int]:
    day = now.astimezone(PT).date()
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), PT).astimezone(timezone.utc)
    ev = get(f"{sport.base}/events?apiKey={key}&dateFormat=iso&commenceTimeFrom={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
             f"&commenceTimeTo={end.strftime('%Y-%m-%dT%H:%M:%SZ')}", key, http, sleep)
    remaining, cost = _credits(ev["headers"])
    if cost != 0:
        raise StopRun(f"the events list cost {cost} credits (expected 0)")
    return today_events(json.loads(ev["body"]), now), remaining


def _league_need(sp: Sport, mode: str, refresh: bool, key: str, now: datetime, day: str, reader, http, sleep) -> tuple[int, int, int]:
    """(remaining credits, games still needing lines, credits billed today) for one league. Events lists are free."""
    if refresh:
        end = datetime.combine(now.astimezone(PT).date() + timedelta(days=2), datetime.min.time(), PT).astimezone(timezone.utc)
        ev = get(f"{sp.base}/events?apiKey={key}&dateFormat=iso&commenceTimeFrom={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                 f"&commenceTimeTo={end.strftime('%Y-%m-%dT%H:%M:%SZ')}", key, http, sleep)
        remaining, cost = _credits(ev["headers"])
        if cost != 0:
            raise StopRun(f"the events list cost {cost} credits (expected 0)")
        events = window_events(json.loads(ev["body"]), now)
        h = day_history(reader, day, sp.prefix)
        h2 = day_history(reader, (now.astimezone(PT).date() + timedelta(days=1)).isoformat(), sp.prefix)
        cap_ = lambda e: "captured" in (h["status"].get(e), h2["status"].get(e))    # noqa: E731
        att = lambda e: h["attempts"].get(e, 0) + h2["attempts"].get(e, 0)          # noqa: E731
        return remaining, sum(1 for e in events if not cap_(e["id"]) and att(e["id"]) < MAX_ATTEMPTS), h["billed"]
    events, remaining = _events_today(sp, key, now, http, sleep)
    h = day_history(reader, day, sp.prefix)
    if mode in h["modes"]:
        n = 0
    elif mode == "followup":
        n = sum(1 for e in events if h["status"].get(e["id"]) == "empty" and h["attempts"].get(e["id"], 0) == 1)
    else:
        n = sum(1 for e in events if e["id"] not in h["status"])
    return remaining, n, h["billed"]


def run_day(mode: str, key: str, boards: dict[str, dict], store, reader, now: datetime | None = None, reset_day: int = 10,
            aliases_path: Path | None = None, http=_http, sleep=time.sleep) -> dict:
    """NBA player points and NFL receiving yards from ONE daily allowance (the existing budget: game-line reserve,
    30-credit margin, 15-credit floor and 15-a-day cap are unchanged). Events lists are free. The allowance is split by
    games still needed (split_allowance); NBA runs with its share, then NFL gets whatever the same budget still
    allows (its share plus anything NBA didn't use). Every game not requested because of the cap is recorded as
    skipped_cap in that league's manifest, so the site can say so."""
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(PT).date().isoformat()
    refresh = mode in REFRESH_SLOTS
    need, billed, remaining = {}, {}, None
    failed: dict[str, str] = {}
    for sp in (NBA, NFL):
        if sp.name not in boards:
            continue
        try:
            remaining_, need_, billed_ = _league_need(sp, mode, refresh, key, now, day, reader, http, sleep)
        except Exception as x:  # noqa: BLE001  one league's provider trouble never stops the other league
            failed[sp.name] = scrub(f"{type(x).__name__}: {x}", key)[:160]
            continue
        remaining = remaining_ if remaining_ is not None else remaining
        need[sp.name], billed[sp.name] = need_, billed_
    b = budget(remaining or 0, now.astimezone(PT).date(), reset_day, False, sum(billed.values()))
    shares = split_allowance(b["allowance"], need)
    out = {"mode": mode, "date": day, "budget": b, "games_needing_lines": need, "shares": shares, "leagues": {}}
    def fn(m, key_, board, st, rd, now_, reset_, lines_done, aliases, http_, sleep_, **k):
        if refresh:
            return run_refresh(m, key_, board, st, rd, now_, reset_, aliases, http_, sleep_, **k)
        return run(m, key_, board, st, rd, now_, reset_, lines_done, aliases, http_, sleep_, **k)

    def guarded(name, call):
        if name in failed:
            return {"league": name, "mode": mode, "stopped": f"events list failed: {failed[name]}", "credits_billed": 0}
        try:
            return call()
        except StopRun as x:
            return {"league": name, "mode": mode, "stopped": scrub(str(x), key), "credits_billed": 0}
        except Exception as x:  # noqa: BLE001  one league failing never stops the other
            return {"league": name, "mode": mode, "stopped": f"unexpected error: {type(x).__name__}: {scrub(str(x), key)[:160]}", "credits_billed": 0}

    if remaining is None:
        out["stopped"] = "no league's events list could be read"
        out["leagues"] = {k: {"league": k, "stopped": v} for k, v in failed.items()}
        out["credits_billed"] = 0
        return out
    if "nba" in boards:
        out["leagues"]["nba"] = guarded("nba", lambda: fn(mode, key, boards["nba"], store, reader, now, reset_day, False, aliases_path, http, sleep,
                                                          sport=NBA, cap=shares.get("nba", 0), other_billed=billed.get("nfl", 0)))
    if "nfl" in boards:
        nba_now = day_history(reader, day, NBA.prefix)["billed"] if "nba" in boards else 0
        out["leagues"]["nfl"] = guarded("nfl", lambda: fn(mode, key, boards["nfl"], store, reader, now, reset_day, False, None, http, sleep,
                                                          sport=NFL, cap=None, other_billed=nba_now))
    out["credits_billed"] = sum(v.get("credits_billed", 0) for v in out["leagues"].values())
    out["stopped"] = next((v["stopped"] for v in out["leagues"].values() if v.get("stopped")), None)
    return out


WINDOWS = {"main": ((5, 30), (8, 30)), "followup": ((9, 30), (12, 30)),           # Pacific time (retired 2026-11-28)
           "morning": ((7, 0), (9, 30)), "midday": ((12, 30), (15, 0)), "afternoon": ((16, 0), (18, 30))}


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
    ap.add_argument("action", choices=["plan", "fetch", "verify", "probe-nfl-receiving-yards"])
    ap.add_argument("--mode", choices=["main", "followup", *REFRESH_SLOTS], default="main")
    ap.add_argument("--board", default="data/published/nba_props.json")
    ap.add_argument("--nfl-board", default="data/published/nfl_props.json", help="'' = NBA only")
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
        out = {lg: MS.verify_day(reader, a.date or day.isoformat(), pre) for lg, pre in (("nba", MS.PREFIX), ("nfl", MS.NFL_PREFIX))}
        print(json.dumps(out))
        return 0 if all(v["ok"] for v in out.values()) else 1
    if a.action == "plan":                         # no paid request: budget from the last known remaining credits
        billed = day_history(reader, day.isoformat())["billed"] + day_history(reader, day.isoformat(), MS.NFL_PREFIX)["billed"]
        rem = int(os.environ.get("ODDS_REMAINING_HINT", "0") or 0)
        print(json.dumps(budget(rem, day, reset_day, False, billed)))
        return 0
    if a.only_in_window and not in_window(a.mode, now):
        print(json.dumps({"mode": a.mode, "skipped": f"outside the {a.mode} window ({now.astimezone(PT):%H:%M} PT)"}))
        return 0
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        print(json.dumps({"stopped": "ODDS_API_KEY not set"}))
        return 1
    if a.action == "probe-nfl-receiving-yards":
        try:
            out = probe_nfl_receiving_yards(key, json.loads(Path(a.board).read_text()), from_env(a.local), reader, now, reset_day)
        except Exception as e:  # noqa: BLE001
            out = {"stopped": f"{type(e).__name__}: {scrub(str(e), key)[:200]}"}
        print(json.dumps(out))
        return 1 if out.get("stopped") else 0
    try:
        boards = {"nba": json.loads(Path(a.board).read_text())}
        if a.nfl_board and Path(a.nfl_board).exists():
            boards["nfl"] = json.loads(Path(a.nfl_board).read_text())
        out = run_day(a.mode, key, boards, from_env(a.local), reader, now, reset_day, Path("config/nba_player_aliases.csv"))
    except StopRun as s:
        out = {"mode": a.mode, "stopped": scrub(str(s), key)}
    except Exception as e:  # noqa: BLE001  never print a traceback that could carry the request URL
        out = {"mode": a.mode, "stopped": f"unexpected error: {type(e).__name__}: {scrub(str(e), key)[:200]}"}
    print(json.dumps(out))
    return 1 if out.get("stopped") else 0



# ------------------------------------------------------------------ one-off probe (Moose, 2026-11-27)


def probe_nfl_receiving_yards(key: str, board: dict, store, reader, now: datetime | None = None, reset_day: int = 10,
                              http=_http, sleep=time.sleep) -> dict:
    """ONE request: player receiving yards (player_reception_yds, US books) for the next upcoming NFL game. Approved
    once by Moose (2026-11-27); no recurring schedule. Hard limits: the game-line reserve + safety margin and the
    15-credit floor (the monthly guarantee) must hold after it; a cost above 1 or missing credit headers is reported.
    A write-once lock makes a second dispatch a no-op. The raw response is stored write-once in private R2 and read
    back with the read-only token. Returns counts only."""
    from modelroom.archive.store import ArchiveError
    now = now or datetime.now(timezone.utc)
    lock = "v1/market-snapshots/nfl/player-reception-yds/_probe/lock.json"
    try:
        store.put_once(lock, json.dumps({"at": now.isoformat(timespec="seconds")}).encode())
    except ArchiveError:
        return {"skipped": "the approved one-time NFL probe already ran"}
    ev = get(f"{NFL_BASE}/events?apiKey={key}&dateFormat=iso&commenceTimeFrom={now.strftime('%Y-%m-%dT%H:%M:%SZ')}", key, http, sleep)
    remaining, cost = _credits(ev["headers"])
    if cost != 0:
        raise StopRun(f"the events list cost {cost} credits (expected 0)")
    events = sorted(json.loads(ev["body"]), key=lambda e: (e["commence_time"], e["id"]))
    if not events:
        return {"skipped": "no upcoming NFL game listed"}
    e = events[0]
    day = now.astimezone(PT).date()
    b = budget(remaining, day, reset_day, False, 0)
    if not may_request(remaining, b["reserve"]):
        return {"skipped": "the request would dip into the game-line reserve", "budget": b}
    res = get(f"{NFL_BASE}/events/{e['id']}/odds?apiKey={key}&regions=us&markets=player_reception_yds&oddsFormat=american&dateFormat=iso",
              key, http, sleep)
    remaining, cost = _credits(res["headers"])
    data = json.loads(res["body"])
    gdate = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(PT).date().isoformat()
    base = f"v1/market-snapshots/nfl/player-reception-yds/{gdate}/{e['id']}/{MS.stamp(now)}"
    MS.put_verified(store, reader, f"{base}.attempt.json", json.dumps({"cost": cost, "at": now.isoformat(timespec="seconds"), "probe": True}).encode())
    raw = MS.put_verified(store, reader, f"{base}.raw.json", res["body"])
    books = data.get("bookmakers") or []
    outs = [(b_.get("key"), o) for b_ in books for m in b_.get("markets") or [] if m.get("key") == "player_reception_yds" for o in m.get("outcomes") or []]
    players = {o.get("description") for _, o in outs if o.get("description")}
    game = PM.match_game(e, board.get("games") or [])
    matched = {p for p in players if game and PM.match_player(p, game, {})[0]} if game else set()
    per = {}
    for bk, o in outs:
        per.setdefault(o.get("description"), set()).add(bk)
    ups = [m.get("last_update") for b_ in books for m in b_.get("markets") or [] if m.get("key") == "player_reception_yds" and m.get("last_update")]
    pts = [o.get("point") for _, o in outs if o.get("point") is not None]
    return {"game_date": gdate, "starts": e["commence_time"], "credits_billed": cost, "credits_remaining_after": remaining,
            "budget_before": b, "bookmakers": len(books), "outcomes": len(outs), "players": len(players),
            "board_game_found": bool(game), "players_matched_to_board": len(matched),
            "books_per_player": [min(len(v) for v in per.values()), max(len(v) for v in per.values())] if per else None,
            "has_lines": bool(pts), "has_prices": all("price" in o for _, o in outs) if outs else False,
            "has_book_names": all(b_.get("title") for b_ in books) if books else False, "has_timestamps": bool(ups),
            "half_point_lines": all(abs(p % 1 - 0.5) < 1e-9 for p in pts) if pts else None,
            "stored": {"raw_bytes": raw["bytes"], "verified": raw["verified"]}}


if __name__ == "__main__":
    raise SystemExit(main())
