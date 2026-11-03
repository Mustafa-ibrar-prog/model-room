"""Model probability vs exchange prices, after costs. Edges only where they are comparable.

For a contract "player clears threshold" with model probability p:
  buy Yes at ask a:  cost a + fee(a),        expected value per $1 contract  EV = p − a − fee(a)
  buy No  at ask b:  cost b + fee(b),        EV = (1 − p) − b − fee(b)
  fee(x) = θ·x·(1 − x) per contract (Kalshi and Polymarket US both publish a coefficient θ).
The market's implied probability is the mid (bid + ask) / 2. Its difference from p is shown, but an edge
is only reported from executable prices (the ask), after fees.

A quote is not used for an edge when it is:
  stale        captured more than MAX_AGE_MIN minutes before the comparison (or the game has started)
  thin         no bid or no ask, a spread wider than MAX_SPREAD, or (where sizes are published) fewer than
               MIN_SIZE contracts at the best ask
  incomplete   closed / suspended, or the player isn't matched
  different    the contract pays on something the model doesn't price (e.g. Sleeper vs ESPN fantasy
               scoring, or "did not play = 0" when the model assumes the player plays)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .schema import PropQuote

MAX_AGE_MIN = 20.0
MAX_SPREAD = 0.06
MIN_SIZE = 50.0
MIN_EV = 0.02           # smallest after-fee edge worth showing ("lean"), per $1 contract
STRONG_EV = 0.04        # a "strong" edge also needs every reliability gate in grade()
MAX_MARKET_ECE = 0.03   # the market type's test-season calibration error must be at most this
MODEL_VARIANTS = {"fantasy_points": {"espn_ppr", "sleeper_ppr"}}  # the model simulates both scorings


@dataclass
class QuoteView:
    provider: str
    yes_bid: float | None
    yes_ask: float | None
    bid_size: float | None
    no_ask: float | None
    mid: float | None
    spread: float | None
    ask_size: float | None
    fee_yes: float | None
    fee_no: float | None
    ev_yes: float | None
    ev_no: float | None
    captured_at: str
    usable: bool
    flags: list[str] = field(default_factory=list)


def fee(theta: float | None, x: float | None) -> float:
    if not theta or x is None:
        return 0.0
    return theta * x * (1 - x)


def age_minutes(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 60


def quote_flags(q: PropQuote, now: datetime, *, max_age_min: float = MAX_AGE_MIN, model_assumes_plays: bool = True) -> list[str]:
    f = []
    a = age_minutes(q.captured_at, now)
    if a is None or a > max_age_min:
        f.append("stale")
    if q.start_time and (age_minutes(q.start_time, now) or -1) > 0:
        f.append("game started")
    if q.status and q.status.lower() not in ("open", "active", "manual"):
        f.append(f"status {q.status}")
    if q.yes_bid is None or q.yes_ask is None:
        if not q.provider.startswith("manual:"):
            f.append("one-sided")
    elif q.yes_bid > q.yes_ask + 1e-9:
        f.append("crossed book")   # bid above ask in the listing: a stale or inconsistent snapshot, never priced
    elif q.yes_ask - q.yes_bid > MAX_SPREAD + 1e-9:
        f.append("wide spread")
    if q.yes_ask_size is not None and q.yes_ask_size < MIN_SIZE:
        f.append("thin at ask")
    if q.player_id is None:
        f.append("player not matched")
    if q.void_rule and "scores 0" in q.void_rule and model_assumes_plays:
        f.append("pays 0 if inactive; model assumes he plays")
    return f


def view(q: PropQuote, p: float | None, now: datetime, **kw) -> QuoteView:
    flags = quote_flags(q, now, **kw)
    fy = fee(q.fee_rate, q.yes_ask)
    fn = fee(q.fee_rate, q.no_ask)
    ev_y = (p - q.yes_ask - fy) if p is not None and q.yes_ask is not None else None
    ev_n = ((1 - p) - q.no_ask - fn) if p is not None and q.no_ask is not None else None
    if p is None:
        flags.append("no model probability")
    return QuoteView(q.provider, q.yes_bid, q.yes_ask, q.yes_bid_size, q.no_ask, q.mid, q.spread, q.yes_ask_size,
                     round(fy, 4) if q.yes_ask is not None else None, round(fn, 4) if q.no_ask is not None else None,
                     None if ev_y is None else round(ev_y, 4), None if ev_n is None else round(ev_n, 4),
                     q.captured_at, not flags, flags)


def best(views: list[QuoteView]) -> dict:
    """Best executable price for each side among usable quotes, and the edge there."""
    ok = [v for v in views if v.usable]
    out = {"yes": None, "no": None}
    ys = [v for v in ok if v.yes_ask is not None]
    ns = [v for v in ok if v.no_ask is not None]
    if ys:
        v = min(ys, key=lambda v: v.yes_ask + (v.fee_yes or 0))
        out["yes"] = {"provider": v.provider, "price": v.yes_ask, "fee": v.fee_yes, "ev": v.ev_yes, "size": v.ask_size}
    if ns:
        v = min(ns, key=lambda v: v.no_ask + (v.fee_no or 0))
        # Buying No at the No ask takes the Yes bid; its size is the Yes bid size.
        out["no"] = {"provider": v.provider, "price": v.no_ask, "fee": v.fee_no, "ev": v.ev_no, "size": v.bid_size}
    picks = [(side, b) for side, b in out.items() if b and b["ev"] is not None and b["ev"] >= MIN_EV]
    out["edge"] = max(picks, key=lambda x: x[1]["ev"])[0] if picks else None
    return out


def grade(best_sides: dict | None, support: str, market_reliability: dict | None) -> dict:
    """How much to trust an edge. A probability gap alone is never enough.

    strong  EV ≥ STRONG_EV after fees, AND the player's history is "ok", AND this market type was well
            calibrated and beat the baseline on the test seasons, AND the size available at that price is
            published and at least MIN_SIZE contracts
    lean    EV ≥ MIN_EV on a usable quote, but at least one gate above isn't met (the reasons say which)
    none    otherwise
    """
    if not best_sides or not best_sides.get("edge"):
        return {"grade": None, "reasons": []}
    side = best_sides["edge"]
    b = best_sides[side]
    reasons = []
    if b["ev"] < STRONG_EV:
        reasons.append(f"edge under {STRONG_EV * 100:.0f}¢")
    if support != "ok":
        reasons.append(f"{support} player history")
    r = market_reliability or {}
    if not r:
        reasons.append("no backtest for this market")
    else:
        if r.get("ece") is None or r["ece"] > MAX_MARKET_ECE:
            reasons.append("market type not well calibrated in testing")
        if r.get("baseline_log_loss") is not None and r.get("model_log_loss_same_rows") is not None and \
                r["model_log_loss_same_rows"] >= r["baseline_log_loss"]:
            reasons.append("model didn't beat the baseline for this market")
    if b.get("size") is None:
        reasons.append("size at this price not published")
    elif b["size"] < MIN_SIZE:
        reasons.append("thin at this price")
    return {"grade": "lean" if reasons else "strong", "reasons": reasons}
