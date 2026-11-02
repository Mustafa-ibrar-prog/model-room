"""NFL walk-forward: each game is projected with plays from earlier dates only."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from modelroom.common.paths import processed_dir

from . import ingest
from .config import RatingSettings
from .features import indoor_by_stadium, qb_dropbacks, scrimmage_plays, team_games
from .qb import QBModel
from .ratings import EPARater

REST_CAP = 7


@dataclass
class Prepared:
    games: pd.DataFrame
    plays: pd.DataFrame
    tg: pd.DataFrame
    qbd: pd.DataFrame
    indoor: dict


def prepare(games: pd.DataFrame | None = None, pbp: pd.DataFrame | None = None) -> Prepared:
    games = games if games is not None else ingest.load_games()
    if pbp is None:
        f = processed_dir("nfl") / "pbp.parquet"
        if not f.exists():
            raise FileNotFoundError("No NFL play-by-play yet. Run: python -m modelroom nfl ingest")
        pbp = pd.read_parquet(f)
    plays = scrimmage_plays(pbp)
    tg = team_games(plays)
    meta = games[["game_id", "game_date", "start_time", "neutral"]]
    tg = tg.merge(meta, on="game_id", how="inner")
    qbd = qb_dropbacks(plays).merge(games[["game_id", "game_date", "season"]], on="game_id", how="inner")
    return Prepared(games, plays, tg, qbd, indoor_by_stadium(games))


def run(prep: Prepared, settings: RatingSettings, replacement: float, *, project_seasons: set[int],
        include_scheduled: bool = False) -> pd.DataFrame:
    rater = EPARater(prep.tg, settings)
    qbm = QBModel(prep.qbd, prep.tg, settings.qb_shrink_dropbacks, replacement, settings.season_carry, settings.half_life_games)
    g = prep.games
    have_pbp = set(prep.tg["game_id"])
    want = g["season"].isin(project_seasons) & (
        ((g["status"] == "final") & g["game_id"].isin(have_pbp)) | (include_scheduled & (g["status"] == "scheduled"))
    )
    targets = g[want].sort_values("start_time")
    rows = []
    for d, day in targets.groupby("game_date", sort=True):
        cutoff = np.datetime64(pd.Timestamp(d), "D")
        season = int(day["season"].iloc[0])
        r = rater.solve(cutoff, season)
        vals = qbm.values(cutoff, season)
        for _, x in day.iterrows():
            if x["home_team"] not in r.teams or x["away_team"] not in r.teams:
                continue
            hi, ai = r.idx(x["home_team"]), r.idx(x["away_team"])
            venue = 0.0 if x["neutral"] else 1.0
            qh, qh_info = qbm.adjustment(x["home_team"], x["home_qb_id"] if pd.notna(x["home_qb_id"]) else None, cutoff, season, vals)
            qa, qa_info = qbm.adjustment(x["away_team"], x["away_qb_id"] if pd.notna(x["away_qb_id"]) else None, cutoff, season, vals)
            rest_adv = float(np.clip((x["home_rest"] or 0) - (x["away_rest"] or 0), -REST_CAP, REST_CAP)) if pd.notna(x["home_rest"]) and pd.notna(x["away_rest"]) else 0.0
            rows.append({
                "game_id": x["game_id"],
                "exp_off_home": r.mu + r.off[hi] + r.deff[ai] + r.home * venue,
                "exp_off_away": r.mu + r.off[ai] + r.deff[hi] - r.home * venue,
                "qb_adj_home": qh, "qb_adj_away": qa,
                "qb_home_info": qh_info, "qb_away_info": qa_info,
                "rest_adv": rest_adv,
                "indoor": float(bool(prep.indoor.get(x["stadium_id"], False))),
                "home_net": r.off[hi] - r.deff[hi], "away_net": r.off[ai] - r.deff[ai],
                "ratings_rows": r.games_used,
            })
    proj = pd.DataFrame(rows)
    if proj.empty:
        return proj
    cols = ["game_id", "season", "game_type", "week", "game_date", "start_time", "home_team", "away_team", "neutral",
            "status", "home_score", "away_score", "home_rest", "away_rest", "home_qb_name", "away_qb_name"]
    out = g[cols].merge(proj, on="game_id", how="inner")
    out["actual_margin"] = out["home_score"] - out["away_score"]
    out["actual_total"] = out["home_score"] + out["away_score"]
    return out.sort_values(["start_time", "game_id"]).reset_index(drop=True)
