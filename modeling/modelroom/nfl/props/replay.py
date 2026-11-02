"""Walk-forward NFL prop projections for past games (used to price historical exchange contracts)."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from modelroom.common import board as B

from . import backtest as BT
from . import inputs as I
from .config import MARKETS, MODEL_VERSION, PropParams
from .pipeline import VARIANT_STAT, backtest_summary


@lru_cache(maxsize=1)
def _runner():
    games = I.ingest.load_games()
    seasons = set(int(s) for s in games["season"].unique() if s >= 2019)
    return BT.Runner(I.load(seasons))


def schedule() -> pd.DataFrame:
    g = _runner().inp.games
    g = g[g["status"] == "final"].copy()
    g["game_date"] = g["game_date"].astype(str)
    g["start_iso"] = g["start_time"].map(B.iso)
    return g


@lru_cache(maxsize=1)
def _roster_ids():
    r = _runner().inp.rosters
    return r.dropna(subset=["sportradar_id"]).drop_duplicates("gsis_id", keep="last").set_index("gsis_id")["sportradar_id"].to_dict()


def sportradar(player_id):
    return _roster_ids().get(player_id)


def project(games: pd.DataFrame):
    run = _runner()
    p = PropParams.load()
    out = []
    for (season, week), g in run.inp.games[run.inp.games["game_id"].isin(games["game_id"])].groupby(["season", "week"]):
        week_games = run.inp.games[(run.inp.games["season"] == season) & (run.inp.games["week"] == week)]
        cutoff = pd.Timestamp(week_games["game_date"].min())
        ctx = run.ctx(cutoff, int(season), p.settings)
        ro, inj = I.week_slices(run.inp, int(season), int(week))
        from . import model as M

        out += [x for x in M.project_games(ctx, g, ro, inj, p, seed=int(season) * 100 + int(week)) if BT.eligible(x)]

    def price(x, q):
        m = MARKETS.get(q.market)
        if m is None or x.group not in m["positions"]:
            return None
        s = VARIANT_STAT.get((q.market, q.variant), m["stat"])
        return p.calibrate(q.market, x.prob(s, float(q.threshold), q.op)), m["stat"]

    rel = (backtest_summary() or {}).get("by_market", {})
    return out, price, (lambda x, mk: x.support(mk)[0]), rel, MODEL_VERSION
