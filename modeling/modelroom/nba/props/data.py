"""NBA player-game table for the prop model, built from the hoopR player box scores already downloaded.

  data/processed/nba/prop_player_games.parquet   one row per player per game (DNPs kept, minutes 0)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modelroom.common.paths import ensure, processed_dir, raw_dir

COLS = ["game_id", "season", "season_type", "game_date", "athlete_id", "athlete_display_name", "team_id",
        "team_abbreviation", "opponent_team_id", "opponent_team_abbreviation", "home_away", "minutes",
        "field_goals_made", "field_goals_attempted", "three_point_field_goals_made", "three_point_field_goals_attempted",
        "free_throws_made", "free_throws_attempted", "offensive_rebounds", "defensive_rebounds", "rebounds", "assists",
        "steals", "blocks", "turnovers", "points", "starter", "did_not_play", "reason", "athlete_position_abbreviation"]
GROUP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C", "GF": "F", "FC": "C"}


def _ids(s: pd.Series) -> pd.Series:
    """Numeric ids as clean strings ("4702656", not "4702656.0")."""
    return pd.to_numeric(s, errors="coerce").astype("Int64").astype(str)


def build() -> pd.DataFrame:
    parts = []
    for f in sorted(raw_dir("nba").glob("player_box_*.parquet")):
        d = pd.read_parquet(f)
        parts.append(d[[c for c in COLS if c in d.columns]])
    pb = pd.concat(parts, ignore_index=True)
    out = pd.DataFrame({
        "game_id": _ids(pb["game_id"]), "season": pb["season"].astype(int), "season_type": pb["season_type"],
        "game_date": pd.to_datetime(pb["game_date"]).dt.date, "player_id": _ids(pb["athlete_id"]),
        "name": pb["athlete_display_name"], "team_id": _ids(pb["team_id"]), "team": pb["team_abbreviation"],
        "opp_id": _ids(pb["opponent_team_id"]), "opp": pb["opponent_team_abbreviation"],
        "is_home": pb["home_away"].eq("home"),
        "minutes": pd.to_numeric(pb["minutes"], errors="coerce").fillna(0.0),
        "fgm": pb["field_goals_made"], "fga": pb["field_goals_attempted"],
        "fg3m": pb["three_point_field_goals_made"], "fg3a": pb["three_point_field_goals_attempted"],
        "ftm": pb["free_throws_made"], "fta": pb["free_throws_attempted"], "oreb": pb["offensive_rebounds"],
        "reb": pb["rebounds"], "ast": pb["assists"], "stl": pb["steals"], "blk": pb["blocks"], "tov": pb["turnovers"],
        "pts": pb["points"], "starter": pb["starter"].fillna(False).astype(bool),
        "dnp": pb["did_not_play"].fillna(False).astype(bool), "reason": pb["reason"],
        "pos_raw": pb["athlete_position_abbreviation"],
    })
    num = ["fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "reb", "ast", "stl", "blk", "tov", "pts"]
    out[num] = out[num].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    out["fg2m"] = out["fgm"] - out["fg3m"]
    out["pra"] = out["pts"] + out["reb"] + out["ast"]
    out["played"] = out["minutes"] > 0
    # Position group: the player's most common listed position (it's often blank on individual rows).
    pos = out.dropna(subset=["pos_raw"]).groupby("player_id")["pos_raw"].agg(lambda s: s.mode().iat[0])
    out["group"] = out["player_id"].map(pos).map(GROUP).fillna("F")
    out = out.drop_duplicates(["game_id", "player_id"]).sort_values(["game_date", "game_id", "team", "player_id"])
    ensure(processed_dir("nba"))
    out.reset_index(drop=True).to_parquet(processed_dir("nba") / "prop_player_games.parquet", index=False)
    return out


def load() -> pd.DataFrame:
    f = processed_dir("nba") / "prop_player_games.parquet"
    if not f.exists():
        return build()
    return pd.read_parquet(f)


def validate(pg: pd.DataFrame) -> dict:
    """Points = 2·(FGM − 3PM) + 3·3PM + FTM on every row; minutes ≥ 0; one row per player-game."""
    calc = 2 * pg["fg2m"] + 3 * pg["fg3m"] + pg["ftm"]
    return {"rows": int(len(pg)), "points_identity": float(np.mean(np.isclose(calc, pg["pts"]))),
            "duplicates": int(pg.duplicated(["game_id", "player_id"]).sum()), "negative_minutes": int((pg["minutes"] < 0).sum())}
