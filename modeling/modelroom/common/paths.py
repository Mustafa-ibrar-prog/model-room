"""Where data and outputs live. Override the root with MODELROOM_DATA_DIR."""
from __future__ import annotations

import os
from pathlib import Path

MODELING_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    return Path(os.environ.get("MODELROOM_DATA_DIR", MODELING_ROOT / "data"))


def raw_dir(league: str) -> Path:
    """Downloaded source files, exactly as published by the provider."""
    return data_root() / "raw" / league


def processed_dir(league: str) -> Path:
    """Normalized tables built from raw files by the ingest step."""
    return data_root() / "processed" / league


def output_dir(league: str) -> Path:
    """Ratings, projections and backtest reports produced by the engine."""
    return data_root() / "output" / league


def ledger_path(league: str) -> Path:
    """Append-only prediction ledger. Committed to git."""
    return MODELING_ROOT / "ledger" / f"{league}.jsonl"


def published_board_path(league: str) -> Path:
    """The file the website reads (server side only)."""
    return data_root() / "published" / f"{league}.json"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
