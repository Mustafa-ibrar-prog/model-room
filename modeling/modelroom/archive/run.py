"""`python -m modelroom archive dryrun|run|verify` (TEST). dryrun writes under the dryrun/ prefix; nothing in Supabase or
Git is changed or deleted by any mode. Prints counts, ranges, checksums and problems only (no payloads, no secrets)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from modelroom.sources import odds_store as S

from . import audit, ledgers, odds
from .store import from_env, sha256

TABLES = ("snapshots", "comparisons", "reports")
LEAGUES = ("nba", "nfl")


def check(store) -> dict:
    """Access and privacy probe, no Supabase: write, read back and delete one tiny object; an unsigned request for it
    must be refused. 1 Class A (PUT) + 2 Class B (GET, HEAD) operations; DeleteObject is free."""
    key = f"_probe/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.txt"
    body = b"model-room archive access probe"
    out = {"store": store.kind, "write": False, "read_back": False, "anonymous_status": None, "private": None, "deleted": False}
    put = store.put(key, body)
    out["write"] = True
    out["read_back"] = store.get(key) == body and put["sha256"] == sha256(body)
    if hasattr(store, "anonymous_status"):
        st = store.anonymous_status(key)
        out["anonymous_status"], out["private"] = st, 400 <= st < 500
    store.delete(key)
    out["deleted"] = not store.exists(key)
    out["ok"] = out["write"] and out["read_back"] and out["private"] is not False and out["deleted"]
    return out


def record_index(conn, rows: list[dict], run_id: str | None) -> dict:
    """Pointers and checksums into archive.objects (append-only). Skipped, with a note, if the table isn't there yet."""
    if not rows:
        return {"inserted": 0}
    cur = conn.cursor()
    cur.execute("select to_regclass('archive.objects') is not null")
    if not S._fetchone(cur)[0]:
        return {"inserted": 0, "note": "archive.objects not created yet (migration 20261124000100 not applied)"}
    cols = ["dataset", "league", "object_key", "seq_first", "seq_last", "rows", "first_prev_hash", "last_row_hash", "date_first",
            "date_last", "bytes", "sha256", "format", "run_id"]
    n = 0
    with conn.transaction():
        for r in rows:
            cur.execute(f"insert into archive.objects ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) on conflict (object_key, sha256) do nothing",
                        [r.get(c) if c != "run_id" else run_id for c in cols])
            n += cur.rowcount
    return {"inserted": n}


def main(mode: str, local_root: str | None, ledger_dir: str | None, include_audit: bool, use_supabase: bool = True) -> dict:
    store = from_env(local_root)
    if mode == "check":
        return {"mode": "check", **check(store)}
    prefix = "dryrun/v1" if mode == "dryrun" else "v1"
    out = {"mode": mode, "store": store.kind, "prefix": prefix, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "odds": [], "odds_verify": [], "ledgers": None, "ledgers_verify": None, "audit": None, "ok": True}
    run_id = os.environ.get("GITHUB_RUN_ID")
    conn = S.connect() if use_supabase and os.environ.get("MODELROOM_ODDS_DB_URL") else None
    out["supabase"] = "read" if conn is not None else "not read"
    index_rows = []
    try:
        if conn is not None:
            for t in TABLES:
                for lg in LEAGUES:
                    if mode != "verify":
                        r = odds.archive_table(conn, store, prefix, t, lg, run_id=run_id)
                        index_rows += r["index_rows"]
                        out["odds"].append({k: v for k, v in r.items() if k not in ("index_rows",)} | {"new_segments": len(r["new_segments"])})
                        out["ok"] &= not r["problems"]
                    v = odds.verify_archive(store, prefix, t, lg, conn)
                    out["odds_verify"].append(v)
                    out["ok"] &= v["ok"]
            if mode == "run":                                       # dry runs never touch the index
                out["index"] = record_index(conn, index_rows, run_id)
            if include_audit and mode != "verify":
                out["audit"] = audit.archive_days(conn, store, prefix)
                out["ok"] &= not out["audit"]["problems"]
        if ledger_dir:
            if mode != "verify":
                out["ledgers"] = ledgers.archive_ledgers(store, prefix, Path(ledger_dir))
                out["ok"] &= not out["ledgers"]["problems"]
            out["ledgers_verify"] = ledgers.verify_ledgers(store, prefix)
            out["ok"] &= out["ledgers_verify"]["ok"]
    finally:
        if conn is not None:
            conn.close()
    out["supabase_bytes_read"] = S.bytes_read()
    return out
