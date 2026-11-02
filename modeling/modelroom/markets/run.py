"""Fetch market data from every enabled provider and store a snapshot. Independent of the engines.

    python -m modelroom markets fetch nfl [--provider polymarket_us|kalshi|all] [--days 10]
    python -m modelroom markets status
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from modelroom.common.paths import data_root, processed_dir

from . import config, kalshi, polymarket_us, snapshots
from .http import ProviderError

ADAPTERS = {"polymarket_us": polymarket_us, "kalshi": kalshi}


def upcoming_games(league: str, days: int) -> pd.DataFrame:
    if league == "nfl":
        g = pd.read_parquet(processed_dir("nfl") / "games.parquet")
    else:
        g = pd.read_parquet(processed_dir("nba") / "games.parquet")
    g = g[g["status"] == "scheduled"].copy()
    st = pd.to_datetime(g["start_time"], utc=True)
    now = datetime.now(timezone.utc)
    g = g[(st > now) & (st <= now + timedelta(days=days))]
    g["game_date"] = g["game_date"].astype(str)
    return g


def fetch(league: str, providers: list[str] | None = None, days: int = 10, log=print) -> dict:
    wanted = providers or config.PROVIDERS
    games = upcoming_games(league, days)
    report: dict = {"league": league, "games": int(len(games)), "providers": {}}
    for name in wanted:
        st = config.status(name)
        if not st.enabled:
            report["providers"][name] = {"skipped": st.reason}
            continue
        cache = data_root() / "markets" / "cache" / name
        try:
            quotes, stats = ADAPTERS[name].fetch(league, games, cache, log=log)
        except ProviderError as e:  # one provider failing never blocks the others
            report["providers"][name] = {"error": str(e)}
            continue
        stats["stored"] = snapshots.append(quotes, league).get(name, 0)
        stats["publishable"] = st.publishable
        report["providers"][name] = stats
    return report


def provider_status() -> list[dict]:
    return [config.status(p).__dict__ for p in config.PROVIDERS]
