"""Turn ratings into game projections. Deterministic; no randomness anywhere."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modelroom.common.metrics import normal_cdf

from .config import FittedAdjustments
from .ratings import Ratings

REST_ADV_CAP = 3


def rating_projection(r: Ratings, games: pd.DataFrame) -> pd.DataFrame:
    """Score projection from ratings alone (before rest and injury adjustments)."""
    idx = {t: i for i, t in enumerate(r.team_ids)}
    hi = games["home_id"].map(idx)
    ai = games["away_id"].map(idx)
    if hi.isna().any() or ai.isna().any():
        missing = games.loc[hi.isna() | ai.isna(), "game_id"].tolist()
        raise ValueError(f"Teams without ratings in games {missing}")
    hi, ai = hi.to_numpy(int), ai.to_numpy(int)
    venue = np.where(games["neutral"].to_numpy(), 0.0, 1.0)
    pace = r.mu_pace + r.pace[hi] + r.pace[ai]
    eff_h = r.mu + r.off[hi] + r.deff[ai] + r.home * venue
    eff_a = r.mu + r.off[ai] + r.deff[hi] - r.home * venue
    return pd.DataFrame(
        {
            "game_id": games["game_id"].to_numpy(),
            "proj_pace": pace,
            "proj_home_eff": eff_h,
            "proj_away_eff": eff_a,
            "margin_raw": (eff_h - eff_a) * pace / 100,
            "total_raw": (eff_h + eff_a) * pace / 100,
            "home_net": r.off[hi] - r.deff[hi],
            "away_net": r.off[ai] - r.deff[ai],
            "rating_games_used": r.games_used,
        }
    )


def situational(rest: pd.DataFrame, adj: FittedAdjustments) -> pd.DataFrame:
    """Rest and back-to-back margin adjustment (points, home perspective)."""
    b2b = rest["away_b2b"].astype(float) - rest["home_b2b"].astype(float)
    rest_adv = rest["home_rest"].clip(upper=REST_ADV_CAP) - rest["away_rest"].clip(upper=REST_ADV_CAP)
    return pd.DataFrame(
        {"game_id": rest["game_id"], "rest_adj": adj.b2b_points * b2b + adj.rest_points * rest_adv}
    )


def finalize(df: pd.DataFrame, adj: FittedAdjustments) -> pd.DataFrame:
    """Combine raw projection + adjustments into scores, spread, total and win probability.

    Expects columns margin_raw, total_raw, rest_adj and injury_adj (NaN = no data,
    treated as no adjustment but reported as missing).
    """
    out = df.copy()
    inj = out["injury_adj"].fillna(0.0) if "injury_adj" in out else 0.0
    out["proj_margin"] = out["margin_raw"] + out["rest_adj"] + inj
    out["proj_total"] = out["total_raw"] + adj.total_points
    out["proj_home_score"] = (out["proj_total"] + out["proj_margin"]) / 2
    out["proj_away_score"] = (out["proj_total"] - out["proj_margin"]) / 2
    out["home_win_prob"] = normal_cdf(out["proj_margin"].to_numpy() / adj.margin_sigma)
    out["model_spread"] = -out["proj_margin"]
    out["model_total"] = out["proj_total"]
    return out


def with_market(df: pd.DataFrame) -> pd.DataFrame:
    """Edges vs market. Missing market lines stay missing (NaN), never 0."""
    out = df.copy()
    for col in ("market_spread", "market_total"):
        if col not in out:
            out[col] = np.nan
    out["spread_edge"] = out["market_spread"] - out["model_spread"]
    out["total_edge"] = out["model_total"] - out["market_total"]
    return out
