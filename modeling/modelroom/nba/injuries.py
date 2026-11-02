"""NBA injury impact.

Player value = average Hollinger Game Score per game over the player's
appearances in his team's previous 10 games (earlier games only).

    GmSc = PTS + 0.4·FGM − 0.7·FGA − 0.4·(FTA − FTM) + 0.7·OREB + 0.3·DREB
           + STL + 0.7·AST + 0.7·BLK − 0.4·PF − TOV

A rotation player (5+ appearances and 15+ minutes a game over those 10 team
games) who is listed on the game roster but does not play counts as absent.

    injury_value_diff = Σ value(absent away players) − Σ value(absent home players)
    margin adjustment = k × injury_value_diff

k (points of margin per unit of Game Score) is fitted on training seasons.

For upcoming games the absences come from an injury report file instead
(Out = 1.0, Doubtful = 0.75). With no report, the adjustment is reported as
missing, never as zero.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common.download import DownloadError, fetch
from modelroom.common.paths import ensure, processed_dir, raw_dir

BASE = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/player_box/parquet"
WINDOW = 10
MIN_APPEARANCES = 5
MIN_MINUTES = 15.0
STATUS_WEIGHT = {"out": 1.0, "doubtful": 0.75}
COLS = [
    "game_id", "season", "athlete_id", "athlete_display_name", "team_id", "minutes",
    "field_goals_made", "field_goals_attempted", "free_throws_made", "free_throws_attempted",
    "offensive_rebounds", "defensive_rebounds", "assists", "steals", "blocks", "turnovers",
    "fouls", "points", "did_not_play",
]


def download(seasons: list[int]) -> None:
    out = ensure(raw_dir("nba"))
    for s in seasons:
        try:
            fetch(f"{BASE}/player_box_{s}.parquet", out / f"player_box_{s}.parquet")
        except DownloadError:
            if s != seasons[-1]:
                raise


def build(seasons: list[int]) -> pd.DataFrame:
    parts = []
    for s in seasons:
        f = raw_dir("nba") / f"player_box_{s}.parquet"
        if f.exists():
            parts.append(pd.read_parquet(f, columns=COLS))
    pb = pd.concat(parts, ignore_index=True)
    num = [c for c in COLS if c not in ("athlete_display_name", "did_not_play")]
    for c in num:
        pb[c] = pd.to_numeric(pb[c], errors="coerce")
    pb = pb.dropna(subset=["game_id", "athlete_id", "team_id"])
    pb["minutes"] = pb["minutes"].fillna(0.0)
    pb["played"] = (pb["minutes"] > 0) & ~pb["did_not_play"].fillna(False).astype(bool)
    stats = pb[num].fillna(0.0)
    pb["gmsc"] = (
        stats["points"] + 0.4 * stats["field_goals_made"] - 0.7 * stats["field_goals_attempted"]
        - 0.4 * (stats["free_throws_attempted"] - stats["free_throws_made"])
        + 0.7 * stats["offensive_rebounds"] + 0.3 * stats["defensive_rebounds"]
        + stats["steals"] + 0.7 * stats["assists"] + 0.7 * stats["blocks"]
        - 0.4 * stats["fouls"] - stats["turnovers"]
    ).where(pb["played"], 0.0)
    out = pb[["game_id", "season", "athlete_id", "athlete_display_name", "team_id", "minutes", "played", "gmsc"]]
    out = out.astype({"game_id": "int64", "athlete_id": "int64", "team_id": "int64", "season": "int64"})
    ensure(processed_dir("nba"))
    out.to_parquet(processed_dir("nba") / "player_games.parquet", index=False)
    return out


def load() -> pd.DataFrame | None:
    f = processed_dir("nba") / "player_games.parquet"
    return pd.read_parquet(f) if f.exists() else None


def player_form(games: pd.DataFrame, player_games: pd.DataFrame) -> pd.DataFrame:
    """Rolling pre-game form for every player on every team game (earlier games only)."""
    g = games[games["has_box"]][["game_id", "season", "start_time", "home_id", "away_id"]]
    team_seq = pd.concat([g.assign(team_id=g["home_id"]), g.assign(team_id=g["away_id"])])[
        ["game_id", "season", "start_time", "team_id"]
    ].sort_values(["team_id", "season", "start_time", "game_id"])
    team_seq["seq"] = team_seq.groupby(["team_id", "season"]).cumcount()

    pg = player_games.merge(team_seq[["game_id", "team_id", "seq"]], on=["game_id", "team_id"], how="inner")
    # Dense grid: every player x every team game of that team-season (0 when not listed).
    keys = pg[["athlete_id", "team_id", "season"]].drop_duplicates()
    grid = keys.merge(team_seq[["team_id", "season", "game_id", "seq"]], on=["team_id", "season"])
    grid = grid.merge(pg[["athlete_id", "game_id", "minutes", "played", "gmsc"]], on=["athlete_id", "game_id"], how="left")
    grid["listed"] = grid["played"].notna()
    grid[["minutes", "gmsc"]] = grid[["minutes", "gmsc"]].fillna(0.0)
    grid["played"] = grid["played"].fillna(False).astype(float)
    grid = grid.sort_values(["athlete_id", "team_id", "season", "seq"])

    grp = grid.groupby(["athlete_id", "team_id", "season"], sort=False)
    prev = lambda col: grp[col].transform(lambda s: s.shift(1).rolling(WINDOW, min_periods=1).sum())
    grid["apps"] = prev("played").fillna(0.0)
    min_sum = prev("minutes").fillna(0.0)
    gmsc_sum = prev("gmsc").fillna(0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        grid["avg_minutes"] = np.where(grid["apps"] > 0, min_sum / grid["apps"], 0.0)
        grid["value"] = np.where(grid["apps"] > 0, gmsc_sum / grid["apps"], 0.0)
    grid["rotation"] = (grid["apps"] >= MIN_APPEARANCES) & (grid["avg_minutes"] >= MIN_MINUTES)
    return grid


def absence_values(games: pd.DataFrame, player_games: pd.DataFrame) -> pd.DataFrame:
    """Per completed game: absent rotation value for each side and the difference."""
    grid = player_form(games, player_games)
    absent = grid[grid["listed"] & (grid["played"] == 0) & grid["rotation"]]
    by_team = absent.groupby(["game_id", "team_id"])["value"].sum()
    g = games[games["has_box"]][["game_id", "home_id", "away_id"]]
    home = by_team.reindex(list(zip(g["game_id"], g["home_id"]))).fillna(0.0).to_numpy()
    away = by_team.reindex(list(zip(g["game_id"], g["away_id"]))).fillna(0.0).to_numpy()
    return pd.DataFrame(
        {"game_id": g["game_id"].to_numpy(), "home_absent_value": home, "away_absent_value": away,
         "injury_value_diff": away - home}
    )


def fit_injury_coefficient(train: pd.DataFrame) -> float:
    """k from least squares of the rating residual on absent value (with rest terms as controls)."""
    from .project import REST_ADV_CAP

    t = train.dropna(subset=["injury_value_diff"])
    b2b = t["away_b2b"].astype(float) - t["home_b2b"].astype(float)
    rest_adv = t["home_rest"].clip(upper=REST_ADV_CAP) - t["away_rest"].clip(upper=REST_ADV_CAP)
    X = np.column_stack([t["injury_value_diff"], b2b, rest_adv])
    y = (t["actual_margin"] - t["margin_raw"]).to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[0])


def current_values(games: pd.DataFrame, player_games: pd.DataFrame, season: int) -> pd.DataFrame:
    """Each player's latest value for his current team (from games already played)."""
    grid = player_form(games, player_games)
    grid = grid[grid["season"] == season].copy()
    if grid.empty:
        return pd.DataFrame(columns=["athlete_id", "team_id", "value", "rotation", "name"])
    # Form going into the team's next game = rolling window including the last game.
    grid = grid.sort_values(["athlete_id", "team_id", "seq"])
    g = grid.groupby(["athlete_id", "team_id"], sort=False)
    last = g.tail(WINDOW)
    agg = last.groupby(["athlete_id", "team_id"]).agg(apps=("played", "sum"), minutes=("minutes", "sum"), gmsc=("gmsc", "sum"))
    agg["avg_minutes"] = np.where(agg["apps"] > 0, agg["minutes"] / agg["apps"], 0.0)
    agg["value"] = np.where(agg["apps"] > 0, agg["gmsc"] / agg["apps"], 0.0)
    agg["rotation"] = (agg["apps"] >= MIN_APPEARANCES) & (agg["avg_minutes"] >= MIN_MINUTES)
    names = player_games.drop_duplicates("athlete_id", keep="last").set_index("athlete_id")["athlete_display_name"]
    agg = agg.reset_index()
    agg["name"] = agg["athlete_id"].map(names)
    return agg


def report_adjustments(report: pd.DataFrame | None, values: pd.DataFrame, upcoming: pd.DataFrame, k: float | None) -> pd.DataFrame:
    """injury_adj (home perspective) for upcoming games from an injury report.

    report columns: game_date (YYYY-MM-DD), team_abbr, player, status.
    Returns NaN for every game when there is no report or no fitted k.
    """
    out = upcoming[["game_id"]].copy()
    out["injury_adj"] = np.nan
    out["injury_detail"] = [[] for _ in range(len(out))]
    if report is None or k is None or report.empty:
        return out
    rep = report.copy()
    rep["weight"] = rep["status"].str.lower().map(STATUS_WEIGHT).fillna(0.0)
    rep["key"] = rep["player"].str.lower().str.strip()
    vals = values.assign(key=values["name"].str.lower().str.strip())
    adjs, details = [], []
    for _, gm in upcoming.iterrows():
        side_value = {}
        detail = []
        for side, tid, abbr in (("home", gm["home_id"], gm["home_abbr"]), ("away", gm["away_id"], gm["away_abbr"])):
            r = rep[(rep["team_abbr"] == abbr) & (rep["game_date"] == str(gm["game_date"])) & (rep["weight"] > 0)]
            v = r.merge(vals[(vals["team_id"] == tid) & vals["rotation"]], on="key", how="inner")
            side_value[side] = float((v["value"] * v["weight"]).sum())
            detail += [{"team": abbr, "player": p, "status": s, "points": round(-k * val * w, 2) if side == "home" else round(k * val * w, 2)}
                       for p, s, val, w in zip(v["player"], v["status"], v["value"], v["weight"])]
        adjs.append(k * (side_value["away"] - side_value["home"]))
        details.append(detail)
    out["injury_adj"] = adjs
    out["injury_detail"] = details
    return out


def load_report(path: Path | None = None) -> pd.DataFrame | None:
    path = path or (processed_dir("nba").parent.parent / "nba" / "injuries.csv")
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype=str)
    need = {"game_date", "team_abbr", "player", "status"}
    if not need <= set(df.columns):
        raise ValueError(f"{path} needs columns {sorted(need)}")
    return df
