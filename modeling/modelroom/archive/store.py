"""Object store for Model Room archives (TEST): Cloudflare R2 through its S3-compatible API, or a local folder.

R2 (private bucket) is used when R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET are set (GitHub
TEST secrets; never in the repo or the site). Every object carries its SHA-256 in metadata and the caller checks it on
read; nothing here prints a key, a secret or an object's contents.

Cost protection: one PUT (Class A) per archived segment, one GET (Class B) per read; no listing in normal use (the
archive index in Supabase and the manifest say what exists).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


class ArchiveError(RuntimeError):
    pass


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class LocalStore:
    """A folder standing in for the bucket (dry runs, tests)."""
    kind = "local"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, key: str, body: bytes, meta: dict | None = None) -> dict:
        f = self.root / key
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
        return {"key": key, "bytes": len(body), "sha256": sha256(body)}

    def get(self, key: str) -> bytes:
        f = self.root / key
        if not f.exists():
            raise ArchiveError(f"missing object {key}")
        return f.read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


class R2Store:
    """Private Cloudflare R2 bucket via the S3 API (boto3). Standard storage class only (the free tier's)."""
    kind = "r2"

    def __init__(self, account_id: str, key_id: str, secret: str, bucket: str):
        import boto3  # installed by the archive workflow only
        from botocore.config import Config
        self.bucket = bucket
        self.endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        self.s3 = boto3.client("s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com", aws_access_key_id=key_id,
                               aws_secret_access_key=secret, region_name="auto",
                               config=Config(retries={"max_attempts": 4, "mode": "standard"}, signature_version="s3v4"))

    def put(self, key: str, body: bytes, meta: dict | None = None) -> dict:
        h = sha256(body)
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, Metadata={"sha256": h, **{k: str(v) for k, v in (meta or {}).items()}})
        return {"key": key, "bytes": len(body), "sha256": h}

    def get(self, key: str) -> bytes:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey as e:
            raise ArchiveError(f"missing object {key}") from e

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001  404 or no access: treat as absent, the caller re-checks
            return False

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def anonymous_status(self, key: str) -> int:
        """HTTP status of an UNSIGNED request for this object on the S3 endpoint: a private bucket answers 4xx."""
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{self.endpoint}/{self.bucket}/{key}", method="GET"), timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code


def from_env(local_root: str | None = None):
    """R2 when its four settings are present, else the local folder (if given)."""
    keys = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if all(os.environ.get(k) for k in keys):
        return R2Store(*(os.environ[k] for k in keys))
    if local_root:
        return LocalStore(local_root)
    raise ArchiveError("R2 is not configured (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET) and no local folder was given")
