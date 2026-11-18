"""Forecast-wind adjustment for the 0.1.6 shadow (TEST only). Applied AFTER the 0.1.6a projection is simulated, to that
version's own copy; no other version is touched.

For a game with a usable pregame forecast (modelroom.nfl.weather.select) at an open-air stadium, each listed stat's simulated
outcomes are multiplied by
    factor = (a + b * min(wind, wind_max_mph)) / (a + b * wbar)
with (a, b, wbar) per stat fitted on 2021-23 against GFS MOS forecast wind (research Phase 7, out/wind7_fit_fc.json). With
wind_reduce_only the factor is capped at 1, so wind can only LOWER a projection. Whole-number stats stay whole numbers
(stochastic rounding from a per-player seeded stream); completions never exceed attempts; PPR points and rush+rec yards move
with their parts. No forecast, or not open-air: the projection is left exactly as simulated.
"""
from __future__ import annotations

import zlib

import numpy as np

QB_STATS = (("pass_yds", "passing_yards"), ("pass_cmp", "passing_completions"), ("pass_att", "passing_attempts"), ("pass_td", "passing_tds"))
REC_STATS = (("rec_yds", "receiving_yards"), ("receptions", "receptions"))
COUNTS = {"pass_cmp", "pass_att", "pass_td", "receptions"}


def factor(fit: dict, wind_mph: float, wind_max_mph: float, reduce_only: bool) -> float:
    a, b, wbar = fit["a"], fit["b"], fit["wbar"]
    f = (a + b * min(float(wind_mph), wind_max_mph)) / (a + b * wbar)
    return min(f, 1.0) if reduce_only else f


def apply(projs: list, wind: dict, s, seed: int) -> dict:
    """Adjust `projs` in place where `wind[game_id]["usable"]`. Returns {game_id: {stat: factor}} for the record."""
    fits = {k: {"a": a, "b": b, "wbar": w} for k, a, b, w in s.wind_adjust}
    used: dict = {}
    for x in projs:
        w = wind.get(x.game_id) or {}
        if not w.get("usable"):
            continue
        S = x.sims
        if x.group == "QB":
            if float(np.mean(S.get("pass_att", np.zeros(1)))) < 1:
                continue                       # a QB who isn't projected to pass is left alone (as in the research)
            stats = QB_STATS
        else:
            stats = REC_STATS
        rng = np.random.default_rng([seed, zlib.crc32(f"{x.game_id}|{x.player_id}|wind".encode())])
        old = {k: S[k].astype(float).copy() for k in ("pass_yds", "pass_td", "rec_yds", "receptions") if k in S}
        for st, mk in stats:
            if st not in S or mk not in fits:
                continue
            f = factor(fits[mk], w["wind_mph"], s.wind_max_mph, s.wind_reduce_only)
            used.setdefault(x.game_id, {})[mk] = round(f, 4)
            if f == 1.0:
                continue
            v = S[st].astype(float) * f
            if st in COUNTS:
                fl = np.floor(v)
                v = fl + (rng.random(len(v)) < (v - fl))
            S[st] = v
        if x.group == "QB" and "pass_cmp" in S and "pass_att" in S:
            S["pass_cmp"] = np.minimum(S["pass_cmp"], S["pass_att"])
        d = {k: S[k] - old[k] for k in old}
        if "rush_rec_yds" in S and "rec_yds" in d:
            S["rush_rec_yds"] = S["rush_rec_yds"] + d["rec_yds"]
        dfp = 0.04 * d.get("pass_yds", 0) + 4 * d.get("pass_td", 0) + 0.1 * d.get("rec_yds", 0) + d.get("receptions", 0)
        for k in ("fantasy_ppr", "fantasy_sleeper"):
            if k in S:
                S[k] = S[k] + dfp
    return used
