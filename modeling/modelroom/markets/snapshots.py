"""Timestamped market snapshots, append-only, one file per provider per league per day.

  data/markets/snapshots/<provider>/<league>/<YYYY-MM-DD>.jsonl

Every fetch appends what it saw (quotes plus captured_at). Nothing is edited later. These files are
the history for price movement, exchange-vs-exchange comparison, closing-line value and "did the model
see it before the market moved". data/ is gitignored; see markets.config for what may be published.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from modelroom.common.paths import data_root

from .schema import PropQuote


def root() -> Path:
    return data_root() / "markets" / "snapshots"


def append(quotes: list[PropQuote], league: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    day = datetime.now(timezone.utc).date().isoformat()
    by_provider: dict[str, list[PropQuote]] = {}
    for q in quotes:
        by_provider.setdefault(q.provider.split(":")[0], []).append(q)
    for prov, qs in by_provider.items():
        f = root() / prov / league / f"{day}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8", newline="\n") as out:
            for q in qs:
                out.write(json.dumps(q.to_dict(), sort_keys=True, default=str) + "\n")
        counts[prov] = len(qs)
    return counts


def load(league: str, provider: str | None = None) -> pd.DataFrame:
    files = sorted(root().glob(f"{provider or '*'}/{league}/*.jsonl"))
    rows = [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return pd.DataFrame(rows)


def latest(league: str, provider: str | None = None) -> pd.DataFrame:
    """Most recent snapshot of each contract."""
    df = load(league, provider)
    if df.empty:
        return df
    return df.sort_values("captured_at").drop_duplicates(["provider", "provider_market_id"], keep="last")


def closing(league: str) -> pd.DataFrame:
    """Last snapshot of each contract taken before its game started (for closing-line value)."""
    df = load(league)
    if df.empty or "start_time" not in df:
        return df.iloc[0:0]
    st = pd.to_datetime(df["start_time"], utc=True, errors="coerce")
    ct = pd.to_datetime(df["captured_at"], utc=True, errors="coerce")
    pre = df[(st.isna()) | (ct < st)]
    return pre.sort_values("captured_at").drop_duplicates(["provider", "provider_market_id"], keep="last")
