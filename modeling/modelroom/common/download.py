"""HTTP downloads with a small manifest so every raw file is traceable."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = "ModelRoom/0.1 (+https://github.com/Mustafa-ibrar-prog/model-room)"


class DownloadError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, *, retries: int = 3, timeout: int = 120, headers: dict | None = None) -> Path:
    """Download url to dest atomically and record it in dest's folder manifest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
            tmp.replace(dest)
            _record(dest, url)
            return dest
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404:
                break  # not published (e.g. a future season); don't retry
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
        time.sleep(2 * attempt)
    tmp.unlink(missing_ok=True)
    raise DownloadError(f"Could not download {url}: {last_err}")


def _record(dest: Path, url: str) -> None:
    manifest = dest.parent / "manifest.json"
    data = json.loads(manifest.read_text()) if manifest.exists() else {}
    data[dest.name] = {
        "url": url,
        "sha256": sha256_file(dest),
        "bytes": dest.stat().st_size,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest.write_text(json.dumps(data, indent=2, sort_keys=True))
