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
    """Append-only prediction ledger. Committed to git.

    MODELROOM_LEDGER_DIR overrides the folder (the hosted preview keeps its own
    ledger so it never conflicts with the one on main)."""
    base = Path(os.environ["MODELROOM_LEDGER_DIR"]) if os.environ.get("MODELROOM_LEDGER_DIR") else MODELING_ROOT / "ledger"
    return base / f"{league}.jsonl"


def backtest_report(league: str, version: str) -> Path | None:
    """Latest local backtest output, else the committed report for this model version."""
    import json

    local = output_dir(league) / "backtest.json"
    if local.exists() and json.loads(local.read_text()).get("model_version") == version:
        return local
    committed = MODELING_ROOT.parent / "docs" / "models" / "results" / f"{league}-backtest-{version}.json"
    return committed if committed.exists() else None


def published_board_path(league: str) -> Path:
    """The file the website reads (server side only)."""
    return data_root() / "published" / f"{league}.json"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
