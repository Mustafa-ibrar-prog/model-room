"""`python -m modelroom archive dryrun|run|verify` (TEST). dryrun writes under the dryrun/ prefix; nothing in Supabase or
Git is changed or deleted by any mode. Prints counts, ranges, checksums and problems only (no payloads, no secrets)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from modelroom.sources import odds_store as S

from . import audit, ledgers, odds
from .store import from_env

TABLES = ("snapshots", "comparisons", "reports")
LEAGUES = ("nba", "nfl")


def main(mode: str, local_root: str | None, ledger_dir: str | None, include_audit: bool) -> dict:
    prefix = "dryrun/v1" if mode == "dryrun" else "v1"
    store = from_env(local_root)
    out = {"mode": mode, "store": store.kind, "prefix": prefix, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "odds": [], "odds_verify": [], "ledgers": None, "ledgers_verify": None, "audit": None, "ok": True}
    run_id = os.environ.get("GITHUB_RUN_ID")
    conn = S.connect() if os.environ.get("MODELROOM_ODDS_DB_URL") else None
    try:
        if conn is not None:
            for t in TABLES:
                for lg in LEAGUES:
                    if mode != "verify":
                        r = odds.archive_table(conn, store, prefix, t, lg, run_id=run_id)
                        out["odds"].append({k: v for k, v in r.items() if k not in ("index_rows",)} | {"new_segments": len(r["new_segments"])})
                        out["ok"] &= not r["problems"]
                    v = odds.verify_archive(store, prefix, t, lg, conn)
                    out["odds_verify"].append(v)
                    out["ok"] &= v["ok"]
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
