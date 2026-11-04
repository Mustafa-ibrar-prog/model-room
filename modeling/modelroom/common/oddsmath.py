"""Odds arithmetic shared by game and prop comparisons.

American odds, implied probability, no-vig two-way probabilities, fair odds and expected value.
Outcomes are integers (points, yards, receptions), so a line on a whole number can push: every
probability here is split into win / push / loss, and EV treats a push as the stake returned.
"""
from __future__ import annotations

import math

from .metrics import normal_cdf

Z80 = 1.2815515655446004  # an 80% central interval is mean ± Z80·sd


def implied(american: float | None) -> float | None:
    """Break-even probability of an American price (includes the book's margin)."""
    if american is None or (isinstance(american, float) and math.isnan(american)):
        return None
    a = float(american)
    if -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def devig(a: float | None, b: float | None) -> tuple[float | None, float | None]:
    """No-vig probabilities of a two-way market (multiplicative: each side's implied ÷ their sum)."""
    pa, pb = implied(a), implied(b)
    if pa is None or pb is None:
        return None, None
    s = pa + pb
    return pa / s, pb / s


def decimal(american: float) -> float:
    a = float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def fair_american(p_win: float, p_loss: float | None = None) -> float | None:
    """Price at which a bet has zero EV. With a push chance, only win vs loss matters."""
    q = p_win if p_loss is None else p_win / max(p_win + p_loss, 1e-12)
    if q <= 0 or q >= 1:
        return None
    return round(-100 * q / (1 - q)) if q >= 0.5 else round(100 * (1 - q) / q)


def ev(p_win: float, p_push: float, american: float | None) -> float | None:
    """Expected profit per $1 staked at this price (push = stake back)."""
    if american is None or implied(american) is None:
        return None
    p_loss = max(0.0, 1.0 - p_win - p_push)
    return p_win * (decimal(american) - 1) - p_loss


def sigma_from_range(rng) -> float | None:
    if not rng or len(rng) != 2 or rng[0] is None or rng[1] is None:
        return None
    s = (float(rng[1]) - float(rng[0])) / (2 * Z80)
    return s if s > 0 else None


def over_probs(mean: float, sd: float, line: float) -> dict:
    """X ~ Normal(mean, sd) rounded to integers. P(X > line), P(X = line), P(X < line)."""
    if math.isclose(line, round(line)):
        k = round(line)
        p_over = 1 - normal_cdf((k + 0.5 - mean) / sd)
        p_push = normal_cdf((k + 0.5 - mean) / sd) - normal_cdf((k - 0.5 - mean) / sd)
    else:
        k = math.floor(line) + 1
        p_over = 1 - normal_cdf((k - 0.5 - mean) / sd)
        p_push = 0.0
    return {"over": float(p_over), "push": float(p_push), "under": float(max(0.0, 1 - p_over - p_push))}


def cover_probs(margin: float, sd: float, home_line: float) -> dict:
    """Home spread `home_line` (negative = home favored). Home covers when margin + line > 0."""
    p = over_probs(margin, sd, -home_line)
    return {"home": p["over"], "push": p["push"], "away": p["under"]}


def ladder_probs(grid: dict, line: float) -> dict | None:
    """Prop distribution as a ladder {k: P(X >= k)} (integer ks). Over/push/under at `line`.
    Returns None when the ladder doesn't hold the thresholds needed (no extrapolation)."""
    g = {float(k): float(v) for k, v in grid.items() if k not in ("mean", "sd", "support")}
    if math.isclose(line, round(line)):
        k = float(round(line))
        if k not in g or (k + 1) not in g:
            return None
        return {"over": g[k + 1], "push": g[k] - g[k + 1], "under": 1 - g[k]}
    k = float(math.floor(line) + 1)
    if k not in g:
        return None
    return {"over": g[k], "push": 0.0, "under": 1 - g[k]}


def side_view(p_win: float, p_push: float, price: float | None) -> dict:
    """Everything the site shows for one side of one market."""
    p_loss = max(0.0, 1 - p_win - p_push)
    return {"model_prob": round(p_win, 4), "push_prob": round(p_push, 4), "fair_odds": fair_american(p_win, p_loss),
            "market_price": price, "market_implied": None if implied(price) is None else round(implied(price), 4),
            "ev_per_dollar": None if ev(p_win, p_push, price) is None else round(ev(p_win, p_push, price), 4)}
