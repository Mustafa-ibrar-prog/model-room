"""Shared fixtures.

Unit tests use tiny SYNTHETIC inputs built here to check math and parsing.
They are never written to data/ and never reach the website. Tests marked
`data` run against real downloaded data and are skipped when it is absent.
"""
import os
from pathlib import Path

import pytest

from modelroom.common.paths import processed_dir


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path))
    return tmp_path


def has_real(league: str, name: str) -> bool:
    if os.environ.get("MODELROOM_DATA_DIR"):
        return False
    return (processed_dir(league) / f"{name}.parquet").exists()


real_nba = pytest.mark.skipif(not has_real("nba", "games"), reason="run `python -m modelroom nba ingest` first")
real_nfl = pytest.mark.skipif(not has_real("nfl", "games"), reason="run `python -m modelroom nfl ingest` first")
