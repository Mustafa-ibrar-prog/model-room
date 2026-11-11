"""Permanent, append-only store for sportsbook line snapshots: the Supabase table odds.snapshots (TEST site).

The repository is public, and The Odds API's terms allow storing and displaying its data but not offering it as
downloadable files, so snapshots are kept in the database, not in git. The workflow:

  load    rebuild data/processed/<league>/market_snapshots.parquet from the table (start of a refresh)
  sync    insert every row of that parquet file the table doesn't have yet (after a collection); never updates
  verify  recompute each league's hash chain and check every typed column against the stored payload
  import  one-time: move the snapshots previously kept on the preview branch into the table, labelled as such

Each row's payload is the canonical JSON of the snapshot exactly as collected (provider fields, our collection
time, the provider-response fingerprint). row_hash = sha256(prev_hash + payload); the first row of a league
chains from 64 zeros. The table refuses UPDATE, DELETE and TRUNCATE (migration 20261111000100).

Connection: MODELROOM_ODDS_DB_URL (a Postgres URL; the workflow sets it from the SUPABASE_DB_URL secret and masks
it). Nothing here prints the URL.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from modelroom.common.paths import ensure, processed_dir

from .odds import COLUMNS

GENESIS = "0" * 64
PAYLOAD_FIELDS = COLUMNS + ["raw_sha256"]
KEY_FIELDS = ["source", "sportsbook", "home_team", "away_team", "commence_time", "market", "captured_at", "collected_at"]
TYPED = ["game_id", "home_team", "away_team", "commence_time", "sportsbook", "market", "line", "home_price",
         "away_price", "over_price", "under_price", "captured_at", "collected_at", "source"]
NUM = {"line", "home_price", "away_price", "over_price", "under_price"}
TS = {"commence_time", "captured_at", "collected_at"}


class StoreError(RuntimeError):
    pass


# ------------------------------------------------------------------ canonical form (pure, unit-tested)
def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return pd.Timestamp(v).isoformat()
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
        if isinstance(v, float) and math.isnan(v):
            return None
    if isinstance(v, float):
        return float(v)
    if isinstance(v, (int, bool)):
        return v
    return str(v)


def payload_of(row: dict) -> str:
    """Canonical JSON of one snapshot row (all collected fields; missing fields as null)."""
    d = {k: _clean(row.get(k)) for k in PAYLOAD_FIELDS}
    for k in NUM:
        if isinstance(d[k], int):
            d[k] = float(d[k])
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_key(p: dict) -> str:
    return "|".join("" if p.get(k) is None else str(p[k]) for k in KEY_FIELDS)


def chain(prev: str, payload: str) -> str:
    return hashlib.sha256((prev + payload).encode("utf-8")).hexdigest()


def rows_from_frame(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        p = payload_of(r)
        out.append({"payload": p, "data": json.loads(p)})
    return out


def frame_from_payloads(payloads: list[str]) -> pd.DataFrame:
    if not payloads:
        return pd.DataFrame(columns=PAYLOAD_FIELDS)
    df = pd.DataFrame([json.loads(p) for p in payloads])[PAYLOAD_FIELDS]
    for k in NUM:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    return df


def verify_rows(rows: list[dict]) -> dict:
    """rows: one league's table rows ordered by seq, each with seq, payload, prev_hash, row_hash, content_key and the
    typed columns. Returns {"rows": n, "ok": bool, "problems": [...] (first 20)}."""
    problems, prev = [], GENESIS
    for i, r in enumerate(rows, start=1):
        if r["seq"] != i:
            problems.append(f"seq {r['seq']} at position {i}")
        if r["prev_hash"] != prev:
            problems.append(f"seq {r['seq']}: prev_hash does not match the previous row")
        if chain(r["prev_hash"], r["payload"]) != r["row_hash"]:
            problems.append(f"seq {r['seq']}: row_hash does not match its payload")
        d = json.loads(r["payload"])
        if content_key(d) != r["content_key"]:
            problems.append(f"seq {r['seq']}: content_key does not match payload")
        for k in TYPED:
            a, b = d.get(k), r.get(k)
            if k in TS:
                a = None if a is None else pd.Timestamp(a)
                b = None if b is None else pd.Timestamp(b)
                if (a is None) != (b is None) or (a is not None and a != b):
                    problems.append(f"seq {r['seq']}: {k} differs from payload")
            elif k in NUM:
                if (a is None) != (b is None) or (a is not None and abs(float(a) - float(b)) > 1e-9):
                    problems.append(f"seq {r['seq']}: {k} differs from payload")
            elif (a is None) != (b is None) or (a is not None and str(a) != str(b)):  # text columns (NBA game ids are numbers in payload)
                problems.append(f"seq {r['seq']}: {k} differs from payload")
        prev = r["row_hash"]
    return {"rows": len(rows), "ok": not problems, "problems": problems[:20], "head": prev if rows else None}


# ------------------------------------------------------------------ database
def connect(url: str | None = None):
    url = url or os.environ.get("MODELROOM_ODDS_DB_URL")
    if not url:
        raise StoreError("MODELROOM_ODDS_DB_URL is not set")
    import psycopg  # installed by the workflow (psycopg[binary])
    return psycopg.connect(url, connect_timeout=15)


SELECT = ("select seq, payload, prev_hash, row_hash, content_key, " + ", ".join(TYPED) +
          " from odds.snapshots where league = %s order by seq")


def _rows(cur, league: str) -> list[dict]:
    cur.execute(SELECT, (league,))
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def insert(conn, league: str, df: pd.DataFrame, batch: str, run_id: str | None = None) -> dict:
    """Append rows the table doesn't have (by content key); never updates. One transaction, league chain locked."""
    new = rows_from_frame(df)
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"odds.snapshots.{league}",))
        cur.execute("select content_key from odds.snapshots where league = %s", (league,))
        have = {r[0] for r in cur.fetchall()}
        cur.execute("select seq, row_hash from odds.snapshots where league = %s order by seq desc limit 1", (league,))
        last = cur.fetchone()
        seq, prev = (last[0], last[1]) if last else (0, GENESIS)
        added, seen = 0, set()
        for r in new:
            d = r["data"]
            k = content_key(d)
            if k in have or k in seen:
                continue
            seen.add(k)
            seq += 1
            h = chain(prev, r["payload"])
            vals = [None if d.get(c) is None else d.get(c) for c in TYPED]
            cur.execute(
                "insert into odds.snapshots (league, seq, content_key, payload, prev_hash, row_hash, batch, run_id, raw_sha256, "
                + ", ".join(TYPED) + ") values (" + ", ".join(["%s"] * (9 + len(TYPED))) + ")",
                [league, seq, k, r["payload"], prev, h, batch, run_id, d.get("raw_sha256")] + vals)
            prev = h
            added += 1
    return {"league": league, "offered": len(new), "inserted": added, "already_stored": len(new) - added}


def load(conn, league: str) -> pd.DataFrame:
    cur = conn.cursor()
    cur.execute("select payload from odds.snapshots where league = %s order by seq", (league,))
    return frame_from_payloads([r[0] for r in cur.fetchall()])


def verify(conn, league: str) -> dict:
    return verify_rows(_rows(conn.cursor(), league)) | {"league": league}


# ------------------------------------------------------------------ CLI helpers (used by the workflow)
def parquet_path(league: str) -> Path:
    return ensure(processed_dir(league)) / "market_snapshots.parquet"


def cmd(action: str, league: str, path: str | None = None, batch: str | None = None) -> dict:
    run_id = os.environ.get("GITHUB_RUN_ID")
    conn = connect()
    try:
        if action == "load":
            df = load(conn, league)
            f = parquet_path(league)
            if len(df):
                df.to_parquet(f, index=False)
            return {"league": league, "action": "load", "rows": len(df), "written": str(f) if len(df) else None}
        if action == "sync":
            f = Path(path) if path else parquet_path(league)
            if not f.exists():
                return {"league": league, "action": "sync", "inserted": 0, "note": "no local snapshots"}
            res = insert(conn, league, pd.read_parquet(f), batch or "collection", run_id)
            return res | {"action": "sync", "verify": verify(conn, league)}
        if action == "import":
            f = Path(path)
            res = insert(conn, league, pd.read_parquet(f), batch or "import", run_id)
            return res | {"action": "import", "verify": verify(conn, league)}
        if action == "verify":
            return verify(conn, league)
        raise StoreError(f"unknown action {action}")
    finally:
        conn.close()
