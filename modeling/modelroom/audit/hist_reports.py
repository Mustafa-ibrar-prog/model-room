"""Historical official NBA injury reports for realistic replays (test tooling; never used by the live site).

For each game, the report the model would have had at its final pregame refresh: the league's report published
at or before (tip − 30 min), floored to the hour (US Eastern). Harvested once from the league's public PDFs
(the injury-probe branch, harvest.py) and parsed with the same parser the live feed uses.

    build(inp, paths) → {(game_id, team): {"players": {player_id: {...}}, "submitted": bool, "report_time": ...}}

Only report information is used: nothing from the box score of the game being predicted.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from modelroom.injuries import schema as S

ET = "America/New_York"


def load(dirs: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    R = pd.concat([pd.read_parquet(Path(d) / "nba_reports.parquet") for d in dirs if (Path(d) / "nba_reports.parquet").exists()], ignore_index=True)
    F = pd.concat([pd.read_parquet(Path(d) / "nba_filings.parquet") for d in dirs if (Path(d) / "nba_filings.parquet").exists()], ignore_index=True)
    return R, F


def slot_of(start_time) -> str:
    t = pd.Timestamp(start_time).tz_convert(ET) - pd.Timedelta(minutes=30)
    return t.floor("h").isoformat()


def id_maps(pg: pd.DataFrame) -> tuple[dict, dict]:
    """(season, team, name key) → player_id, and (season, name key) → player_id when the name is unique that season."""
    x = pg.drop_duplicates(["season", "team", "player_id"]).assign(key=lambda d: d["name"].map(S.norm_name))
    by_team = {(r.season, r.team, r.key): str(r.player_id) for r in x.itertuples()}
    u = x.drop_duplicates(["season", "player_id"]).groupby(["season", "key"])["player_id"].agg(list)
    by_name = {k: str(v[0]) for k, v in u.items() if len(v) == 1}
    return by_team, by_name


def build(inp, dirs: list[Path]) -> tuple[dict, dict]:
    R, F = load(dirs)
    by_team, by_name = id_maps(inp.player_games)
    g = inp.games[inp.games["status"] == "final"].copy()
    g["slot"] = g["start_time"].map(slot_of)
    R["key"] = R["player"].map(S.norm_name)
    Rk = {k: d for k, d in R.groupby(["target_slot", "game_date", "team"])}
    Fk = {(r.target_slot, str(r.game_date), r.team): (bool(r.submitted), r.report_time) for r in F.itertuples()}
    out, stats = {}, {"games": 0, "with_report": 0, "rows": 0, "unmatched": 0}
    for r in g.itertuples():
        for team in (r.home_abbr, r.away_abbr):
            stats["games"] += 1
            k = (r.slot, str(r.game_date), team)
            if k not in Fk and k not in Rk:
                continue
            stats["with_report"] += 1
            players = {}
            d = Rk.get(k)
            if d is not None:
                for x in d.itertuples():
                    pid = by_team.get((r.season, team, x.key)) or by_name.get((r.season, x.key))
                    stats["rows"] += 1
                    if pid is None:
                        stats["unmatched"] += 1
                        continue
                    players[pid] = {"status": x.status, "raw_status": x.raw_status, "source": "nba_official", "kind": "official",
                                    "report_time": x.report_time, "restriction": bool(x.restriction),
                                    "restriction_minutes": None if pd.isna(x.restriction_minutes) else float(x.restriction_minutes),
                                    "late_scratch": False, "conflict": None, "detail": x.detail if isinstance(x.detail, str) else None}
            sub, rt = Fk.get(k, (len(players) > 0, None))
            out[(str(r.game_id), team)] = {"players": players, "submitted": sub, "report_time": rt, "starters": None}
    return out, stats
