"""Inputs for the NBA prop model: player box scores, game pace, and the game engine's walk-forward projections."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .. import ingest, walkforward
from ..backtest import apply
from ..config import ModelParams
from ..features import game_possessions
from ..project import total_offsets
from . import data


@dataclass
class Inputs:
    player_games: pd.DataFrame
    pace: pd.DataFrame       # game_id (str), pace (possessions per 48)
    games: pd.DataFrame      # game engine projections: proj_margin (home), proj_pace, game_date, home_abbr, away_abbr


def game_projections() -> pd.DataFrame:
    params = ModelParams.load()
    games, team_games = ingest.load()
    seasons = set(range(int(games["season"].min()) + 1, int(games["season"].max()) + 1))
    proj, _, _ = walkforward.run(games, team_games, params.ratings, project_seasons=seasons, include_scheduled=True)
    if params.adjustments.total_rolling_games:
        proj["total_offset"] = total_offsets(proj, params.adjustments.total_rolling_games)
    proj = apply(proj, params.adjustments, use_injuries=False)
    proj["game_id"] = proj["game_id"].astype(str)
    proj["game_date"] = proj["game_date"].astype(str)
    return proj


def load() -> Inputs:
    games, team_games = ingest.load()
    pace = game_possessions(games, team_games)[["game_id", "pace"]]
    pace["game_id"] = pace["game_id"].astype(str)
    return Inputs(data.build(), pace, game_projections())
