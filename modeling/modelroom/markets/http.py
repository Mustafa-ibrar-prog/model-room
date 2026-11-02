"""Polite JSON client: per-provider rate limit, on-disk response cache, retries with Retry-After.

One client per provider, so limits, caches and credentials never mix.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from modelroom.common.download import USER_AGENT


class ProviderError(RuntimeError):
    pass


class JsonClient:
    def __init__(self, base: str, *, name: str, min_interval_s: float, cache_dir: Path | None, cache_ttl_s: float = 60.0,
                 retries: int = 4, timeout: int = 30, headers: dict | None = None, opener=None):
        self.base = base.rstrip("/")
        self.name = name
        self.min_interval_s = min_interval_s
        self.cache_dir = cache_dir
        self.cache_ttl_s = cache_ttl_s
        self.retries = retries
        self.timeout = timeout
        self.headers = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
        self._last = 0.0
        self._opener = opener or urllib.request.urlopen
        self.calls = 0
        self.cache_hits = 0
        self.failures: list[str] = []

    def _url(self, path: str, params: dict | None) -> str:
        q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
        return f"{self.base}{path}" + (f"?{q}" if q else "")

    def _cache_file(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")

    def get(self, path: str, params: dict | None = None, *, allow_404: bool = False):
        url = self._url(path, params)
        cf = self._cache_file(url)
        if cf is not None and cf.exists() and time.time() - cf.stat().st_mtime < self.cache_ttl_s:
            self.cache_hits += 1
            return json.loads(cf.read_text())
        wait = 0.0
        last_err = None
        for attempt in range(self.retries + 1):
            if wait:
                time.sleep(wait)
            gap = time.monotonic() - self._last
            if gap < self.min_interval_s:
                time.sleep(self.min_interval_s - gap)
            self._last = time.monotonic()
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with self._opener(req, timeout=self.timeout) as r:
                    body = r.read().decode()
                data = json.loads(body)
                if cf is not None:
                    cf.parent.mkdir(parents=True, exist_ok=True)
                    cf.write_text(body)
                return data
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                if e.code == 404 and allow_404:
                    return None
                if e.code == 429 or e.code >= 500:
                    ra = e.headers.get("Retry-After") if e.headers else None
                    wait = (float(ra) + 1.0) if ra and str(ra).replace(".", "").isdigit() else 10.0 * (attempt + 1)
                    continue
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                last_err = repr(e)
                wait = 3.0 * (attempt + 1)
        self.failures.append(f"{url}: {last_err}")
        raise ProviderError(f"{self.name}: {url} failed ({last_err})")
