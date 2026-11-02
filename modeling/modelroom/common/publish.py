"""Write the board file the website reads. Schema version bumps on breaking changes."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

BOARD_SCHEMA_VERSION = 1


def _clean(value: Any) -> Any:
    """JSON-safe: NaN/inf become null so 'missing' never turns into 0."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):  # numpy scalar
        return _clean(value.item())
    return value


def write_board(path: Path, board: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean({"schema_version": BOARD_SCHEMA_VERSION, **board}), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path
