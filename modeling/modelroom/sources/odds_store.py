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
from datetime import datetime, timezone
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
# Egress (Moose, 2026-11-23): every byte a query returns counts against the TEST project's transfer quota. Reads go
# through _fetchall/_fetchone so each command reports exactly how much it downloaded, and integrity checks that
# need every historical row run INSIDE the database (server_check), returning only a summary. Nothing here weakens
# a check: each one still recomputes every row's hash from its payload, every link, every seq and every typed copy.
_READ = {"bytes": 0, "rows": 0, "queries": 0}


def _size(v) -> int:
    if v is None:
        return 0
    if isinstance(v, str):
        return len(v.encode("utf-8"))
    if isinstance(v, (bytes, bytearray, memoryview)):
        return len(v)
    return 8


def _fetchall(cur) -> list:
    rows = cur.fetchall()
    _READ["queries"] += 1
    _READ["rows"] += len(rows)
    _READ["bytes"] += sum(_size(v) for r in rows for v in r)
    return rows


def _fetchone(cur):
    r = cur.fetchone()
    _READ["queries"] += 1
    if r is not None:
        _READ["rows"] += 1
        _READ["bytes"] += sum(_size(v) for v in r)
    return r


def bytes_read() -> dict:
    return dict(_READ)


def connect(url: str | None = None):
    url = url or os.environ.get("MODELROOM_ODDS_DB_URL")
    if not url:
        raise StoreError("MODELROOM_ODDS_DB_URL is not set")
    import psycopg  # installed by the workflow (psycopg[binary])
    # autocommit: each `with conn.transaction()` is then a real BEGIN ... COMMIT. Without it, a read before the insert
    # opens an implicit transaction, the block becomes a savepoint, and closing the connection rolls the insert back.
    return psycopg.connect(url, connect_timeout=15, autocommit=True)


TABLES = ("snapshots", "comparisons", "reports")
SELECT = ("select seq, payload, prev_hash, row_hash, content_key, " + ", ".join(TYPED) +
          " from odds.snapshots where league = %s order by seq")


def _table(t: str) -> str:
    if t not in TABLES:
        raise StoreError(f"unknown table {t}")
    return t


def _rows(cur, league: str) -> list[dict]:
    cur.execute(SELECT, (league,))
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in _fetchall(cur)]


def missing_keys(cur, table: str, league: str, keys) -> set[str]:
    """Which of these content keys the table does NOT have yet. Only the missing keys come back (a handful per
    refresh), instead of downloading every stored key to compare locally."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return set()
    cur.execute(f"select k from unnest(%s::text[]) as k except select content_key from odds.{_table(table)} where league = %s",
                (keys, league))
    return {r[0] for r in _fetchall(cur)}


def _head(cur, table: str, league: str) -> tuple[int, str]:
    cur.execute(f"select seq, row_hash from odds.{_table(table)} where league = %s order by seq desc limit 1", (league,))
    last = _fetchone(cur)
    return (last[0], last[1]) if last else (0, GENESIS)


def insert(conn, league: str, df: pd.DataFrame, batch: str, run_id: str | None = None) -> dict:
    """Append rows the table doesn't have (by content key); never updates. One transaction, league chain locked.
    Returns the inserted rows' seq / row_hash / payload so callers never have to read them back."""
    new = rows_from_frame(df)
    added_rows = []
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"odds.snapshots.{league}",))
        missing = missing_keys(cur, "snapshots", league, [content_key(r["data"]) for r in new])
        seq, prev = _head(cur, "snapshots", league)
        start = (seq, prev)
        seen = set()
        for r in new:
            d = r["data"]
            k = content_key(d)
            if k not in missing or k in seen:
                continue
            seen.add(k)
            seq += 1
            h = chain(prev, r["payload"])
            vals = [None if d.get(c) is None else d.get(c) for c in TYPED]
            cur.execute(
                "insert into odds.snapshots (league, seq, content_key, payload, prev_hash, row_hash, batch, run_id, raw_sha256, "
                + ", ".join(TYPED) + ") values (" + ", ".join(["%s"] * (9 + len(TYPED))) + ")",
                [league, seq, k, r["payload"], prev, h, batch, run_id, d.get("raw_sha256")] + vals)
            added_rows.append({"seq": seq, "row_hash": h, "payload": r["payload"]})
            prev = h
    return {"league": league, "offered": len(new), "inserted": len(added_rows), "already_stored": len(new) - len(added_rows),
            "start": {"seq": start[0], "row_hash": start[1]}, "head": {"seq": seq, "row_hash": prev}, "rows_added": added_rows}


def _archived_payloads(league: str) -> list[str]:
    """Closed snapshot segments from the private R2 archive (MODELROOM_ARCHIVE_READ=on and R2 settings present), seq 1..k
    in order, each object checked against its manifest SHA-256. Any problem -> [] (the caller reads Supabase instead)."""
    if os.environ.get("MODELROOM_ARCHIVE_READ") != "on":
        return []
    try:
        from modelroom.archive import odds as AO
        from modelroom.archive.store import from_env
        df = AO.load_archived(from_env(None), "v1", "snapshots", league)
        if not len(df) or list(df["seq"]) != list(range(1, len(df) + 1)):
            return []
        return list(df["payload"])
    except Exception as e:  # noqa: BLE001
        print(f"archive not used for {league} snapshots ({type(e).__name__}); reading Supabase", flush=True)
        return []


def load_with_hashes(conn, league: str, use_archive: bool = True) -> pd.DataFrame:
    """All snapshots of a league, plus each row's seq and row_hash, from ONE read of the payloads: closed segments from
    the private archive when available, the rest (seq beyond them) from Supabase. The chain is recomputed here from
    genesis over every payload; `server_check` on the same connection proves the result ends at the stored head (the
    load command falls back to a full Supabase read if it doesn't)."""
    arch = _archived_payloads(league) if use_archive else []
    cur = conn.cursor()
    cur.execute("select payload from odds.snapshots where league = %s and seq > %s order by seq", (league, len(arch)))
    payloads = arch + [r[0] for r in _fetchall(cur)]
    hashes, prev = [], GENESIS
    for p in payloads:
        prev = chain(prev, p)
        hashes.append(prev)
    df = frame_from_payloads(payloads)
    df.insert(0, "snapshot_hash", hashes)
    df.insert(0, "snapshot_seq", list(range(1, len(payloads) + 1)))
    return df


def load(conn, league: str) -> pd.DataFrame:
    """The model input: snapshot fields only (same frame as before), from the same single read."""
    return load_with_hashes(conn, league)[PAYLOAD_FIELDS]


# Server-side integrity check: the database recomputes sha256(prev_hash || payload) for EVERY row, checks every
# link to the previous row, that seq runs 1..n with nothing missing, and (snapshots) every content key and typed
# copy against the payload, and returns only counts, the first bad seq and the head. Same checks as verify_rows /
# verify_payload_rows, without downloading the history.
_CHAIN_SQL = """
with t as materialized (
  select seq, prev_hash, row_hash, {extra_cols}
         encode(sha256(convert_to(prev_hash || payload, 'UTF8')), 'hex') as calc,
         row_number() over (order by seq) as rn,
         lag(row_hash) over (order by seq) as before
  from odds.{table} where league = %(league)s),
b as (
  select seq, row_hash, seq <> rn as seq_bad, prev_hash <> coalesce(before, %(genesis)s) as link_bad,
         calc <> row_hash as hash_bad, {extra_bad} as typed_bad
  from t)
select count(*),
       coalesce(max(seq), 0),
       count(*) filter (where seq_bad),
       count(*) filter (where link_bad),
       count(*) filter (where hash_bad),
       count(*) filter (where typed_bad),
       min(seq) filter (where seq_bad or link_bad or hash_bad or typed_bad),
       (select row_hash from b order by seq desc limit 1),
       (select row_hash from b where seq = %(anchor_seq)s)
from b
"""
# snapshots: content_key = "|".join of KEY_FIELDS ("" for null) and every typed column equal to its payload field
_SNAP_EXTRA_COLS = "content_key, j, " + ", ".join(TYPED) + ","
_J = "payload::jsonb"


def _snap_typed_bad() -> str:
    key = " || '|' || ".join(f"coalesce(j->>'{k}', '')" for k in KEY_FIELDS)
    parts = [f"content_key is distinct from ({key})"]
    for k in TYPED:
        if k in TS:
            parts.append(f"{k} is distinct from (j->>'{k}')::timestamptz")
        elif k in NUM:
            parts.append(f"((j->>'{k}') is null) <> ({k} is null) or abs((j->>'{k}')::float8 - {k}) > 1e-9")
        else:
            parts.append(f"{k} is distinct from (j->>'{k}')")
    return "(" + " or ".join(f"coalesce(({p}), false)" for p in parts) + ")"


def _chain_sql(table: str) -> str:
    if table == "snapshots":
        inner = _CHAIN_SQL.replace("from odds.{table} where", "from (select *, " + _J + " as j from odds.snapshots) s where")
        return inner.format(table="snapshots", extra_cols=_SNAP_EXTRA_COLS, extra_bad=_snap_typed_bad())
    return _CHAIN_SQL.format(table=_table(table), extra_cols="", extra_bad="false")


def server_check(conn, table: str, league: str, anchor: dict | None = None) -> dict:
    """Full chain verification computed by the database; returns the same shape as verify_rows.
    anchor = {"seq", "row_hash"} from the last verified checkpoint: the row at that seq must still carry exactly that
    hash (so the history up to it can't have been rewritten, even consistently) and the table can't be shorter."""
    cur = conn.cursor()
    a_seq = int(anchor["seq"]) if anchor and anchor.get("seq") else 0
    cur.execute(_chain_sql(_table(table)), {"league": league, "genesis": GENESIS, "anchor_seq": a_seq})
    n, max_seq, seq_bad, link_bad, hash_bad, typed_bad, first_bad, head, at_anchor = _fetchone(cur)
    problems = []
    if seq_bad:
        problems.append(f"{seq_bad} row(s) out of sequence: a row is missing or reordered (first at seq {first_bad})")
    if link_bad:
        problems.append(f"{link_bad} row(s) whose prev_hash does not match the previous row (first at seq {first_bad})")
    if hash_bad:
        problems.append(f"{hash_bad} row(s) whose row_hash does not match their payload (first at seq {first_bad})")
    if typed_bad:
        problems.append(f"{typed_bad} row(s) whose content_key or typed columns differ from the payload (first at seq {first_bad})")
    if a_seq:
        if max_seq < a_seq or n < a_seq:
            problems.append(f"table has {n} row(s), fewer than the verified checkpoint at seq {a_seq}: rows were removed")
        elif at_anchor != anchor.get("row_hash"):
            problems.append(f"the row at checkpoint seq {a_seq} no longer carries the verified hash: history was rewritten")
    return {"rows": int(n), "ok": not problems, "problems": problems[:20], "head": head if n else None,
            "max_seq": int(max_seq), "mode": "server", "table": table, "league": league,
            "anchor": {"seq": a_seq, "ok": not a_seq or (max_seq >= a_seq and at_anchor == anchor.get("row_hash"))}}


def verify(conn, league: str) -> dict:
    """Client-side full verification of the snapshot chain (downloads every row: used by the manual full check)."""
    return verify_rows(_rows(conn.cursor(), league)) | {"league": league}


# ------------------------------------------------------------------ verification checkpoints (the trust anchor)
# preview-ledger/reports/store_checkpoints.json keeps, per table and league, the seq and row_hash of the last row
# that passed a full verification. Committed with each refresh (git history = an external, append-only record of
# every verified head). Hashes and counts only: no payloads, lines, prices or sportsbook names. A check that fails
# never advances it, and it only ever moves forward.
def checkpoint_path() -> Path:
    return Path(os.environ.get("MODELROOM_LEDGER_DIR", "preview-ledger")) / "reports" / "store_checkpoints.json"


def read_checkpoints() -> dict:
    f = checkpoint_path()
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {}


def anchor_for(cps: dict, table: str, league: str) -> dict | None:
    return (cps.get(table) or {}).get(league)


def advance_checkpoint(table: str, league: str, check: dict, by: str) -> dict:
    """Record the verified head. Refuses to move backwards or to record a failed check."""
    cps = read_checkpoints()
    old = anchor_for(cps, table, league)
    if not check.get("ok") or not check.get("rows"):
        return {"advanced": False, "reason": "check failed" if not check.get("ok") else "empty table"}
    if old and int(old.get("seq", 0)) > check["max_seq"]:
        return {"advanced": False, "reason": "checkpoint is ahead of the table"}
    cps.setdefault(table, {})[league] = {"seq": check["max_seq"], "row_hash": check["head"],
                                         "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": by}
    cps["_note"] = ("Last fully verified row per table and league (seq and row_hash only). The next check requires the row "
                    "at that seq to carry exactly this hash. Integrity anchor for odds.snapshots / comparisons / reports.")
    f = checkpoint_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cps, indent=1, sort_keys=True))
    return {"advanced": True, "seq": check["max_seq"]}


def check_and_advance(conn, table: str, league: str, by: str) -> dict:
    cps = read_checkpoints()
    res = server_check(conn, table, league, anchor_for(cps, table, league))
    res["checkpoint"] = advance_checkpoint(table, league, res, by)
    return res


# ------------------------------------------------------------------ derived records (odds.comparisons, odds.reports)
# Same guarantees as odds.snapshots: canonical JSON payload, per-league hash chain, insert-only (migration 20261111000200).
DERIVED = {"comparisons", "reports"}


def canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def insert_payloads(conn, table: str, league: str, items: list[tuple[str, dict]], batch: str, run_id: str | None = None) -> dict:
    """items: (content_key, record). Appends records whose key the table doesn't have; never updates."""
    if table not in DERIVED:
        raise StoreError(f"unknown table {table}")
    added, last_hash = 0, None
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"odds.{table}.{league}",))
        missing = missing_keys(cur, table, league, [k for k, _ in items])
        seq, prev = _head(cur, table, league)
        done = set()
        for k, rec in items:
            if k not in missing or k in done:
                continue
            done.add(k)
            p = canonical(rec)
            seq += 1
            h = chain(prev, p)
            cur.execute(f"insert into odds.{table} (league, seq, content_key, payload, prev_hash, row_hash, batch, run_id) "
                        "values (%s, %s, %s, %s, %s, %s, %s, %s)", (league, seq, k, p, prev, h, batch, run_id))
            prev = h
            added += 1
    return {"table": table, "league": league, "offered": len(items), "inserted": added, "head": {"seq": seq, "row_hash": prev}}


def verify_payload_rows(rows: list[dict]) -> dict:
    problems, prev = [], GENESIS
    for i, r in enumerate(rows, start=1):
        if r["seq"] != i:
            problems.append(f"seq {r['seq']} at position {i}")
        if r["prev_hash"] != prev:
            problems.append(f"seq {r['seq']}: prev_hash does not match the previous row")
        if chain(r["prev_hash"], r["payload"]) != r["row_hash"]:
            problems.append(f"seq {r['seq']}: row_hash does not match its payload")
        prev = r["row_hash"]
    return {"rows": len(rows), "ok": not problems, "problems": problems[:20], "head": prev if rows else None}


def verify_table(conn, table: str, league: str) -> dict:
    """Client-side full verification of a derived table (downloads every row: manual full check only)."""
    if table not in DERIVED:
        raise StoreError(f"unknown table {table}")
    cur = conn.cursor()
    cur.execute(f"select seq, payload, prev_hash, row_hash from odds.{table} where league = %s order by seq", (league,))
    cols = [c.name for c in cur.description]
    return verify_payload_rows([dict(zip(cols, r)) for r in _fetchall(cur)]) | {"league": league, "table": table}


def verify_after_reconnect(league: str, url: str | None = None) -> dict:
    """Chain checks on a fresh connection: what a later reader sees, i.e. only committed rows (computed in the database)."""
    c = connect(url)
    try:
        cps = read_checkpoints()
        return {t: server_check(c, t, league, anchor_for(cps, t, league)) for t in TABLES}
    finally:
        c.close()


def load_payloads(conn, table: str, league: str) -> list[dict]:
    if table not in DERIVED:
        raise StoreError(f"unknown table {table}")
    cur = conn.cursor()
    cur.execute(f"select payload from odds.{table} where league = %s order by seq", (league,))
    return [json.loads(r[0]) for r in _fetchall(cur)]


# ------------------------------------------------------------------ local copy for the rest of this refresh
# `load` writes the snapshots it read (with their computed seq / hash) next to the model input, so `sync` and the
# sportsbook analysis reuse them instead of downloading the history again. data/ is git-ignored: never committed.
def parquet_path(league: str) -> Path:
    return ensure(processed_dir(league)) / "market_snapshots.parquet"


def local_store_path(league: str) -> Path:
    return ensure(processed_dir(league)) / "market_snapshots_store.parquet"


def local_head(league: str) -> dict | None:
    f = local_store_path(league)
    if not f.exists():
        return None
    df = pd.read_parquet(f, columns=["snapshot_seq", "snapshot_hash"])
    if not len(df):
        return {"seq": 0, "row_hash": GENESIS}
    return {"seq": int(df["snapshot_seq"].iloc[-1]), "row_hash": str(df["snapshot_hash"].iloc[-1])}


def local_snapshots(conn, league: str) -> pd.DataFrame:
    """This refresh's copy if it matches the table's head (cheap one-row query), else one full read."""
    f = local_store_path(league)
    if f.exists():
        head = _head(conn.cursor(), "snapshots", league)
        mine = local_head(league)
        if mine and (mine["seq"], mine["row_hash"]) == head:
            return pd.read_parquet(f)
    df = load_with_hashes(conn, league)
    df.to_parquet(f, index=False)
    return df


# ------------------------------------------------------------------ CLI helpers (used by the workflow)
def cmd(action: str, league: str, path: str | None = None, batch: str | None = None) -> dict:
    run_id = os.environ.get("GITHUB_RUN_ID")
    conn = connect()
    try:
        if action == "load":
            df = load_with_hashes(conn, league)
            check = check_and_advance(conn, "snapshots", league, "refresh load")
            same = lambda d: (int(d["snapshot_seq"].iloc[-1]), str(d["snapshot_hash"].iloc[-1])) == (check["max_seq"], check["head"]) if len(d) else True
            if not same(df) and os.environ.get("MODELROOM_ARCHIVE_READ") == "on":
                print(f"archived {league} snapshots don't reproduce the stored head; reading everything from Supabase", flush=True)
                df = load_with_hashes(conn, league, use_archive=False)
            # the hashes computed from the downloaded payloads must end exactly at the stored head
            if len(df) and (int(df["snapshot_seq"].iloc[-1]), str(df["snapshot_hash"].iloc[-1])) != (check["max_seq"], check["head"]):
                check["ok"] = False
                check["problems"].append("downloaded payloads do not reproduce the stored chain head")
            f = parquet_path(league)
            if len(df):
                df[PAYLOAD_FIELDS].to_parquet(f, index=False)
            df.to_parquet(local_store_path(league), index=False)
            return {"league": league, "action": "load", "rows": len(df), "written": str(f) if len(df) else None,
                    "verify": _brief(check), "bytes_read": bytes_read()}
        if action == "sync":
            f = Path(path) if path else parquet_path(league)
            if not f.exists():
                return {"league": league, "action": "sync", "inserted": 0, "note": "no local snapshots"}
            res = insert(conn, league, pd.read_parquet(f), batch or "collection", run_id)
            check = check_and_advance(conn, "snapshots", league, "refresh sync")
            if res["inserted"] and check["head"] != res["head"]["row_hash"]:
                check["ok"] = False
                check["problems"].append("stored head differs from the rows this run inserted")
            _append_local(league, res)
            added = res.pop("rows_added")
            return res | {"action": "sync", "verify": _brief(check), "new_rows_hashed_locally": len(added), "bytes_read": bytes_read()}
        if action == "import":
            f = Path(path)
            res = insert(conn, league, pd.read_parquet(f), batch or "import", run_id)
            res.pop("rows_added", None)
            return res | {"action": "import", "verify": _brief(check_and_advance(conn, "snapshots", league, "import"))}
        if action in ("verify", "verify-full"):
            # Complete historical verification: the database recomputes every row of every chain and checks it against
            # the checkpoint; verify-full ALSO downloads and recomputes everything locally (manual use: large egress).
            cps = read_checkpoints()
            out = {"league": league, "mode": action, "ok": True}
            for t in TABLES:
                try:
                    s = server_check(conn, t, league, anchor_for(cps, t, league))
                except Exception as e:  # table not created yet
                    out[t] = {"rows": 0, "ok": True, "note": type(e).__name__}
                    continue
                out[t] = _brief(s)
                out["ok"] = out["ok"] and s["ok"]
                if action == "verify-full":
                    c = verify(conn, league) if t == "snapshots" else verify_table(conn, t, league)
                    out[t]["client"] = {"rows": c["rows"], "ok": c["ok"], "problems": c["problems"], "same_head": c["head"] == s["head"]}
                    out["ok"] = out["ok"] and c["ok"] and c["head"] == s["head"]
            out["rows"] = out.get("snapshots", {}).get("rows", 0)
            out["bytes_read"] = bytes_read()
            return out
        raise StoreError(f"unknown action {action}")
    finally:
        conn.close()


def _brief(c: dict) -> dict:
    return {k: c.get(k) for k in ("rows", "ok", "problems", "head", "anchor", "checkpoint") if k in c}


def _append_local(league: str, res: dict) -> None:
    """Add the rows sync just inserted to this refresh's local copy, if it is the copy they were chained onto."""
    f = local_store_path(league)
    mine = local_head(league)
    if not res["rows_added"] or mine is None or (mine["seq"], mine["row_hash"]) != (res["start"]["seq"], res["start"]["row_hash"]):
        if res["rows_added"] and f.exists():
            f.unlink()  # out of step: the next reader does one full read instead
        return
    new = frame_from_payloads([r["payload"] for r in res["rows_added"]])
    new.insert(0, "snapshot_hash", [r["row_hash"] for r in res["rows_added"]])
    new.insert(0, "snapshot_seq", [r["seq"] for r in res["rows_added"]])
    pd.concat([pd.read_parquet(f), new], ignore_index=True).to_parquet(f, index=False)
