"""Loads everything the prop model reads, from the processed files and the game engine."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from modelroom.common.paths import ensure, output_dir, processed_dir, raw_dir

from .. import ingest, player_data, project, walkforward
from ..config import ModelParams


@dataclass
class Inputs:
    player_games: pd.DataFrame
    passes: pd.DataFrame
    rushes: pd.DataFrame
    games: pd.DataFrame        # game engine projections: proj_home_score / proj_away_score per game
    rosters: pd.DataFrame
    injuries: pd.DataFrame


def game_projections(seasons: set[int], *, use_cache: bool = True) -> pd.DataFrame:
    """Walk-forward game-engine projections (each game uses earlier plays only). Cached per run inputs."""
    params = ModelParams.load()
    prep = walkforward.prepare()
    games = ingest.load_games()
    key = f"{params.to_json()['model_version']}-{len(prep.tg)}-{int((games['status'] == 'final').sum())}-{len(games)}"
    cache = ensure(output_dir("nfl")) / "prop_game_inputs.parquet"
    if use_cache and cache.exists():
        c = pd.read_parquet(cache)
        if len(c) and c["cache_key"].iloc[0] == key and seasons <= set(c["season"].unique()):
            return c[c["season"].isin(seasons)]
    out = project.apply(walkforward.run(prep, params.ratings, params.points.qb_replacement_epa,
                                        project_seasons=seasons, include_scheduled=True), params.points)
    qb = games.set_index("game_id")[["home_qb_id", "away_qb_id"]]
    out = out.join(qb, on="game_id")
    out["cache_key"] = key
    out.to_parquet(cache, index=False)
    return out


def rosters() -> pd.DataFrame:
    return player_data.rosters(ingest.available_pbp_seasons())


def injuries() -> pd.DataFrame:
    parts = []
    for f in sorted(raw_dir("nfl").glob("injuries_*.parquet")):
        d = pd.read_parquet(f)
        parts.append(d[[c for c in ("season", "week", "game_type", "team", "gsis_id", "full_name", "report_status", "date_modified") if c in d.columns]])
    if not parts:
        return pd.DataFrame(columns=["season", "week", "team", "gsis_id", "report_status"])
    inj = pd.concat(parts, ignore_index=True)
    inj["team"] = inj["team"].replace(ingest.FRANCHISE)
    if "date_modified" in inj:
        inj = inj.sort_values("date_modified", na_position="first")
    return inj.drop_duplicates(["season", "week", "team", "gsis_id"], keep="last")


def load(seasons: set[int]) -> Inputs:
    pg, passes, rushes = player_data.load()
    return Inputs(pg, passes, rushes, game_projections(seasons), rosters(), injuries())


def week_slices(inp: Inputs, season: int, week: int) -> tuple[pd.DataFrame | None, pd.DataFrame]:
    """Roster for this week (falls back to the latest published week) and this week's injury report."""
    r = inp.rosters[(inp.rosters["season"] == season) & (inp.rosters["week"] <= week)]
    # Each team's roster for this week, else its latest published week (byes and not-yet-published weeks).
    if len(r):
        latest = r.groupby("team")["week"].transform("max")
        rw = r[r["week"] == latest].drop_duplicates(["team", "gsis_id"], keep="last")
    else:
        rw = None
    inj = inp.injuries[(inp.injuries["season"] == season) & (inp.injuries["week"] == week)]
    return rw, inj


def processed_ok() -> bool:
    return (processed_dir("nfl") / "player_games.parquet").exists()
