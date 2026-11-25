"""Independent verification of the archived ledgers with the READ-ONLY R2 token (TEST; Moose 2026-11-24).

For every file in {prefix}/ledgers/manifest.json: the object exists, its size equals the manifest's bytes_stored, the
SHA-256 of the stored (compressed) bytes equals the sha256 recorded on the object at upload, the decompressed bytes are
exactly bytes_original long and hash to the manifest's sha256, which must also equal the SHA-256 of the same file in the
git checkout it was copied from, and its hash chain (when it has one) verifies to the recorded head. Also lists every
object under the prefix so nothing unexpected is there. Reads only; never writes, overwrites or deletes.

    python -m modelroom.archive.readonly_verify --ledgers <dir> [--prefix v1] > manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from modelroom.common import ledger as L

from .ledgers import _zstd, summarize


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledgers", required=True, help="the git checkout's ledger folder (source of truth)")
    ap.add_argument("--prefix", default="v1")
    a = ap.parse_args(argv)
    import boto3
    from botocore.config import Config

    e = {k: os.environ[k].strip() for k in ("R2_ACCOUNT_ID", "R2_BUCKET", "R2_READ_ACCESS_KEY_ID", "R2_READ_SECRET_ACCESS_KEY")}
    s3 = boto3.client("s3", endpoint_url=f"https://{e['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com", aws_access_key_id=e["R2_READ_ACCESS_KEY_ID"],
                      aws_secret_access_key=e["R2_READ_SECRET_ACCESS_KEY"], region_name="auto", config=Config(signature_version="s3v4"))
    b, pre = e["R2_BUCKET"], f"{a.prefix}/ledgers/"
    listed, tok = {}, None
    while True:
        r = s3.list_objects_v2(Bucket=b, Prefix=a.prefix + "/", **({"ContinuationToken": tok} if tok else {}))
        listed.update({o["Key"]: o["Size"] for o in r.get("Contents", [])})
        if not r.get("IsTruncated"):
            break
        tok = r["NextContinuationToken"]
    man = json.loads(s3.get_object(Bucket=b, Key=pre + "manifest.json")["Body"].read())
    z = _zstd().ZstdDecompressor()
    rows, problems = [], []
    for name, m in sorted(man["files"].items()):
        row = {"file": name, "key": m["key"], "lines": m["lines"], "bytes_original": m["bytes_original"], "bytes_stored": m["bytes_stored"],
               "sha256_original": m["sha256"], "chained": m.get("chained"), "checks": {}}
        o = s3.get_object(Bucket=b, Key=m["key"])
        body = o["Body"].read()
        c = row["checks"]
        c["size_matches_manifest"] = len(body) == m["bytes_stored"] == o["ContentLength"]
        row["sha256_stored"] = hashlib.sha256(body).hexdigest()
        c["stored_sha256_matches_upload"] = row["sha256_stored"] == o.get("Metadata", {}).get("sha256")
        raw = z.decompress(body)
        c["original_size_matches"] = len(raw) == m["bytes_original"]
        c["original_sha256_matches_manifest"] = hashlib.sha256(raw).hexdigest() == m["sha256"]
        src = Path(a.ledgers) / name
        c["identical_to_git_source"] = src.exists() and hashlib.sha256(src.read_bytes()).hexdigest() == m["sha256"]
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as t:
            Path(t.name).write_bytes(raw)
            try:
                c["chain_head_matches"] = summarize(Path(t.name))["head"] == m["head"]
            except Exception as ex:  # noqa: BLE001
                c["chain_head_matches"] = False
                row["error"] = type(ex).__name__
            try:                                               # the same reader the refresh and the site use
                c["loads_with_ledger_reader"] = len(L.read(Path(t.name))) == m["lines"]
            except Exception:  # noqa: BLE001
                c["loads_with_ledger_reader"] = False
        row["ok"] = all(c.values())
        if not row["ok"]:
            problems.append(f"{name}: " + ", ".join(k for k, v in c.items() if not v))
        rows.append(row)
    expected = {m["key"] for m in man["files"].values()} | {pre + "manifest.json"}
    unexpected = sorted(k for k in listed if k not in expected)
    out = {"bucket_prefix": a.prefix, "verified_with": "read-only token", "manifest_updated_at": man.get("updated_at"),
           "objects_listed": len(listed), "objects_expected": len(expected), "unexpected_objects": unexpected,
           "files": len(rows), "bytes_original": sum(r["bytes_original"] for r in rows), "bytes_stored": sum(r["bytes_stored"] for r in rows),
           "manifest_object_bytes": listed.get(pre + "manifest.json"), "ok": not problems and not unexpected, "problems": problems, "rows": rows}
    json.dump(out, sys.stdout, indent=1)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
