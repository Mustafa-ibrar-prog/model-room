"""Game markets (winner, spread, total) on Polymarket US and Kalshi, and the model's probability for each.

Normalized like player props, so snapshots, comparison, evaluation and settlement are shared:

  market        team   op  threshold   pays Yes when
  game_winner   T      >   0           T wins
  game_spread   T      >   x           T's margin of victory is more than x (Polymarket "T covers L" → x = −L)
  game_total    None   >   x           combined points are more than x

The model's probability comes from the published game board, never from a price:
  - winner: the engine's own home win probability;
  - spread and total: a normal approximation to the engine's projected margin / total, with the spread
    implied by its published 80% range (sd = range / 2.563). This is not separately calibrated; the
    settled record on the Performance page is how it is judged.
"""
from __future__ import annotations

import json
import math
from datetime import datetime

from modelroom.common.paths import data_root

from . import teams as T
from .schema import PropQuote, price, to_float

GAME_MARKETS = ("game_winner", "game_spread", "game_total")
Z80 = 1.2815515655446004  # 80% central range = mean ± 1.2816 sd

# Kalshi: one series per game-market type (checked 2026-11-02: KXNFLGAME/SPREAD/TOTAL, KXNBA… the same).
KALSHI_SERIES = {
    "nfl": {"KXNFLGAME": "game_winner", "KXNFLSPREAD": "game_spread", "KXNFLTOTAL": "game_total"},
    "nba": {"KXNBAGAME": "game_winner", "KXNBASPREAD": "game_spread", "KXNBATOTAL": "game_total"},
}
# Polymarket US: marketType on each market of the game's event.
PM_TYPES = {"moneyline": "game_winner", "spreads": "game_spread", "totals": "game_total"}


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ------------------------------------------------------------------ parsing
def parse_kalshi(series: str, payload: dict, league: str) -> list[PropQuote]:
    from . import kalshi as K

    key = KALSHI_SERIES[league].get(series)
    if key is None:
        return []
    out = []
    for ev in payload.get("events") or []:
        gd, away, home = K.parse_event_ticker(ev.get("event_ticker", ""), ev.get("sub_title"), league)
        raw = []
        if ev.get("sub_title") and " vs " in ev["sub_title"]:
            a, rest = ev["sub_title"].split(" vs ", 1)
            raw = [a.strip(), rest.split(" (")[0].strip()]
        for m in ev.get("markets") or []:
            team = K._team_from_ticker(m.get("ticker", ""), ev.get("event_ticker", ""), raw, league)
            if key == "game_winner":
                op, thr = ">", 0.0
                if team is None:
                    continue
            else:
                thr = to_float(m.get("floor_strike"))
                if thr is None or m.get("strike_type") not in ("greater", "greater_or_equal"):
                    continue
                op = ">" if m.get("strike_type") == "greater" else ">="
                if key == "game_spread" and team is None:
                    continue
                if key == "game_total":
                    team = None
            out.append(PropQuote(
                provider=K.PROVIDER, league=league, market=key, op=op, threshold=thr, player_name="", team=team,
                game_date=gd, home_team=home, away_team=away, provider_event_id=ev.get("event_ticker"),
                provider_market_id=m.get("ticker"),
                yes_bid=price(m.get("yes_bid_dollars")), yes_ask=price(m.get("yes_ask_dollars")),
                no_bid=price(m.get("no_bid_dollars")), no_ask=price(m.get("no_ask_dollars")),
                last_price=price(m.get("last_price_dollars")), yes_bid_size=to_float(m.get("yes_bid_size_fp")),
                yes_ask_size=to_float(m.get("yes_ask_size_fp")), volume=to_float(m.get("volume_fp")),
                fee_rate=K.FEE_RATE, status=m.get("status"), title=m.get("title"),
            ))
    return out


def parse_polymarket(ev: dict, league: str, home: str | None, away: str | None, game_date: str | None) -> list[PropQuote]:
    from . import polymarket_us as P

    out = []
    for m in ev.get("markets") or []:
        key = PM_TYPES.get(m.get("marketType"))
        if key is None:
            continue
        sides = m.get("marketSides") or []
        long = next((s for s in sides if s.get("long")), None)
        if long is None:
            continue
        team = T.code_from_name(league, (long.get("team") or {}).get("name"))
        line = to_float(m.get("line"))
        if key == "game_winner":
            if team is None:
                continue
            op, thr = ">", 0.0
        elif key == "game_spread":
            if team is None or line is None:
                continue
            op, thr = ">", -line          # "T covers L": T's margin + L > 0
        else:
            desc = (long.get("description") or "").lower()
            if line is None or not desc.startswith("over"):
                continue                  # only "Over x" contracts are normalized
            op, thr, team = ">", line, None
        bid = price((m.get("bestBidQuote") or {}).get("value"))
        ask = price((m.get("bestAskQuote") or {}).get("value"))
        out.append(PropQuote(
            provider=P.PROVIDER, league=league, market=key, op=op, threshold=thr, player_name="", team=team,
            game_date=game_date, home_team=home, away_team=away, start_time=ev.get("startTime"),
            provider_event_id=ev.get("slug"), provider_market_id=m.get("slug"),
            yes_bid=bid, yes_ask=ask, no_bid=(1 - ask) if ask is not None else None, no_ask=(1 - bid) if bid is not None else None,
            fee_rate=to_float(m.get("feeCoefficient")), status=(m.get("status") or "").replace("MARKET_STATUS_", "").lower() or None,
            title=m.get("titleShort") or m.get("question"), quote_time=m.get("updatedAt"),
        ))
    return out


# ------------------------------------------------------------------ model probability
def model_prob(q: PropQuote, g: dict) -> float | None:
    """g: one game from the published board (projection with margin = home − away, ranges)."""
    p = g.get("projection") or {}
    home = (g.get("home") or {}).get("abbr")
    if not p or home is None:
        return None
    if q.market == "game_winner":
        hp = p.get("home_win_prob")
        if hp is None:
            return None
        return hp if q.team == home else 1 - hp
    if q.market == "game_spread":
        lo, hi = (p.get("margin_range_80") or [None, None])
        if lo is None or hi is None or hi <= lo:
            return None
        sd = (hi - lo) / (2 * Z80)
        mu = p["margin"] if q.team == home else -p["margin"]
        return 1 - _phi((q.threshold - mu) / sd)
    if q.market == "game_total":
        lo, hi = (p.get("total_range_80") or [None, None])
        if lo is None or hi is None or hi <= lo:
            return None
        sd = (hi - lo) / (2 * Z80)
        return 1 - _phi((q.threshold - p["total"]) / sd)
    return None


def board(league: str) -> dict:
    f = data_root() / "published" / f"{league}.json"
    return json.loads(f.read_text()) if f.exists() else {}


def evaluate(league: str, now: datetime | None = None) -> int:
    """Append one evaluation row per pre-game game-market quote in the latest snapshots, priced by the
    latest published game board. Same log and fields as player props (player fields empty)."""
    import pandas as pd

    from . import compare as C
    from . import evaluation, matching, snapshots

    b = board(league)
    games = {g["game_id"]: g for g in b.get("upcoming") or []}
    if not games:
        return 0
    snap = snapshots.latest(league)
    if snap.empty:
        return 0
    snap = snap[snap["market"].isin(GAME_MARKETS)]
    fields = PropQuote.__dataclass_fields__
    quotes = [PropQuote(**{k: (None if isinstance(v, float) and v != v else v) for k, v in r.items() if k in fields}) for r in snap.to_dict("records")]
    sched = pd.DataFrame([{"game_id": gid, "game_date": g["game_date"], "home_team": g["home"]["abbr"], "away_team": g["away"]["abbr"]} for gid, g in games.items()])
    matching.match_games(quotes, sched)
    now = now or datetime.now().astimezone()
    rows = []
    for q in quotes:
        g = games.get(q.game_id)
        if g is None or not g.get("start_time") or pd.Timestamp(q.captured_at) >= pd.Timestamp(g["start_time"]):
            continue
        p = model_prob(q, g)
        if p is None:
            continue
        v = C.view(q, p, now, model_assumes_plays=False)
        grade = C.grade(C.best([v]), "ok", None)
        r = evaluation.row(q, p, b["model"]["version"], b["generated_at"], g["start_time"], grade, q.market)
        r.update({"kind": "game", "team": q.team, "event_id": q.provider_event_id,
                  "projection": {"margin": g["projection"]["margin"], "total": g["projection"]["total"], "home": g["home"]["abbr"], "away": g["away"]["abbr"]}})
        rows.append(r)
    return evaluation.record(league, rows)
