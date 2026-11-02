"""Which market-data providers may run, and where their data goes.

Every external provider is OFF unless switched on. In production they stay off until commercial
redistribution permission is confirmed, even if switched on:

  MODELROOM_ENV=production                        production mode (the hosted site)
  MODELROOM_MARKETS_REDISTRIBUTION_OK=true        set only after written permission from the provider(s)

  MODELROOM_MARKETS_POLYMARKET_US=on              Polymarket US public market data (no key)
  MODELROOM_MARKETS_KALSHI=on                     Kalshi public market data (no key needed to read)
  KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH     optional, Kalshi only; never needed for reads, never logged

Terms, checked 2026-11-02 (re-check before launch):
  Polymarket US participant agreement §I.22: data is proprietary to PMUS and "may not be redistributed
    except as PMUS expressly permits".
  Kalshi Developer Agreement §3, §3.1, §3.5: API use is limited to facilitating your own trading; storing,
    caching or sharing data with third parties needs prior written authorization; no benchmarking or
    competitive use. Kalshi snapshots therefore stay on this machine (data/markets is gitignored) and are
    excluded from anything published unless MODELROOM_MARKETS_KALSHI_PUBLISH=on is set deliberately.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

PROVIDERS = ("polymarket_us", "kalshi")


def _on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "on", "true", "yes")


def production() -> bool:
    return os.environ.get("MODELROOM_ENV", "").strip().lower() == "production"


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    enabled: bool
    publishable: bool      # may its prices appear in files the website reads
    reason: str


def status(provider: str) -> ProviderStatus:
    flag = {"polymarket_us": "MODELROOM_MARKETS_POLYMARKET_US", "kalshi": "MODELROOM_MARKETS_KALSHI"}[provider]
    if not _on(flag):
        return ProviderStatus(provider, False, False, f"off (set {flag}=on to enable)")
    if production() and not _on("MODELROOM_MARKETS_REDISTRIBUTION_OK"):
        return ProviderStatus(provider, False, False, "off in production until redistribution permission is confirmed")
    if provider == "kalshi" and not _on("MODELROOM_MARKETS_KALSHI_PUBLISH"):
        return ProviderStatus(provider, True, False, "on for local use; not published (Kalshi Developer Agreement §3.1)")
    return ProviderStatus(provider, True, True, "on")


def enabled_providers() -> list[str]:
    return [p for p in PROVIDERS if status(p).enabled]
