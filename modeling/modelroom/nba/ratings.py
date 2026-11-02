"""Opponent-adjusted, recency-weighted team ratings with a previous-season prior.

Efficiency model (one observation per team per game):
    100·pts/poss = μ + off[team] + def[opp] + h·venue
Pace model (one observation per game):
    pace = μp + pace[home] + pace[away]

Both are solved by ridge regression toward a prior (common.linalg).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from modelroom.common.linalg import ridge_to_prior

from .config import RatingSettings

LN2 = np.log(2.0)


@dataclass
class SeasonPrior:
    """Starting point for a season, from the previous season's final ratings."""

    team_ids: list[int]
    off: np.ndarray
    deff: np.ndarray
    mu: float
    home: float
    pace: np.ndarray
    mu_pace: float


@dataclass
class Ratings:
    """Ratings as of a cutoff (games strictly before the cutoff)."""

    team_ids: list[int]
    mu: float
    off: np.ndarray
    deff: np.ndarray
    home: float
    mu_pace: float
    pace: np.ndarray
    games_used: int

    def index(self, team_id: int) -> int:
        return self.team_ids.index(team_id)

    def table(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "team_id": self.team_ids,
                "off_rating": self.mu + self.off,
                "def_rating": self.mu + self.deff,
                "net_rating": self.off - self.deff,
                "pace": self.mu_pace + 2 * self.pace,
            }
        )


class SeasonRater:
    """Holds one season's observations and solves ratings for any cutoff date."""

    def __init__(self, season_games: pd.DataFrame, poss: pd.DataFrame, team_ids: list[int], settings: RatingSettings):
        self.s = settings
        self.team_ids = list(team_ids)
        self.n = len(self.team_ids)
        idx = {t: i for i, t in enumerate(self.team_ids)}
        g = season_games.merge(poss, on="game_id", how="inner").sort_values("start_time")
        self.dates = pd.to_datetime(g["game_date"]).to_numpy()
        venue = np.where(g["neutral"].to_numpy(), 0.0, 1.0)
        hi = g["home_id"].map(idx).to_numpy()
        ai = g["away_id"].map(idx).to_numpy()
        m = len(g)
        n = self.n

        # Efficiency design: rows 0..m-1 home offense, m..2m-1 away offense.
        X = np.zeros((2 * m, 2 * n + 2))
        X[:, 0] = 1.0
        X[np.arange(m), 1 + hi] = 1.0
        X[np.arange(m), 1 + n + ai] = 1.0
        X[np.arange(m), -1] = venue
        X[m + np.arange(m), 1 + ai] = 1.0
        X[m + np.arange(m), 1 + n + hi] = 1.0
        X[m + np.arange(m), -1] = -venue
        self.X_eff = X
        self.y_eff = np.concatenate([g["home_eff"].to_numpy(), g["away_eff"].to_numpy()])
        self.eff_dates = np.concatenate([self.dates, self.dates])

        P = np.zeros((m, n + 1))
        P[:, 0] = 1.0
        P[np.arange(m), 1 + hi] += 1.0
        P[np.arange(m), 1 + ai] += 1.0
        self.X_pace = P
        self.y_pace = g["pace"].to_numpy()
        self.game_ids = g["game_id"].to_numpy()

    def _weights(self, dates: np.ndarray, cutoff: np.datetime64) -> np.ndarray:
        age = (cutoff - dates).astype("timedelta64[D]").astype(float)
        return np.exp(-LN2 * age / self.s.half_life_days)

    def solve(self, prior: SeasonPrior, cutoff: np.datetime64 | None = None) -> Ratings:
        """Ratings using games with game_date < cutoff (all games if cutoff is None)."""
        s, n = self.s, self.n
        if cutoff is None:
            cutoff = self.dates.max() + np.timedelta64(1, "D") if len(self.dates) else np.datetime64("1970-01-01")
        use_e = self.eff_dates < cutoff
        use_p = self.dates < cutoff

        beta0 = np.concatenate([[prior.mu], prior.off, prior.deff, [prior.home]])
        pen = np.concatenate([[s.mean_prior_games], np.full(n, s.prior_games), np.full(n, s.prior_games), [s.home_prior_games]])
        beta = ridge_to_prior(
            self.X_eff[use_e], self.y_eff[use_e], self._weights(self.eff_dates[use_e], cutoff), beta0, pen
        )

        pbeta0 = np.concatenate([[prior.mu_pace], prior.pace])
        ppen = np.concatenate([[s.mean_prior_games], np.full(n, s.pace_prior_games)])
        pbeta = ridge_to_prior(
            self.X_pace[use_p], self.y_pace[use_p], self._weights(self.dates[use_p], cutoff), pbeta0, ppen
        )
        return Ratings(
            team_ids=self.team_ids,
            mu=float(beta[0]),
            off=beta[1 : 1 + n],
            deff=beta[1 + n : 1 + 2 * n],
            home=float(beta[-1]),
            mu_pace=float(pbeta[0]),
            pace=pbeta[1:],
            games_used=int(use_p.sum()),
        )


def next_season_prior(final: Ratings, team_ids: list[int], s: RatingSettings) -> SeasonPrior:
    """Regress last season's final ratings toward average (centered so they sum to zero)."""
    def carry(values: np.ndarray, keep: float) -> np.ndarray:
        by_team = dict(zip(final.team_ids, values - values.mean()))
        return np.array([keep * by_team.get(t, 0.0) for t in team_ids])

    return SeasonPrior(
        team_ids=team_ids,
        off=carry(final.off, s.prior_retention),
        deff=carry(final.deff, s.prior_retention),
        mu=final.mu + float(final.off.mean() + final.deff.mean()),
        home=final.home,
        pace=carry(final.pace, s.pace_retention),
        mu_pace=final.mu_pace + 2 * float(final.pace.mean()),
    )


def burn_in_prior(team_ids: list[int], poss: pd.DataFrame) -> SeasonPrior:
    """Flat prior for the first season in the data (that season is never scored)."""
    n = len(team_ids)
    mu = float(np.concatenate([poss["home_eff"], poss["away_eff"]]).mean())
    return SeasonPrior(team_ids, np.zeros(n), np.zeros(n), mu, 0.0, np.zeros(n), float(poss["pace"].mean()))


def burn_in_settings(s: RatingSettings) -> RatingSettings:
    """Weak, non-recency fit for the burn-in season's final ratings."""
    from dataclasses import replace

    return replace(s, half_life_days=1e9, prior_games=2.0, home_prior_games=2.0, pace_prior_games=2.0)
