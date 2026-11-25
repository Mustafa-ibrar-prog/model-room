"""Private R2 storage for live market snapshots: NBA player points from The Odds API (TEST; Moose 2026-11-24).
Separate from the historical ledger archive (v1/ledgers/) and from archive reads (MODELROOM_ARCHIVE_READ stays off).

    v1/market-snapshots/nba/player-points/{YYYY-MM-DD}/                  game date, Pacific
        {event_id}/{capture_ts}.raw.json     exact provider response bytes                      write-once
        {event_id}/{capture_ts}.rows.jsonl   one row per book x player x line                    write-once
        manifest-{run_ts}.json               this run: objects (key, bytes, sha256), games requested/skipped and
                                             why, credits before/after, prev_manifest_sha256 (chain)  write-once
        view-{run_ts}.json                   compact main-line view of every game captured that day  write-once
        latest.json                          pointer to the newest manifest and view (the ONLY object replaced)
    v1/market-snapshots/nba/player-points/_usage/{YYYY-MM}/{run_ts}.json   credit log per run (no odds)   write-once

Every write-once object is read back with the READ-ONLY token and its size and SHA-256 compared before the manifest
records it. Nothing is deleted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .store import ArchiveError, sha256

PREFIX = "v1/market-snapshots/nba/player-points"


def day_prefix(date: str) -> str:
    return f"{PREFIX}/{date}"


def stamp(t: datetime | None = None) -> str:
    return (t or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def put_verified(store, reader, key: str, body: bytes, retries: int = 3) -> dict:
    """Write once, then read back with the read-only token: size and SHA-256 must match. Retries the upload (never the
    provider request). A key that already exists with the same bytes counts as done."""
    last = None
    for _ in range(retries):
        try:
            put = store.put_once(key, body)
        except ArchiveError as e:
            if "already exists" in str(e) and sha256(reader.get(key)) == sha256(body):
                put = {"key": key, "bytes": len(body), "sha256": sha256(body)}
            else:
                last = e
                continue
        except Exception as e:  # noqa: BLE001  transient upload error: try again
            last = e
            continue
        back = reader.get(key)
        if len(back) == len(body) and sha256(back) == put["sha256"]:
            return {**put, "verified": True}
        last = ArchiveError(f"read-back differs for {key}")
    raise ArchiveError(f"upload failed after {retries} attempts: {type(last).__name__}")


def read_latest(reader, date: str) -> dict | None:
    k = f"{day_prefix(date)}/latest.json"
    try:
        return json.loads(reader.get(k))
    except Exception:  # noqa: BLE001  first run of the day
        return None


def write_run(store, reader, date: str, run_ts: str, objects: list[dict], game_views: list[dict], meta: dict) -> dict:
    """Manifest (chained to the day's previous one) + merged view + latest pointer, after every capture is verified."""
    latest = read_latest(reader, date)
    prev_view = json.loads(reader.get(latest["view"])) if latest else {"date": date, "games": {}}
    games = dict(prev_view.get("games", {}))
    for v in game_views:
        if v.get("game_id"):
            games[v["game_id"]] = v
    view = {"date": date, "updated_at": meta.get("finished_at"), "source": "the_odds_api", "market": "player_points",
            "regions": "us", "games": games}
    vkey = f"{day_prefix(date)}/view-{run_ts}.json"
    vput = put_verified(store, reader, vkey, json.dumps(view, sort_keys=True, separators=(",", ":")).encode())
    manifest = {"date": date, "run_ts": run_ts, **meta, "objects": objects + [{"key": vkey, "bytes": vput["bytes"], "sha256": vput["sha256"], "kind": "view"}],
                "prev_manifest": latest["manifest"] if latest else None, "prev_manifest_sha256": latest["manifest_sha256"] if latest else None}
    mkey = f"{day_prefix(date)}/manifest-{run_ts}.json"
    mbody = json.dumps(manifest, sort_keys=True, indent=1).encode()
    mput = put_verified(store, reader, mkey, mbody)
    pointer = {"date": date, "manifest": mkey, "manifest_sha256": mput["sha256"], "view": vkey, "view_sha256": vput["sha256"], "updated_at": meta.get("finished_at")}
    store.put(f"{day_prefix(date)}/latest.json", json.dumps(pointer, sort_keys=True).encode())
    if json.loads(reader.get(f"{day_prefix(date)}/latest.json")) != pointer:
        raise ArchiveError("latest.json read-back differs")
    return {"manifest": mkey, "view": vkey, "games_in_view": len(games)}


def verify_day(reader, date: str) -> dict:
    """Walk the day's manifest chain from latest.json back to the first run; re-hash every object it lists."""
    latest = read_latest(reader, date)
    if not latest:
        return {"date": date, "ok": True, "runs": 0, "objects": 0, "problems": []}
    problems, runs, objs = [], 0, 0
    key, want = latest["manifest"], latest["manifest_sha256"]
    seen = set()
    while key and key not in seen:
        seen.add(key)
        body = reader.get(key)
        if sha256(body) != want:
            problems.append(f"{key}: manifest checksum differs from the chain")
            break
        m = json.loads(body)
        runs += 1
        for o in m["objects"]:
            objs += 1
            try:
                b = reader.get(o["key"])
                if len(b) != o["bytes"] or sha256(b) != o["sha256"]:
                    problems.append(f"{o['key']}: size or checksum differs")
            except Exception as e:  # noqa: BLE001
                problems.append(f"{o['key']}: unreadable ({type(e).__name__})")
        key, want = m.get("prev_manifest"), m.get("prev_manifest_sha256")
    if sha256(reader.get(latest["view"])) != latest["view_sha256"]:
        problems.append("latest view checksum differs")
    return {"date": date, "ok": not problems, "runs": runs, "objects": objs, "problems": problems[:20]}
