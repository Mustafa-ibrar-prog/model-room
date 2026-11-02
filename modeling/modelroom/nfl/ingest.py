"""NFL data ingestion from nflverse.

Raw (unchanged)           data/raw/nfl/games.csv, play_by_play_<season>.parquet, injuries_<season>.parquet
Processed                 data/processed/nfl/games.parquet         one row per game
                          data/processed/nfl/market_lines.parquet  one row per game x market (nflverse line)
                          data/processed/nfl/pbp.parquet           modeling columns from play-by-play
                          data/processed/nfl/injuries.parquet      injury report rows
"""
from __future__ import annotations

import os
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common.download import DownloadError, fetch, sha256_file
from modelroom.common.paths import ensure, processed_dir, raw_dir
from modelroom.sources import state

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
PBP_SEASONS_BACK = 3  # previous three completed seasons plus the current one

# Franchise continuity for relocated teams (nflverse uses the code in force at the time).
FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

PBP_COLUMNS = [
    "game_id", "play_id", "season", "week", "season_type", "home_team", "away_team", "posteam", "defteam",
    "qtr", "game_seconds_remaining", "half_seconds_remaining", "down", "ydstogo", "yardline_100",
    "play_type", "pass", "rush", "qb_dropback", "qb_scramble", "sack", "penalty", "two_point_attempt",
    "epa", "success", "wp", "def_wp", "score_differential", "posteam_score", "defteam_score",
    "passer_player_id", "passer_player_name", "rusher_player_id", "cpoe", "air_yards", "yards_gained",
    "passer_id", "passer", "interception", "fumble_lost", "third_down_converted", "third_down_failed",
    "fixed_drive", "fixed_drive_result", "game_date",
]
INJURY_COLUMNS = ["season", "week", "game_type", "team", "gsis_id", "full_name", "position",
                  "report_status", "practice_status", "report_primary_injury", "date_modified"]


def current_season(today: date | None = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 8 else today.year - 1


# --------------------------------------------------------------------------- games
def download_games() -> Path:
    path = fetch(GAMES_URL, ensure(raw_dir("nfl")) / "games.csv")
    state.record("nflverse_games", file=str(path.name), sha256=sha256_file(path))
    return path


def build_games() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(raw_dir("nfl") / "games.csv", dtype={"old_game_id": str, "gsis": str, "espn": str})
    g = raw.copy()
    for c in ("home_team", "away_team"):
        g[c] = g[c].replace(FRANCHISE)
    # Kickoff time is US Eastern per nflverse docs.
    kickoff = pd.to_datetime(g["gameday"] + " " + g["gametime"].fillna("13:00"), errors="coerce")
    g["start_time"] = kickoff.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    played = g["home_score"].notna() & g["away_score"].notna()
    games = pd.DataFrame(
        {
            "game_id": g["game_id"], "season": g["season"].astype(int), "game_type": g["game_type"],
            "week": g["week"].astype(int), "game_date": pd.to_datetime(g["gameday"]).dt.date,
            "start_time": g["start_time"], "home_team": g["home_team"], "away_team": g["away_team"],
            "home_score": g["home_score"], "away_score": g["away_score"],
            "status": np.where(played, "final", "scheduled"),
            "overtime": g["overtime"], "neutral": g["location"].eq("Neutral"),
            "home_rest": g["home_rest"], "away_rest": g["away_rest"], "div_game": g["div_game"].astype(bool),
            "home_qb_id": g["home_qb_id"], "away_qb_id": g["away_qb_id"],
            "home_qb_name": g["home_qb_name"], "away_qb_name": g["away_qb_name"],
            "roof": g["roof"], "surface": g["surface"], "temp": g["temp"], "wind": g["wind"],
            "stadium_id": g["stadium_id"], "stadium": g["stadium"],
        }
    )
    # Market lines: converted to Model Room convention (home spread, negative = home favored).
    lines = []
    for _, r in g[g["spread_line"].notna() | g["total_line"].notna()].iterrows():
        common = {"game_id": r["game_id"], "league": "nfl", "source": "nflverse_games",
                  "sportsbook": None, "captured_at": None,
                  "capture_note": "nflverse does not document when this line was captured"}
        if pd.notna(r["spread_line"]):
            lines.append({**common, "market": "spread", "line": -float(r["spread_line"]),
                          "home_price": r["home_spread_odds"], "away_price": r["away_spread_odds"],
                          "over_price": np.nan, "under_price": np.nan})
        if pd.notna(r["total_line"]):
            lines.append({**common, "market": "total", "line": float(r["total_line"]),
                          "home_price": np.nan, "away_price": np.nan,
                          "over_price": r["over_odds"], "under_price": r["under_odds"]})
        if pd.notna(r["home_moneyline"]):
            lines.append({**common, "market": "moneyline", "line": np.nan,
                          "home_price": r["home_moneyline"], "away_price": r["away_moneyline"],
                          "over_price": np.nan, "under_price": np.nan})
    market = pd.DataFrame(lines)
    return games, market


# ----------------------------------------------------------------- play-by-play
def pbp_seasons(today: date | None = None) -> list[int]:
    cur = current_season(today)
    return list(range(cur - PBP_SEASONS_BACK, cur + 1))


def acquire_release_files(kind: str, seasons: list[int], local_dir: Path | None) -> list[Path]:
    """Copy from a local folder if given (or MODELROOM_NFL_DIR), else download from nflverse releases."""
    local_dir = local_dir or (Path(os.environ["MODELROOM_NFL_DIR"]) if os.environ.get("MODELROOM_NFL_DIR") else None)
    out = ensure(raw_dir("nfl"))
    prefix = {"pbp": "play_by_play", "injuries": "injuries"}[kind]
    got = []
    for s in seasons:
        name = f"{prefix}_{s}.parquet"
        dest = out / name
        if local_dir is not None:
            src = local_dir / name
            if src.exists():
                shutil.copy2(src, dest)
                got.append(dest)
            continue
        try:
            got.append(fetch(f"{RELEASE}/{kind}/{name}", dest))
        except DownloadError:
            if s != seasons[-1]:
                raise
    return got


def available_pbp_seasons() -> list[int]:
    return sorted(int(f.stem.rsplit("_", 1)[1]) for f in raw_dir("nfl").glob("play_by_play_*.parquet"))


def build_pbp(seasons: list[int]) -> pd.DataFrame:
    parts = []
    for s in seasons:
        f = raw_dir("nfl") / f"play_by_play_{s}.parquet"
        if not f.exists():
            continue
        df = pd.read_parquet(f)
        missing = [c for c in PBP_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{f.name} is missing expected nflverse columns: {missing}")
        parts.append(df[PBP_COLUMNS])
    if not parts:
        return pd.DataFrame(columns=PBP_COLUMNS)
    pbp = pd.concat(parts, ignore_index=True)
    for c in ("home_team", "away_team", "posteam", "defteam"):
        pbp[c] = pbp[c].replace(FRANCHISE)
    return pbp


def build_injuries(seasons: list[int]) -> pd.DataFrame:
    parts = []
    for s in seasons:
        f = raw_dir("nfl") / f"injuries_{s}.parquet"
        if f.exists():
            df = pd.read_parquet(f)
            parts.append(df[[c for c in INJURY_COLUMNS if c in df.columns]])
    if not parts:
        return pd.DataFrame(columns=INJURY_COLUMNS)
    inj = pd.concat(parts, ignore_index=True)
    # A player can appear twice in one week's file (report revised); keep the latest.
    if "date_modified" in inj:
        inj = inj.sort_values("date_modified", na_position="first")
    inj = inj.drop_duplicates(["season", "week", "game_type", "team", "gsis_id"], keep="last")
    # report_status is blank for players on the practice report without a game designation.
    inj["has_game_designation"] = inj["report_status"].notna()
    return inj.reset_index(drop=True)


# ----------------------------------------------------------------------- run
def run(*, skip_download: bool = False, local_dir: Path | None = None) -> dict:
    summary: dict = {}
    if not skip_download:
        download_games()
    games, market = build_games()
    out = ensure(processed_dir("nfl"))
    games.to_parquet(out / "games.parquet", index=False)
    market.to_parquet(out / "market_lines.parquet", index=False)
    summary["games"] = {"rows": len(games), "final": int((games["status"] == "final").sum()),
                        "scheduled": int((games["status"] == "scheduled").sum()),
                        "latest_final": str(games.loc[games["status"] == "final", "game_date"].max())}
    summary["market_lines"] = int(len(market))

    seasons = pbp_seasons()
    for kind, sid in (("pbp", "nflverse_pbp"), ("injuries", "nflverse_injuries")):
        try:
            files = [] if skip_download and local_dir is None else acquire_release_files(kind, seasons, local_dir)
            if files:
                state.record(sid, files=[f.name for f in files])
        except DownloadError as e:
            state.record_failure(sid, str(e))
            summary[f"{kind}_error"] = str(e)

    pbp = build_pbp(available_pbp_seasons())  # every season on disk (history for backtests + current)
    if len(pbp):
        pbp.to_parquet(out / "pbp.parquet", index=False)
    summary["pbp"] = {"rows": int(len(pbp)), "seasons": sorted(pbp["season"].unique().tolist()) if len(pbp) else []}
    inj = build_injuries(seasons)
    if len(inj):
        inj.to_parquet(out / "injuries.parquet", index=False)
    summary["injuries"] = int(len(inj))
    return summary


def load_games() -> pd.DataFrame:
    f = processed_dir("nfl") / "games.parquet"
    if not f.exists():
        raise FileNotFoundError("No NFL data yet. Run: python -m modelroom nfl ingest")
    return pd.read_parquet(f)
