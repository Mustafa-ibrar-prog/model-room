"""NFL play filtering and team-game aggregates. Pure functions of ingested tables."""
from __future__ import annotations

import numpy as np
import pandas as pd

GARBAGE_WP_LOW = 0.10
GARBAGE_WP_HIGH = 0.90
GARBAGE_WEIGHT = 0.25


def scrimmage_plays(pbp: pd.DataFrame) -> pd.DataFrame:
    """Pass and run plays with EPA (sacks and scrambles included; kneels, spikes, 2-pt tries,
    penalty no-plays and special teams excluded), plus a garbage-time weight."""
    p = pbp[pbp["play_type"].isin(["pass", "run"]) & (pbp["two_point_attempt"].fillna(0) == 0) & pbp["epa"].notna()]
    p = p[p["posteam"].notna() & p["defteam"].notna()].copy()
    wp = p["wp"]
    competitive = wp.between(GARBAGE_WP_LOW, GARBAGE_WP_HIGH) | wp.isna()
    p["w"] = np.where(competitive, 1.0, GARBAGE_WEIGHT)
    p["is_pass"] = p["qb_dropback"].fillna(0).astype(float) == 1
    p["qb_id"] = p["passer_id"].where(p["passer_id"].notna(), p["passer_player_id"])
    p["qb_name"] = p["passer"].where(p["passer"].notna(), p["passer_player_name"])
    return p


def team_games(plays: pd.DataFrame) -> pd.DataFrame:
    """One row per team (offense) per game with weighted efficiency measures."""
    p = plays.assign(
        wepa=plays["epa"] * plays["w"],
        wsucc=(plays["epa"] > 0).astype(float) * plays["w"],
        pass_w=plays["w"] * plays["is_pass"],
        rush_w=plays["w"] * ~plays["is_pass"],
    )
    p["pass_wepa"] = p["wepa"] * p["is_pass"]
    p["rush_wepa"] = p["wepa"] * ~p["is_pass"]
    p["turnover"] = p["interception"].fillna(0) + p["fumble_lost"].fillna(0)
    p["third"] = p["down"] == 3
    g = p.groupby(["game_id", "posteam", "defteam"], sort=False)
    out = g.agg(
        season=("season", "first"), week=("week", "first"), home_team=("home_team", "first"),
        plays=("epa", "size"), wplays=("w", "sum"), wepa=("wepa", "sum"), wsucc=("wsucc", "sum"),
        pass_w=("pass_w", "sum"), pass_wepa=("pass_wepa", "sum"), rush_w=("rush_w", "sum"), rush_wepa=("rush_wepa", "sum"),
        yards=("yards_gained", "sum"), turnovers=("turnover", "sum"),
        third_att=("third", "sum"), third_conv=("third_down_converted", "sum"),
    ).reset_index().rename(columns={"posteam": "team", "defteam": "opp"})
    out["epa"] = out["wepa"] / out["wplays"]
    out["success"] = out["wsucc"] / out["wplays"]
    out["pass_epa"] = np.where(out["pass_w"] > 0, out["pass_wepa"] / out["pass_w"].where(out["pass_w"] > 0), np.nan)
    out["rush_epa"] = np.where(out["rush_w"] > 0, out["rush_wepa"] / out["rush_w"].where(out["rush_w"] > 0), np.nan)
    out["ypp"] = out["yards"] / out["plays"]
    out["dropback_share"] = out["pass_w"] / out["wplays"]

    # Red zone: drives that reached the opponent 20, and how many ended in a touchdown.
    rz = plays[plays["yardline_100"] <= 20].groupby(["game_id", "posteam", "fixed_drive"])["fixed_drive_result"].first().reset_index()
    rz = rz.assign(td=rz["fixed_drive_result"].eq("Touchdown")).groupby(["game_id", "posteam"]).agg(rz_drives=("td", "size"), rz_td=("td", "sum"))
    out = out.merge(rz.reset_index().rename(columns={"posteam": "team"}), on=["game_id", "team"], how="left")
    out[["rz_drives", "rz_td"]] = out[["rz_drives", "rz_td"]].fillna(0)
    out["is_home"] = out["team"] == out["home_team"]
    return out


def qb_dropbacks(plays: pd.DataFrame) -> pd.DataFrame:
    """Per QB per team-game: weighted dropbacks and EPA (for QB values)."""
    d = plays[plays["is_pass"] & plays["qb_id"].notna()].assign(wepa=lambda x: x["epa"] * x["w"])
    g = d.groupby(["game_id", "posteam", "qb_id"], sort=False).agg(
        qb_name=("qb_name", "last"), dropbacks=("w", "sum"), wepa=("wepa", "sum"),
    ).reset_index().rename(columns={"posteam": "team"})
    return g


def indoor_by_stadium(games: pd.DataFrame) -> dict:
    """Each stadium's usual roof (from games already played): True if not outdoors."""
    known = games[games["roof"].notna()]
    mode = known.groupby("stadium_id")["roof"].agg(lambda s: s.value_counts().idxmax())
    return {k: v != "outdoors" for k, v in mode.items()}
