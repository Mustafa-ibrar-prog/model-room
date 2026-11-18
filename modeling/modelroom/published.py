"""Which player-prop model version was the PUBLISHED one at any moment.

Shadow versions are recorded in the same ledgers as the published version (NFL props: the same weekly files; NBA
props: the main file until shadows moved to their own files on 2026-11-08). Picks, results and day files must only
ever use the published version's records, so every prop ledger record is checked against this timeline before use.

Each entry is (from, version): the version the TEST workflow published from that moment, taken from the commit that
changed MODELROOM_<LEAGUE>_PROPS_VERSION (every push runs a refresh at once; the ledgers confirm each version's first
record follows these times). When the active version changes, add an entry here in the same commit:
tests/test_published_versions.py fails while the last entry differs from the workflow's version.
"""
from __future__ import annotations

import os

import pandas as pd

TIMELINE: dict[str, list[tuple[str, str]]] = {
    "nba": [
        ("2000-01-01T00:00:00+00:00", "0.1.0"),
        ("2026-11-04T02:05:33+00:00", "0.2.0"),   # 123fe24: 0.2.0 active on the test site
        ("2026-11-04T17:30:11+00:00", "0.2.1"),   # a1ae42e: injury-feed release, 0.2.1 active
        ("2026-11-08T02:22:43+00:00", "0.2.0"),   # 3b528ce: back to 0.2.0; 0.2.1 kept as a shadow
    ],
    "nfl": [
        ("2000-01-01T00:00:00+00:00", "0.1.0"),
        ("2026-11-04T17:30:11+00:00", "0.1.1"),   # a1ae42e: 0.1.1 active, 0.1.0 kept as a shadow
    ],
}


def published_version(league: str, at) -> str:
    """The published prop version at time `at` (ISO string or timestamp)."""
    t = pd.Timestamp(at)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    v = TIMELINE[league][0][1]
    for start, ver in TIMELINE[league]:
        if t >= pd.Timestamp(start):
            v = ver
    return v


def current_env_version(league: str) -> str | None:
    """The version the running workflow publishes (None when the env var is unset, e.g. local runs)."""
    return os.environ.get(f"MODELROOM_{league.upper()}_PROPS_VERSION", "").strip() or None


def is_published(league: str, rec: dict) -> bool:
    """True when this ledger record was made by the version published at the time it was generated."""
    return rec.get("model_version") == published_version(league, rec["generated_at"])
