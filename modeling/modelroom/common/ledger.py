"""Append-only, hash-chained prediction ledger.

Rules
- A prediction is accepted only if it was generated before the game starts.
- Lines are only ever appended. Each line stores the previous line's hash, so
  editing or deleting any earlier line breaks verification.
- Re-running the same model on the same inputs for the same game is a no-op
  (deduplicated on game_id + model_version + inputs_hash + params_hash).
- Grading never touches this file; results are computed into separate reports.
- A ledger can be a series: the original file plus one file per ISO week (<name>_week_<YYYY>-W<ww>.jsonl), each its
  own hash chain. New records go to the current week's file, deduplicated against every file in the series, so
  no single file outgrows GitHub's 100 MB limit while the earlier files stay exactly as written.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

GENESIS = "0" * 64


class LedgerError(RuntimeError):
    pass


def _line_hash(body: dict) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise LedgerError(f"Timestamp without timezone: {value}")
    return ts


@dataclass
class AppendResult:
    appended: int
    skipped_duplicate: int
    rejected_started: int


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _key(r: dict) -> tuple:
    return (r["game_id"], r["model_version"], r["inputs_hash"], r.get("params_hash"))


def append(path: Path, predictions: Iterable[dict], also_seen: set | None = None) -> AppendResult:
    """Append prediction dicts. Each needs game_id, model_version, inputs_hash,
    generated_at and game_start (ISO 8601 with timezone). `also_seen`: dedupe keys already recorded in other files of
    the same series."""
    existing = read(path)
    verify_records(existing)
    key = _key

    seen = {key(r) for r in existing} | set(also_seen or ())
    prev = existing[-1]["hash"] if existing else GENESIS
    seq = existing[-1]["seq"] if existing else 0

    appended = dup = started = 0
    lines: list[str] = []
    for p in predictions:
        k = key(p)
        if k in seen:
            dup += 1
            continue
        if _parse_ts(p["generated_at"]) >= _parse_ts(p["game_start"]):
            started += 1
            continue
        seq += 1
        body = {**p, "seq": seq, "prev_hash": prev}
        body["hash"] = _line_hash(body)
        lines.append(json.dumps(body, sort_keys=True, separators=(",", ":")))
        prev = body["hash"]
        seen.add(k)
        appended += 1

    if lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            for line in lines:
                f.write(line + "\n")
    return AppendResult(appended, dup, started)


def verify_records(records: list[dict]) -> None:
    prev = GENESIS
    for i, r in enumerate(records, start=1):
        body = {k: v for k, v in r.items() if k != "hash"}
        if r.get("seq") != i:
            raise LedgerError(f"Ledger sequence broken at line {i}")
        if r.get("prev_hash") != prev:
            raise LedgerError(f"Ledger chain broken at line {i}: an earlier line was edited or removed")
        if _line_hash(body) != r.get("hash"):
            raise LedgerError(f"Ledger line {i} was modified after it was written")
        if _parse_ts(r["generated_at"]) >= _parse_ts(r["game_start"]):
            raise LedgerError(f"Ledger line {i} was generated after its game started")
        prev = r["hash"]


def verify(path: Path) -> int:
    records = read(path)
    verify_records(records)
    return len(records)


# ------------------------------------------------------------------ weekly series
def week_tag(now) -> str:
    y, w, _ = datetime.fromisoformat(str(now)).isocalendar() if isinstance(now, str) else now.isocalendar()
    return f"{y}-W{w:02d}"


def weekly_path(base: Path, now) -> Path:
    return base.with_name(f"{base.stem}_week_{week_tag(now)}.jsonl")


def series_files(base: Path) -> list[Path]:
    """The original file (if any) then the weekly files, oldest first."""
    weekly = sorted(base.parent.glob(f"{base.stem}_week_*.jsonl"))
    return ([base] if base.exists() else []) + weekly


def read_series(base: Path) -> list[dict]:
    files = series_files(base)
    if not files:
        return read(base)   # nothing on disk yet: same as reading a missing ledger
    out: list[dict] = []
    for f in files:
        out += read(f)
    return out


def verify_series(base: Path) -> dict:
    """Verify every file's hash chain; returns {file name: records}."""
    return {f.name: verify(f) for f in series_files(base)}


def append_weekly(base: Path, now, predictions: Iterable[dict]) -> AppendResult:
    """Append to the current week's file, skipping anything already recorded anywhere in the series."""
    target = weekly_path(base, now)
    others = {_key(r) for f in series_files(base) if f != target for r in read(f)}
    return append(target, predictions, also_seen=others)
