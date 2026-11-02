"""Last-successful-update record per source (data/raw/_state.json)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from modelroom.common.paths import data_root


def _path():
    return data_root() / "raw" / "_state.json"


def read() -> dict:
    p = _path()
    return json.loads(p.read_text()) if p.exists() else {}


def record(source_id: str, **details) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    state = read()
    state[source_id] = {
        "last_success": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **{k: v for k, v in details.items() if v is not None},
    }
    p.write_text(json.dumps(state, indent=2, sort_keys=True, default=str))


def record_failure(source_id: str, error: str) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    state = read()
    entry = state.get(source_id, {})
    entry["last_failure"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry["last_error"] = error[:500]
    state[source_id] = entry
    p.write_text(json.dumps(state, indent=2, sort_keys=True, default=str))
