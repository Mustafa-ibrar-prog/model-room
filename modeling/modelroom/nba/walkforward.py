"""Chronological walk-forward: ratings for each game day use only earlier games."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RatingSettings
from .features import game_possessions, rest_days
from .project import rating_projection
from .ratings import Ratings, SeasonRater, burn_in_prior, burn_in_settings, next_season_prior


def _team_ids(season_games: pd.DataFrame) -> list[int]:
    return sorted(set(season_games["home_id"]) | set(season_games["away_id"]))


def run(
    games: pd.DataFrame,
    team_games: pd.DataFrame,
    settings: RatingSettings,
    *,
    project_seasons: set[int] | None = None,
    include_scheduled: bool = False,
    until_season: int | None = None,
) -> tuple[pd.DataFrame, dict[int, Ratings], dict]:
    """Walk seasons in order.

    The first season is burn-in: it only produces final ratings for the next
    season's prior. For seasons in project_seasons, every game is projected
    with ratings solved from that season's games played on earlier dates.

    Returns (projections, final ratings by season, last prior/rater context).
    """
    poss = game_possessions(games, team_games)
    rest = rest_days(games)
    seasons = sorted(games["season"].unique())
    if until_season is not None:
        seasons = [s for s in seasons if s <= until_season]
    project_seasons = set(project_seasons or [])

    finals: dict[int, Ratings] = {}
    rows: list[pd.DataFrame] = []
    prev_final: Ratings | None = None
    context: dict = {}

    for i, season in enumerate(seasons):
        sg = games[games["season"] == season]
        team_ids = _team_ids(sg)
        season_poss = poss[poss["game_id"].isin(sg["game_id"])]

        if i == 0:
            rater = SeasonRater(sg, season_poss, team_ids, burn_in_settings(settings))
            finals[season] = rater.solve(burn_in_prior(team_ids, season_poss))
            prev_final = finals[season]
            continue

        prior = next_season_prior(prev_final, team_ids, settings)
        rater = SeasonRater(sg, season_poss, team_ids, settings)
        context = {"season": season, "rater": rater, "prior": prior}

        if season in project_seasons:
            wanted = sg["has_box"] | (include_scheduled & (sg["status"] == "scheduled"))
            targets = sg[wanted]
            for d, day in targets.groupby("game_date", sort=True):
                ratings = rater.solve(prior, cutoff=np.datetime64(pd.Timestamp(d), "D"))
                rows.append(rating_projection(ratings, day))

        finals[season] = rater.solve(prior)
        prev_final = finals[season]

    if not rows:
        return pd.DataFrame(), finals, context

    proj = pd.concat(rows, ignore_index=True)
    proj = proj.merge(rest, on="game_id", how="left")
    cols = ["game_id", "season", "season_type", "start_time", "game_date", "home_id", "away_id",
            "home_abbr", "away_abbr", "neutral", "status", "home_score", "away_score"]
    proj = games[cols].merge(proj, on="game_id", how="inner")
    proj["actual_margin"] = proj["home_score"] - proj["away_score"]
    proj["actual_total"] = proj["home_score"] + proj["away_score"]
    return proj.sort_values(["start_time", "game_id"]).reset_index(drop=True), finals, context
