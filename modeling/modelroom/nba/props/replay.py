"""Walk-forward NBA prop projections for past games (used to price historical exchange contracts)."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from modelroom.common import board as B

from . import backtest as BT
from . import inputs as I
from . import model as M
from .config import MARKETS, MODEL_VERSION, PropParams
from .pipeline import backtest_summary


@lru_cache(maxsize=1)
def _runner():
    return BT.Runner(I.load())


def schedule() -> pd.DataFrame:
    g = _runner().inp.games
    g = g[g["status"] == "final"].rename(columns={"home_abbr": "home_team", "away_abbr": "away_team"}).copy()
    g["start_iso"] = g["start_time"].map(B.iso)
    g["home_abbr"], g["away_abbr"] = g["home_team"], g["away_team"]
    return g


def sportradar(player_id):
    return None  # hoopR has ESPN ids only; NBA contracts are matched by name + team


def project(games: pd.DataFrame):
    run = _runner()
    p = PropParams.load()
    out = []
    for day, g in games.groupby("game_date"):
        season = int(g["season"].iloc[0])
        ctx = run.ctx(str(day), season, p.settings)
        out += [x for x in M.project_games(ctx, g, p, seed=int(str(day).replace("-", ""))) if BT.eligible(x)]

    def price(x, q):
        m = MARKETS.get(q.market)
        if m is None:
            return None
        return p.calibrate(q.market, x.prob(m["stat"], float(q.threshold), q.op)), m["stat"]

    rel = (backtest_summary() or {}).get("by_market", {})
    return out, price, (lambda x, mk: x.support()[0]), rel, MODEL_VERSION
