"""Archive the hash-chained private odds tables (odds.snapshots, odds.comparisons, odds.reports) into immutable R2
segments, and verify them (TEST; Moose 2026-11-23). Nothing in Supabase is changed or deleted here.

Layout (one bucket, private):
  {prefix}/odds/{table}/{league}/seg-{first:08d}-{last:08d}.parquet   immutable, zstd Parquet, one CLOSED block of
                                                                      seq values; the open tail stays in Supabase only
  {prefix}/odds/{table}/{league}/manifest.json                        every segment: seq range, rows, first prev_hash,
                                                                      last row_hash, date range, bytes, SHA-256
Columns kept: seq, content_key, payload (the canonical record the chain hashes), prev_hash, row_hash, batch, run_id,
inserted_at. Typed copies on odds.snapshots are derived from the payload and are re-derived on read.

Verification of each segment before and after upload: seq runs first..last with no gap, every row_hash equals
sha256(prev_hash + payload), every prev_hash links to the row before (the first to the previous segment's last row,
or 64 zeros), the uploaded object reads back byte-identical (SHA-256), and the database row at `last` still carries
that exact row_hash. Segments already in the manifest and present in the store are not downloaded or re-read.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pandas as pd

from modelroom.sources import odds_store as S

from .store import ArchiveError, sha256

SEGMENT_ROWS = {"snapshots": 2_000, "comparisons": 10_000, "reports": 25}   # snapshots: small tail left in Supabase; reports ~2-3 MB each
COLUMNS = ["seq", "content_key", "payload", "prev_hash", "row_hash", "batch", "run_id", "inserted_at"]


def seg_key(prefix: str, table: str, league: str, first: int, last: int) -> str:
    return f"{prefix}/odds/{table}/{league}/seg-{first:08d}-{last:08d}.parquet"


def manifest_key(prefix: str, table: str, league: str) -> str:
    return f"{prefix}/odds/{table}/{league}/manifest.json"


def verify_block(rows: list[dict], first: int, prev: str) -> list[str]:
    """Same checks as the chain verifiers, for one block that must start at `first` and chain from `prev`."""
    problems = []
    for i, r in enumerate(rows):
        if int(r["seq"]) != first + i:
            problems.append(f"seq {r['seq']} at position {first + i}")
        if r["prev_hash"] != prev:
            problems.append(f"seq {r['seq']}: prev_hash does not link to the previous row")
        if S.chain(r["prev_hash"], r["payload"]) != r["row_hash"]:
            problems.append(f"seq {r['seq']}: row_hash does not match its payload")
        prev = r["row_hash"]
    return problems[:20]


def to_parquet(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["seq"] = df["seq"].astype("int64")
    df["inserted_at"] = df["inserted_at"].astype(str)
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, compression="zstd")
    return buf.getvalue()


def from_parquet(b: bytes) -> list[dict]:
    return pd.read_parquet(io.BytesIO(b)).to_dict("records")


def _fetch(conn, table: str, league: str, first: int, last: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(f"select {', '.join(COLUMNS)} from odds.{S._table(table)} where league = %s and seq between %s and %s order by seq",
                (league, first, last))
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in S._fetchall(cur)]


def _db_hash_at(conn, table: str, league: str, seq: int) -> str | None:
    cur = conn.cursor()
    cur.execute(f"select row_hash from odds.{S._table(table)} where league = %s and seq = %s", (league, seq))
    r = S._fetchone(cur)
    return r[0] if r else None


def read_manifest(store, prefix: str, table: str, league: str) -> dict:
    k = manifest_key(prefix, table, league)
    if not store.exists(k):
        return {"table": table, "league": league, "segments": []}
    return json.loads(store.get(k))


def archive_table(conn, store, prefix: str, table: str, league: str, rows_per_segment: int | None = None, run_id: str | None = None) -> dict:
    """Archive every CLOSED segment not yet in the manifest. Returns a report (counts, ranges, checks, index rows)."""
    n = rows_per_segment or SEGMENT_ROWS[table]
    check = S.server_check(conn, table, league)                     # whole table verified in the database first
    out = {"table": table, "league": league, "db_rows": check["rows"], "db_chain_ok": check["ok"], "db_problems": check["problems"],
           "segment_rows": n, "new_segments": [], "skipped_existing": 0, "problems": [], "index_rows": []}
    if not check["ok"]:
        out["problems"].append("database chain failed its check: nothing archived")
        return out
    man = read_manifest(store, prefix, table, league)
    have = {(s["first"], s["last"]): s for s in man["segments"]}
    prev = S.GENESIS
    for i in range(check["max_seq"] // n):
        first, last = i * n + 1, (i + 1) * n
        key = seg_key(prefix, table, league, first, last)
        seg = have.get((first, last))
        if seg and seg["first_prev_hash"] == prev and store.exists(key):
            prev = seg["last_row_hash"]
            out["skipped_existing"] += 1
            continue
        rows = _fetch(conn, table, league, first, last)
        p = verify_block(rows, first, prev) + ([] if len(rows) == n else [f"expected {n} rows, read {len(rows)}"])
        if p:
            out["problems"] += [f"{key}: {x}" for x in p]
            break
        body = to_parquet(rows)
        put = store.put(key, body, {"table": table, "league": league, "first": first, "last": last})
        back = store.get(key)
        if sha256(back) != put["sha256"] or verify_block(from_parquet(back), first, prev):
            out["problems"].append(f"{key}: read-back differs from what was written")
            break
        if _db_hash_at(conn, table, league, last) != rows[-1]["row_hash"]:
            out["problems"].append(f"{key}: database row {last} no longer carries the archived hash")
            break
        dates = [str(r["inserted_at"]) for r in rows]
        seg = {"first": first, "last": last, "rows": len(rows), "first_prev_hash": prev, "last_row_hash": rows[-1]["row_hash"],
               "inserted_first": min(dates), "inserted_last": max(dates), "bytes": put["bytes"], "sha256": put["sha256"],
               "payload_bytes": sum(len(r["payload"].encode()) for r in rows), "key": key,
               "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": run_id}
        man["segments"].append(seg)
        out["new_segments"].append(seg)
        out["index_rows"].append({"dataset": f"odds.{table}", "league": league, "object_key": key, "seq_first": first, "seq_last": last,
                                  "rows": len(rows), "first_prev_hash": prev, "last_row_hash": seg["last_row_hash"], "date_first": seg["inserted_first"],
                                  "date_last": seg["inserted_last"], "bytes": put["bytes"], "sha256": put["sha256"], "format": "parquet+zstd"})
        prev = seg["last_row_hash"]
    man["segments"].sort(key=lambda s: s["first"])
    man["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    man["chain_note"] = "row_hash = sha256(prev_hash + payload); segments chain end to end from 64 zeros; open tail lives in Supabase"
    if out["new_segments"]:
        store.put(manifest_key(prefix, table, league), json.dumps(man, indent=1).encode())
    archived = sum(s["rows"] for s in man["segments"])
    out.update(archived_rows=archived, tail_rows_in_supabase_only=check["rows"] - archived,
               archived_seq=[man["segments"][0]["first"], man["segments"][-1]["last"]] if man["segments"] else None)
    return out


def verify_archive(store, prefix: str, table: str, league: str, conn=None) -> dict:
    """Full re-verification of every archived segment from the store (R2 reads are free of egress charges): object
    SHA-256 vs manifest, every chain link and hash, end-to-end continuity, and (with a connection) that the database
    still carries each segment's last hash. Used by the scheduled full check, not by every refresh."""
    man = read_manifest(store, prefix, table, league)
    prev, problems, rows = S.GENESIS, [], 0
    for seg in sorted(man["segments"], key=lambda s: s["first"]):
        b = store.get(seg["key"])
        if sha256(b) != seg["sha256"]:
            problems.append(f"{seg['key']}: object checksum differs from the manifest")
            break
        if seg["first_prev_hash"] != prev:
            problems.append(f"{seg['key']}: does not continue the previous segment")
        p = verify_block(from_parquet(b), seg["first"], prev)
        problems += [f"{seg['key']}: {x}" for x in p]
        if conn is not None and _db_hash_at(conn, table, league, seg["last"]) != seg["last_row_hash"]:
            problems.append(f"{seg['key']}: database row {seg['last']} carries a different hash")
        prev, rows = seg["last_row_hash"], rows + seg["rows"]
    return {"table": table, "league": league, "segments": len(man["segments"]), "rows": rows, "ok": not problems, "problems": problems[:20], "head": prev}


def load_archived(store, prefix: str, table: str, league: str, seq_from: int = 1, seq_to: int | None = None) -> pd.DataFrame:
    """Rows from the archive for a seq range, reading only the segments that overlap it (no full download)."""
    man = read_manifest(store, prefix, table, league)
    parts = []
    for seg in man["segments"]:
        if seg["last"] < seq_from or (seq_to is not None and seg["first"] > seq_to):
            continue
        b = store.get(seg["key"])
        if sha256(b) != seg["sha256"]:
            raise ArchiveError(f"{seg['key']}: checksum mismatch")
        parts.append(pd.read_parquet(io.BytesIO(b)))
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(parts, ignore_index=True)
    return df[(df["seq"] >= seq_from) & ((df["seq"] <= seq_to) if seq_to is not None else True)].reset_index(drop=True)
