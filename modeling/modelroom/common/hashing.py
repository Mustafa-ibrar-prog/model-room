"""Deterministic hashes for reproducibility records."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd


def stable_json(obj: Any) -> str:
    if is_dataclass(obj):
        obj = asdict(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def hash_obj(obj: Any) -> str:
    return hashlib.sha256(stable_json(obj).encode()).hexdigest()[:16]


def hash_frame(df: pd.DataFrame, columns: list[str] | None = None) -> str:
    """Hash of a frame's values in a canonical row and column order."""
    cols = sorted(columns or df.columns)
    canon = df[cols].sort_values(cols, kind="mergesort").reset_index(drop=True)
    payload = pd.util.hash_pandas_object(canon, index=False).values.tobytes()
    return hashlib.sha256(payload).hexdigest()[:16]
