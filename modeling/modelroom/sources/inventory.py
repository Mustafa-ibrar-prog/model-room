"""Data-source inventory: registry facts + last successful update + measured coverage."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from modelroom.common.paths import MODELING_ROOT, ensure, output_dir, processed_dir

from . import state
from .registry import REGISTRY, Source


def _read(league: str, name: str) -> pd.DataFrame | None:
    f = processed_dir(league) / f"{name}.parquet"
    return pd.read_parquet(f) if f.exists() else None


def _coverage(src: Source) -> tuple[str, str]:
    """(historical, current season) measured from processed data where available."""
    try:
        if src.id in ("hoopr_schedule", "hoopr_team_box"):
            g = _read("nba", "games")
            if g is None:
                return src.historical_coverage, "not ingested"
            cur = int(g["season"].max())
            c = g[g["season"] == cur]
            rated = g[g["has_box"]]
            hist = f"{int(rated['season'].min()) - 1}-{str(int(rated['season'].min()))[2:]} to {cur - 1}-{str(cur)[2:]}, {len(rated):,} games with box scores"
            now = (f"{cur - 1}-{str(cur)[2:]}: {int(c['has_box'].sum())} final through {c.loc[c['has_box'], 'game_date'].max()}, "
                   f"{int((c['status'] == 'scheduled').sum())} scheduled through {c['game_date'].max()}")
            return hist, now
        if src.id == "hoopr_player_box":
            p = _read("nba", "player_games")
            if p is None:
                return src.historical_coverage, "not ingested"
            cur = int(p["season"].max())
            return f"{int(p['season'].min()) - 1}-{str(int(p['season'].min()))[2:]} onward, {len(p):,} player-games", f"{int((p['season'] == cur).sum()):,} player-games this season"
        if src.id == "nflverse_games":
            g = _read("nfl", "games")
            if g is None:
                return src.historical_coverage, "not ingested"
            cur = int(g["season"].max())
            c = g[g["season"] == cur]
            fin = c[c["status"] == "final"]
            return (f"{int(g['season'].min())} to {cur}, {int((g['status'] == 'final').sum()):,} final games",
                    f"{cur}: {len(fin)} final through {fin['game_date'].max()}, {int((c['status'] == 'scheduled').sum())} scheduled")
        if src.id == "nflverse_pbp":
            p = _read("nfl", "pbp")
            if p is None:
                return src.historical_coverage, "not ingested"
            cur = int(p["season"].max())
            return (f"{int(p['season'].min())} to {cur} ingested ({len(p):,} plays)",
                    f"{cur}: {p.loc[p['season'] == cur, 'game_id'].nunique()} games, through week {int(p.loc[p['season'] == cur, 'week'].max())}")
        if src.id == "nflverse_injuries":
            i = _read("nfl", "injuries")
            if i is None:
                return src.historical_coverage, "not ingested"
            cur = int(i["season"].max())
            return src.historical_coverage, f"{cur}: through week {int(i.loc[i['season'] == cur, 'week'].max())}"
        if src.id == "land_of_basketball":
            from . import land_of_basketball

            l = land_of_basketball.load_snapshots()
            if l.empty:
                return src.historical_coverage, "no snapshot yet"
            return src.historical_coverage, f"{len(l)} games cross-checked ({l['game_date'].min()} to {l['game_date'].max()})"
    except Exception as e:  # inventory must never crash on one bad file
        return src.historical_coverage, f"coverage check failed: {e}"
    return src.historical_coverage, "n/a"


def build() -> list[dict]:
    st = state.read()
    rows = []
    for s in REGISTRY:
        hist, cur = _coverage(s)
        rec = st.get(s.id, {})
        rows.append(
            {
                "id": s.id, "source": s.name, "sport": s.sport.upper() if s.sport != "both" else "NBA, NFL",
                "categories": ", ".join(s.categories), "status": s.status,
                "historical_coverage": hist, "current_season": cur,
                "last_successful_update": rec.get("last_success", "never"),
                "last_error": rec.get("last_error"),
                "api_key": s.api_key, "official": "yes" if s.official else "no",
                "license": s.license, "update_frequency": s.update_frequency,
                "limitations": list(s.limitations), "access": s.access,
            }
        )
    return rows


def to_markdown(rows: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Data-source inventory",
        "",
        f"Generated {now} by `python -m modelroom sources inventory`. Do not edit by hand.",
        "",
        "Status: **collected** = refreshed by an ingest command; **optional** = used only if you set it up; "
        "**manual** = you enter it; **reference-only** = checked by hand, not collected (terms); **unavailable** = no permitted access.",
        "",
        "| Source | Sport | Status | Official | API key | Historical coverage | Current season | Last successful update |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['source']} | {r['sport']} | {r['status']} | {r['official']} | {r['api_key']} | "
            f"{r['historical_coverage']} | {r['current_season']} | {r['last_successful_update']} |"
        )
    lines += ["", "## Details", ""]
    for r in rows:
        lines += [
            f"### {r['source']}",
            "",
            f"- **Data:** {r['categories']}",
            f"- **Access:** `{r['access']}`" if r["access"].startswith("http") else f"- **Access:** {r['access']}",
            f"- **License / terms:** {r['license']}",
            f"- **Update frequency:** {r['update_frequency']}",
        ]
        lines += [f"- **Limitation:** {x}" for x in r["limitations"]]
        if r["last_error"]:
            lines.append(f"- **Last error:** {r['last_error']}")
        lines.append("")
    return "\n".join(lines)


def write(docs: bool = False) -> Path:
    rows = build()
    out = ensure(output_dir("validation"))
    (out / "inventory.json").write_text(json.dumps(rows, indent=2, default=str))
    md = to_markdown(rows)
    path = out / "inventory.md"
    path.write_text(md)
    if docs:
        doc = MODELING_ROOT.parent / "docs" / "data-inventory.md"
        doc.write_text(md + "\n")
        return doc
    return path
