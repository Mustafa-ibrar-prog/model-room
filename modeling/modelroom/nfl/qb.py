"""Quarterback values and the starter adjustment (see docs/models/nfl.md).

The team's rating is built from weighted games (recency in team games x season
carry). The QB adjustment compares the projected starter with the QB mix
behind those same weighted games, so a backup who started recent games is
still measured against the starter the rating mostly reflects.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import WINDOW_SEASONS

LN2 = np.log(2.0)
SHARE_GAMES = 8


def replacement_level(qbd: pd.DataFrame, seasons: list[int]) -> float:
    """EPA per dropback of QBs other than each team-season's primary passer (training seasons only)."""
    d = qbd[qbd["season"].isin(seasons)]
    tot = d.groupby(["season", "team", "qb_id"])[["dropbacks", "wepa"]].sum().reset_index()
    primary = tot.loc[tot.groupby(["season", "team"])["dropbacks"].idxmax()]
    others = tot.drop(primary.index)
    return float(others["wepa"].sum() / others["dropbacks"].sum())


class QBModel:
    def __init__(self, qbd: pd.DataFrame, tg: pd.DataFrame, shrink: float, replacement: float, carry: float, half_life_games: float):
        self.k, self.repl, self.carry, self.h = shrink, replacement, carry, half_life_games
        t = tg[["game_id", "team", "game_date", "season", "pass_w", "wplays"]].copy()
        t["date"] = pd.to_datetime(t["game_date"]).to_numpy().astype("datetime64[D]")
        t = t.sort_values(["team", "date", "game_id"])
        t["seq"] = t.groupby("team").cumcount()
        self.tg = t
        d = qbd.merge(t[["game_id", "team", "seq", "date"]], on=["game_id", "team"], how="inner")
        self.d = d

    def values(self, cutoff: np.datetime64, season_now: int) -> pd.Series:
        """Shrunk EPA per dropback for every QB, from dropbacks before cutoff."""
        d = self.d[(self.d["date"] < cutoff) & (self.d["season"] >= season_now - WINDOW_SEASONS)]
        f = self.carry ** (season_now - d["season"])
        agg = pd.DataFrame({"qb_id": d["qb_id"], "w": d["dropbacks"] * f, "e": d["wepa"] * f}).groupby("qb_id").sum()
        return (agg["e"] + self.k * self.repl) / (agg["w"] + self.k)

    def adjustment(self, team: str, starter: str | None, cutoff: np.datetime64, season_now: int, values: pd.Series) -> tuple[float | None, dict]:
        """dropback_share × (value(starter) − rating-weighted value of the team's QB mix). None if no starter listed."""
        games = self.tg[(self.tg["team"] == team) & (self.tg["date"] < cutoff) & (self.tg["season"] >= season_now - WINDOW_SEASONS)]
        if games.empty or starter is None or (isinstance(starter, float) and np.isnan(starter)):
            return None, {}
        recent = games.tail(SHARE_GAMES)
        share = float(recent["pass_w"].sum() / recent["wplays"].sum())
        n_before = len(self.tg[(self.tg["team"] == team) & (self.tg["date"] < cutoff)])
        mix = self.d[(self.d["team"] == team) & self.d["game_id"].isin(games["game_id"])]
        if mix.empty:
            return None, {}
        w = mix["dropbacks"] * np.exp(-LN2 * (n_before - mix["seq"]) / self.h) * self.carry ** (season_now - mix["season"])
        mix_v = mix["qb_id"].map(values).fillna(self.repl)
        team_qb = float(np.average(mix_v, weights=w))
        starter_v = float(values.get(starter, self.repl))
        return share * (starter_v - team_qb), {"starter_value": round(starter_v, 4), "team_mix_value": round(team_qb, 4), "dropback_share": round(share, 3)}
