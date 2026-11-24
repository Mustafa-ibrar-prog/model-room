"""Copy CLOSED days of the private Pick of the Day audit table (odds.potd_model_outputs) into the archive, one object per
game date (TEST; Moose 2026-11-23). Read-only toward the table: its rows, triggers and write behaviour are untouched.

The table holds model outputs only (no market prices, lines or decisions), so the archive does too. A day is closed
once its games are two days old. Verification: row count per day equals the database's, and the SHA-256 of the day's
rows in canonical JSON (ordered by id) matches before and after upload.
Layout: {prefix}/audit/potd_model_outputs/{game_date}.parquet + manifest.json.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from modelroom.sources import odds_store as S

from .store import sha256

COLS = ["id", "game_date", "game_id", "game_start", "player_id", "player", "team", "opp", "stat", "model_version", "params_hash",
        "board_generated_at", "projection", "reference", "reference_value", "model_side", "model_prob", "explanation", "contributions",
        "run_id", "inserted_at"]


def _canon(rows: list[dict]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)


def archive_days(conn, store, prefix: str, today: date | None = None, max_days: int = 60) -> dict:
    today = today or datetime.now(timezone.utc).date()
    mk = f"{prefix}/audit/potd_model_outputs/manifest.json"
    man = json.loads(store.get(mk)) if store.exists(mk) else {"days": {}}
    cur = conn.cursor()
    cur.execute("select game_date, count(*) from odds.potd_model_outputs where game_date <= %s group by 1 order by 1",
                (today - timedelta(days=2),))
    days = [(str(d), int(n)) for d, n in S._fetchall(cur)]
    out = {"days_closed": len(days), "copied": [], "already": 0, "problems": [], "versions": {}}
    for d, n in days[:max_days]:
        if man["days"].get(d, {}).get("rows") == n and store.exists(man["days"][d]["key"]):
            out["already"] += 1
            continue
        cur.execute(f"select {', '.join(COLS)} from odds.potd_model_outputs where game_date = %s order by id", (d,))
        rows = [dict(zip(COLS, r)) for r in S._fetchall(cur)]
        if len(rows) != n:
            out["problems"].append(f"{d}: read {len(rows)} rows, table has {n}")
            continue
        h = sha256(_canon(rows).encode())
        df = pd.DataFrame(rows, columns=COLS).astype({"contributions": str, "game_start": str, "board_generated_at": str, "inserted_at": str, "game_date": str})
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, compression="zstd")
        key = f"{prefix}/audit/potd_model_outputs/{d}.parquet"
        put = store.put(key, buf.getvalue(), {"rows": n, "sha256_rows": h})
        back = pd.read_parquet(io.BytesIO(store.get(key)))
        if len(back) != n or sha256(store.get(key)) != put["sha256"]:
            out["problems"].append(f"{d}: read-back differs")
            continue
        vers = back["model_version"].value_counts().to_dict()
        man["days"][d] = {"key": key, "rows": n, "sha256_rows": h, "sha256": put["sha256"], "bytes": put["bytes"], "model_versions": vers}
        out["copied"].append({"day": d, "rows": n, "bytes": put["bytes"]})
    if out["copied"]:
        store.put(mk, json.dumps(man, indent=1, sort_keys=True).encode())
    out["rows_archived"] = sum(v["rows"] for v in man["days"].values())
    out["bytes_stored"] = sum(v["bytes"] for v in man["days"].values())
    return out
