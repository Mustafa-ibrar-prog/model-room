"""NBA data ingestion: hoopR (sportsdataverse) schedules and team box scores.

Produces two normalized tables in processed/nba/:
  games.parquet       one row per game (schedule, status, scores, periods)
  team_games.parquet  one row per team per completed game (box-score counts)

Seasons are named by the year they end (2027 = 2026-27), as in hoopR.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common.download import DownloadError, fetch
from modelroom.common.paths import ensure, processed_dir, raw_dir

BASE = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba"
FIRST_SEASON = 2016
SOURCE = "hoopR / sportsdataverse (ESPN)"

SCHEDULE_COLS = [
    "game_id", "season", "season_type", "type_abbreviation", "game_date", "game_date_time",
    "neutral_site", "status_type_name", "status_type_completed", "status_period",
    "home_id", "home_abbreviation", "home_display_name", "home_score",
    "away_id", "away_abbreviation", "away_display_name", "away_score",
    "venue_full_name", "notes_headline",
]
BOX_COLS = [
    "game_id", "season", "team_id", "opponent_team_id", "team_home_away", "team_score",
    "field_goals_attempted", "free_throws_attempted", "offensive_rebounds", "total_turnovers", "turnovers",
]
SEASON_TYPES = {2: "regular", 3: "postseason", 5: "play_in"}


def current_season(today: date | None = None) -> int:
    today = today or date.today()
    return today.year + 1 if today.month >= 8 else today.year


def download(seasons: list[int]) -> list[Path]:
    out = ensure(raw_dir("nba"))
    files = []
    for s in seasons:
        for kind, name in (("schedules", f"nba_schedule_{s}.parquet"), ("team_box", f"team_box_{s}.parquet")):
            dest = out / name
            try:
                files.append(fetch(f"{BASE}/{kind}/parquet/{name}", dest))
            except DownloadError:
                if s == seasons[-1] and kind == "team_box":
                    continue  # season not started yet
                raise
    return files


def _status(row) -> str:
    name = str(row["status_type_name"] or "")
    if name == "STATUS_FINAL" or row["status_type_completed"] is True:
        return "final"
    if name in ("STATUS_SCHEDULED",):
        return "scheduled"
    if name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
        return "postponed"
    if name in ("STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_END_PERIOD"):
        return "in_progress"
    return name.replace("STATUS_", "").lower() or "unknown"


def build(seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = raw_dir("nba")
    sched_parts, box_parts = [], []
    for s in seasons:
        sched_parts.append(pd.read_parquet(raw / f"nba_schedule_{s}.parquet", columns=SCHEDULE_COLS))
        box_file = raw / f"team_box_{s}.parquet"
        if box_file.exists():
            box_parts.append(pd.read_parquet(box_file, columns=BOX_COLS))
    sched = pd.concat(sched_parts, ignore_index=True)
    box = pd.concat(box_parts, ignore_index=True) if box_parts else pd.DataFrame(columns=BOX_COLS)

    # Keep regular season, play-in and playoffs. Drop preseason and All-Star.
    sched = sched[sched["season_type"].isin(SEASON_TYPES) & (sched["type_abbreviation"] != "ALLSTAR")].copy()

    # NBA franchises only: teams that appear in at least 40 regular-season games that season.
    reg = sched[sched["season_type"] == 2]
    counts = pd.concat([reg[["season", "home_id"]].rename(columns={"home_id": "tid"}),
                        reg[["season", "away_id"]].rename(columns={"away_id": "tid"})])
    counts = counts.groupby(["season", "tid"]).size()
    valid = set(counts[counts >= 40].index)
    keep = [(s, h) in valid and (s, a) in valid for s, h, a in zip(sched["season"], sched["home_id"], sched["away_id"])]
    sched = sched[keep]

    games = pd.DataFrame(
        {
            "game_id": sched["game_id"].astype("int64"),
            "season": sched["season"].astype(int),
            "season_type": sched["season_type"].map(SEASON_TYPES),
            "start_time": pd.to_datetime(sched["game_date_time"], utc=True),
            "game_date": pd.to_datetime(sched["game_date"]).dt.date,
            "home_id": sched["home_id"].astype(int),
            "away_id": sched["away_id"].astype(int),
            "home_abbr": sched["home_abbreviation"],
            "away_abbr": sched["away_abbreviation"],
            "home_name": sched["home_display_name"],
            "away_name": sched["away_display_name"],
            "neutral": sched["neutral_site"].fillna(False).astype(bool),
            "status": sched.apply(_status, axis=1),
            "periods": pd.to_numeric(sched["status_period"], errors="coerce"),
            "venue": sched["venue_full_name"],
        }
    ).drop_duplicates("game_id").sort_values(["start_time", "game_id"]).reset_index(drop=True)

    box = box[box["game_id"].isin(games["game_id"])].copy()
    team_games = pd.DataFrame(
        {
            "game_id": box["game_id"].astype("int64"),
            "team_id": box["team_id"].astype(int),
            "opp_id": box["opponent_team_id"].astype(int),
            "is_home": box["team_home_away"].eq("home"),
            "pts": pd.to_numeric(box["team_score"], errors="coerce"),
            "fga": pd.to_numeric(box["field_goals_attempted"], errors="coerce"),
            "fta": pd.to_numeric(box["free_throws_attempted"], errors="coerce"),
            "oreb": pd.to_numeric(box["offensive_rebounds"], errors="coerce"),
            # total_turnovers = player + team turnovers. The 2017-18 file lacks
            # team turnovers; fall back to player turnovers there and flag it
            # (undercounts possessions by about one per game).
            "tov": pd.to_numeric(box["total_turnovers"], errors="coerce").fillna(
                pd.to_numeric(box["turnovers"], errors="coerce")
            ),
            "tov_player_only": pd.to_numeric(box["total_turnovers"], errors="coerce").isna(),
        }
    ).drop_duplicates(["game_id", "team_id"])

    # A game is usable only if it's final and both team rows are complete.
    complete = team_games.dropna().groupby("game_id").size()
    complete_ids = set(complete[complete == 2].index)
    final_ids = set(games.loc[games["status"] == "final", "game_id"])
    usable = final_ids & complete_ids
    team_games = team_games[team_games["game_id"].isin(usable)].reset_index(drop=True)

    scores = team_games.pivot_table(index="game_id", columns="is_home", values="pts")
    games["home_score"] = games["game_id"].map(scores.get(True))
    games["away_score"] = games["game_id"].map(scores.get(False))
    games["has_box"] = games["game_id"].isin(usable)
    # Finals with a missing box score can't be rated; flag rather than guess.
    games.loc[(games["status"] == "final") & ~games["has_box"], "status"] = "final_no_box"
    games["periods"] = np.where(games["status"] == "final", games["periods"].fillna(4).clip(lower=4), games["periods"])
    return games, team_games


def run(seasons: list[int] | None = None, *, skip_download: bool = False) -> dict:
    seasons = seasons or list(range(FIRST_SEASON, current_season() + 1))
    if not skip_download:
        download(seasons)
    games, team_games = build(seasons)
    out = ensure(processed_dir("nba"))
    games.to_parquet(out / "games.parquet", index=False)
    team_games.to_parquet(out / "team_games.parquet", index=False)
    return {
        "seasons": f"{seasons[0]}-{seasons[-1]}",
        "games": int(len(games)),
        "final_with_box": int(games["has_box"].sum()),
        "final_missing_box": int((games["status"] == "final_no_box").sum()),
        "scheduled": int((games["status"] == "scheduled").sum()),
        "latest_final": str(games.loc[games["has_box"], "game_date"].max()),
    }


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    d = processed_dir("nba")
    if not (d / "games.parquet").exists():
        raise FileNotFoundError("No NBA data yet. Run: python -m modelroom nba ingest")
    return pd.read_parquet(d / "games.parquet"), pd.read_parquet(d / "team_games.parquet")
