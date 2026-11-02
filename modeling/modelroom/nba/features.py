"""Box-score and schedule features. Pure functions of the ingested tables."""
from __future__ import annotations

import numpy as np
import pandas as pd

REST_CAP = 4  # days; also used for a team's first game of the season


def game_possessions(games: pd.DataFrame, team_games: pd.DataFrame) -> pd.DataFrame:
    """Per completed game: possessions, minutes, pace, and each side's efficiency.

    possessions_team = FGA − OREB + TOV + 0.44 × FTA
    possessions_game = mean of the two teams' estimates
    minutes          = 48 + 5 × (periods − 4)
    pace             = possessions_game × 48 / minutes
    efficiency       = 100 × points / possessions_game
    """
    tg = team_games.copy()
    tg["poss"] = tg["fga"] - tg["oreb"] + tg["tov"] + 0.44 * tg["fta"]
    home = tg[tg["is_home"]].set_index("game_id")
    away = tg[~tg["is_home"]].set_index("game_id")
    g = games[games["has_box"]].set_index("game_id")
    g = g.join(home[["pts", "poss"]].add_prefix("home_"), how="inner").join(away[["pts", "poss"]].add_prefix("away_"), how="inner")
    out = pd.DataFrame(index=g.index)
    out["possessions"] = (g["home_poss"] + g["away_poss"]) / 2
    out["minutes"] = 48 + 5 * (g["periods"].astype(float) - 4)
    out["pace"] = out["possessions"] * 48 / out["minutes"]
    out["home_eff"] = 100 * g["home_pts"] / out["possessions"]
    out["away_eff"] = 100 * g["away_pts"] / out["possessions"]
    out["home_ppp"] = g["home_pts"] / out["possessions"]
    out["away_ppp"] = g["away_pts"] / out["possessions"]
    return out.reset_index()


def rest_days(games: pd.DataFrame) -> pd.DataFrame:
    """Days since each team's previous scheduled game in the same season.

    Uses the schedule (not results), so it works for upcoming games too.
    Postponed games are ignored. Values are capped at REST_CAP; a team's first
    game of a season gets REST_CAP. back_to_back means rest == 1.
    """
    g = games[games["status"] != "postponed"][["game_id", "season", "game_date", "home_id", "away_id"]]
    long = pd.concat(
        [
            g.rename(columns={"home_id": "team_id"})[["game_id", "season", "game_date", "team_id"]].assign(side="home"),
            g.rename(columns={"away_id": "team_id"})[["game_id", "season", "game_date", "team_id"]].assign(side="away"),
        ]
    )
    long["game_date"] = pd.to_datetime(long["game_date"])
    long = long.sort_values(["team_id", "season", "game_date", "game_id"])
    prev = long.groupby(["team_id", "season"])["game_date"].shift(1)
    long["rest"] = (long["game_date"] - prev).dt.days.fillna(REST_CAP).clip(upper=REST_CAP).astype(int)
    wide = long.pivot_table(index="game_id", columns="side", values="rest")
    return pd.DataFrame(
        {
            "game_id": wide.index,
            "home_rest": wide["home"].astype(int).values,
            "away_rest": wide["away"].astype(int).values,
        }
    ).assign(home_b2b=lambda d: d["home_rest"] <= 1, away_b2b=lambda d: d["away_rest"] <= 1)


def venue_sign(games: pd.DataFrame) -> np.ndarray:
    """+1 for a true home game, 0 for neutral sites."""
    return np.where(games["neutral"].to_numpy(), 0.0, 1.0)
