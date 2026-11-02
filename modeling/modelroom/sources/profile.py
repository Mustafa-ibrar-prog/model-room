"""Inspect a dataset before it is used: columns, coverage, missing values, duplicates."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Profile:
    dataset: str
    rows: int
    columns: list[dict]
    duplicate_keys: int
    coverage: dict
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "rows": self.rows,
            "ok": self.ok,
            "duplicate_keys": self.duplicate_keys,
            "coverage": self.coverage,
            "checks": [c.__dict__ for c in self.checks],
            "columns": self.columns,
        }


def profile(
    df: pd.DataFrame,
    dataset: str,
    *,
    keys: list[str],
    date_col: str | None = None,
    season_col: str | None = None,
    required: list[str] | None = None,
) -> Profile:
    cols = []
    for c in df.columns:
        s = df[c]
        cols.append(
            {
                "name": c,
                "dtype": str(s.dtype),
                "missing": int(s.isna().sum()),
                "missing_pct": round(float(s.isna().mean()) * 100, 2) if len(df) else 0.0,
            }
        )
    dups = int(df.duplicated(keys).sum()) if keys and len(df) else 0
    coverage: dict = {}
    if date_col and date_col in df and len(df):
        d = pd.to_datetime(df[date_col], errors="coerce", utc=True)
        coverage["first"] = str(d.min().date()) if d.notna().any() else None
        coverage["last"] = str(d.max().date()) if d.notna().any() else None
    if season_col and season_col in df and len(df):
        coverage["seasons"] = {int(k): int(v) for k, v in df[season_col].value_counts().sort_index().items()}

    p = Profile(dataset, int(len(df)), cols, dups, coverage)
    p.checks.append(Check("not empty", len(df) > 0, f"{len(df)} rows"))
    p.checks.append(Check(f"unique on {'+'.join(keys)}", dups == 0, f"{dups} duplicate keys"))
    for c in required or []:
        if c not in df:
            p.checks.append(Check(f"{c} present", False, "column missing"))
        else:
            n = int(df[c].isna().sum())
            p.checks.append(Check(f"{c} complete", n == 0, f"{n} missing"))
    return p


def add_check(p: Profile, name: str, ok: bool, detail: str = "") -> Profile:
    p.checks.append(Check(name, bool(ok), detail))
    return p
