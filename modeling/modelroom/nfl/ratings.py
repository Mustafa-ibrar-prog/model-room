"""Opponent-adjusted EPA ratings for NFL teams (see docs/models/nfl.md).

    off_epa(team vs opp) = μ + off[team] + def[opp] + h·venue

Ridge regression toward 0 with play-count × recency × season-carry weights.
Recency counts each team's own games, so byes don't age the data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from modelroom.common.linalg import ridge_to_prior

from .config import PLAYS_PER_GAME, WINDOW_SEASONS, RatingSettings

LN2 = np.log(2.0)


@dataclass
class Ratings:
    teams: list[str]
    mu: float
    off: np.ndarray
    deff: np.ndarray
    home: float
    games_used: int

    def idx(self, team: str) -> int:
        return self.teams.index(team)


class EPARater:
    """Holds every team-game observation; solves ratings for any cutoff date."""

    def __init__(self, tg: pd.DataFrame, settings: RatingSettings, *, value: str = "epa", weight: str = "wplays"):
        self.s = settings
        t = tg.dropna(subset=[value]).sort_values(["start_time", "game_id"]).reset_index(drop=True)
        t = t[t[weight] > 0]
        self.teams = sorted(set(t["team"]) | set(t["opp"]))
        ix = {k: i for i, k in enumerate(self.teams)}
        self.n = len(self.teams)
        self.date = pd.to_datetime(t["game_date"]).to_numpy().astype("datetime64[D]")
        self.season = t["season"].to_numpy()
        self.ti = t["team"].map(ix).to_numpy()
        self.oi = t["opp"].map(ix).to_numpy()
        self.venue = np.where(t["neutral"].to_numpy(), 0.0, np.where(t["is_home"].to_numpy(), 1.0, -1.0))
        self.y = t[value].to_numpy(float)
        self.w = t[weight].to_numpy(float)

        # Each team's game sequence (by date), for "games ago" recency.
        per_team = pd.concat([
            t[["game_id", "game_date", "team"]].rename(columns={"team": "k"}),
            t[["game_id", "game_date", "opp"]].rename(columns={"opp": "k"}),
        ]).drop_duplicates(["game_id", "k"]).sort_values(["k", "game_date", "game_id"])
        per_team["seq"] = per_team.groupby("k").cumcount()
        seq = per_team.set_index(["game_id", "k"])["seq"]
        self.seq_t = seq.reindex(list(zip(t["game_id"], t["team"]))).to_numpy()
        self.seq_o = seq.reindex(list(zip(t["game_id"], t["opp"]))).to_numpy()
        self.team_dates = {
            ix[k]: pd.to_datetime(g["game_date"]).to_numpy().astype("datetime64[D]")
            for k, g in per_team.groupby("k")
        }

        X = np.zeros((len(t), 2 * self.n + 2))
        X[:, 0] = 1.0
        X[np.arange(len(t)), 1 + self.ti] = 1.0
        X[np.arange(len(t)), 1 + self.n + self.oi] = 1.0
        X[:, -1] = self.venue
        self.X = X

    def _count_before(self, team_i: np.ndarray, cutoff: np.datetime64) -> np.ndarray:
        cache = {k: np.searchsorted(v, cutoff, side="left") for k, v in self.team_dates.items()}
        return np.array([cache[k] for k in team_i])

    def solve(self, cutoff: np.datetime64, season_now: int) -> Ratings:
        s = self.s
        m = (self.date < cutoff) & (self.season >= season_now - WINDOW_SEASONS)
        if not m.any():
            z = np.zeros(self.n)
            return Ratings(self.teams, 0.0, z, z.copy(), 0.0, 0)
        ago_t = self._count_before(self.ti[m], cutoff) - self.seq_t[m]
        ago_o = self._count_before(self.oi[m], cutoff) - self.seq_o[m]
        ago = (ago_t + ago_o) / 2.0
        w = self.w[m] * np.exp(-LN2 * ago / s.half_life_games) * s.season_carry ** (season_now - self.season[m])
        n = self.n
        pen = np.concatenate([[1e-6], np.full(2 * n, s.prior_games * PLAYS_PER_GAME), [s.home_prior_games * PLAYS_PER_GAME]])
        beta = ridge_to_prior(self.X[m], self.y[m], w, np.zeros(2 * n + 2), pen)
        return Ratings(self.teams, float(beta[0]), beta[1 : 1 + n], beta[1 + n : 1 + 2 * n], float(beta[-1]), int(m.sum()))
