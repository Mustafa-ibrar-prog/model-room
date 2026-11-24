"""Copy CLOSED prediction-ledger files (the hash-chained .jsonl ledgers on the preview branch) into the private archive,
byte for byte, zstd-compressed, verified (TEST; Moose 2026-11-23). Git keeps them as they are: this is a copy, not a move.

A file is closed when it is a weekly file of an earlier ISO week (`<name>_week_YYYY-Www.jsonl`): nothing is ever
appended to it again. The open week and the original non-weekly files are copied only when explicitly asked (they can
still grow). Each copy is checked before upload (its own hash chain verifies) and after (decompressed bytes are
identical, SHA-256 of the original file matches).

Layout: {prefix}/ledgers/{file name}.zst, plus {prefix}/ledgers/manifest.json (file -> sha256 of the original bytes,
lines, chain head, first/last generated_at, model versions, bytes stored).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from modelroom.common import ledger as L

from .store import sha256

WEEKLY = re.compile(r"_(?:week_)?(\d{4})-W(\d{2})\.jsonl$")   # <name>_week_YYYY-Www and shadow <name>_YYYY-Www


def is_closed(name: str, now: datetime) -> bool:
    m = WEEKLY.search(name)
    if not m:
        return False
    y, w, _ = now.isocalendar()
    return (int(m.group(1)), int(m.group(2))) < (y, w)


def _zstd():
    import zstandard  # archive workflow dependency
    return zstandard


def verify_chain(recs: list[dict]) -> None:
    """The ledger's own checks; ledgers without game times (grades, injury snapshots) get the chain checks only."""
    if recs and not all("prev_hash" in r for r in recs):
        return                                                  # not a hash chain (e.g. injury snapshots): bytes + checksum only
    if all("generated_at" in r and "game_start" in r for r in recs):
        L.verify_records(recs)
        return
    prev = L.GENESIS
    for i, r in enumerate(recs, start=1):
        if r.get("seq") != i or r.get("prev_hash") != prev or L._line_hash({k: v for k, v in r.items() if k != "hash"}) != r.get("hash"):
            raise L.LedgerError(f"chain broken at line {i}")
        prev = r["hash"]


def summarize(path: Path) -> dict:
    recs = L.read(path)
    verify_chain(recs)                                         # raises if the chain is broken
    versions = Counter(str(r.get("model_version")) for r in recs)
    gen = sorted(str(r.get("generated_at")) for r in recs if r.get("generated_at"))
    return {"lines": len(recs), "chained": bool(recs) and all("prev_hash" in r for r in recs), "head": recs[-1].get("hash") if recs else None, "model_versions": dict(versions),
            "generated_first": gen[0] if gen else None, "generated_last": gen[-1] if gen else None}


def archive_ledgers(store, prefix: str, ledger_dir: Path, now: datetime | None = None, include_open: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    mk = f"{prefix}/ledgers/manifest.json"
    man = json.loads(store.get(mk)) if store.exists(mk) else {"files": {}}
    out = {"copied": [], "already": 0, "skipped_open": [], "problems": []}
    for f in sorted(Path(ledger_dir).glob("*.jsonl")):
        if not include_open and not is_closed(f.name, now):
            out["skipped_open"].append(f.name)
            continue
        raw = f.read_bytes()
        h = sha256(raw)
        prior = man["files"].get(f.name)
        if prior and prior["sha256"] == h and store.exists(prior["key"]):
            out["already"] += 1
            continue
        if prior and prior["sha256"] != h and is_closed(f.name, now):
            out["problems"].append(f"{f.name}: a closed ledger changed since it was archived (archived copy kept)")
            continue
        try:
            info = summarize(f)
        except Exception as e:  # noqa: BLE001
            out["problems"].append(f"{f.name}: chain does not verify ({type(e).__name__}); not archived")
            continue
        z = _zstd()
        body = z.ZstdCompressor(level=19).compress(raw)
        key = f"{prefix}/ledgers/{f.name}.zst"
        put = store.put(key, body, {"sha256_original": h})
        back = z.ZstdDecompressor().decompress(store.get(key))
        if sha256(back) != h:
            out["problems"].append(f"{f.name}: read-back differs")
            continue
        entry = {"key": key, "sha256": h, "bytes_original": len(raw), "bytes_stored": put["bytes"], "closed": is_closed(f.name, now),
                 "archived_at": now.isoformat(timespec="seconds"), **info}
        man["files"][f.name] = entry
        out["copied"].append({"file": f.name, **{k: entry[k] for k in ("lines", "bytes_original", "bytes_stored")}})
    if out["copied"]:
        man["updated_at"] = now.isoformat(timespec="seconds")
        store.put(mk, json.dumps(man, indent=1, sort_keys=True).encode())
    out["files_in_archive"] = len(man["files"])
    out["bytes_original"] = sum(v["bytes_original"] for v in man["files"].values())
    out["bytes_stored"] = sum(v["bytes_stored"] for v in man["files"].values())
    return out


def verify_ledgers(store, prefix: str) -> dict:
    """Re-read every archived ledger: checksum of the original bytes, and its hash chain."""
    import tempfile
    mk = f"{prefix}/ledgers/manifest.json"
    if not store.exists(mk):
        return {"files": 0, "ok": True, "problems": []}
    man = json.loads(store.get(mk))
    z = _zstd()
    problems = []
    for name, e in man["files"].items():
        raw = z.ZstdDecompressor().decompress(store.get(e["key"]))
        if sha256(raw) != e["sha256"]:
            problems.append(f"{name}: checksum differs")
            continue
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as t:
            Path(t.name).write_bytes(raw)
            try:
                if summarize(Path(t.name))["head"] != e["head"]:
                    problems.append(f"{name}: chain head differs")
            except Exception as ex:  # noqa: BLE001
                problems.append(f"{name}: chain does not verify ({type(ex).__name__})")
    return {"files": len(man["files"]), "ok": not problems, "problems": problems[:20]}
