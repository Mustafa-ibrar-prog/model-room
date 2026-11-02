"""Kalshi adapter (public market data; reading needs no key).

  Base URL   https://api.elections.kalshi.com/trade-api/v2
  Events     GET /events?series_ticker=<series>&status=open&with_nested_markets=true (cursor-paged)
  Book       GET /markets/{ticker}/orderbook

Structure (checked 2026-11-02): one series per stat (KXNFLRECYDS = receiving yards, ...), one event per
game (KXNFLRECYDS-26NOV02CHISEA, sub_title "CHI vs SEA (Nov 2)"), one market per player-threshold with
floor_strike and strike_type "greater" (49.5 → 50+), yes/no bid and ask in dollars with sizes, and the
player's Sportradar ID in custom_strike.football_player.

Differences from Polymarket US that matter for comparison:
  - Fantasy points use Sleeper full-PPR (interception −1), not ESPN PPR (−2), and a player who doesn't play
    scores 0 (Polymarket settles at the last fair price). These are different contracts.
  - "Protected" series (…PROT) have their own settlement terms; they are skipped.
  - Fees: taker fee ≈ 0.07 × contracts × p × (1−p), rounded up to the cent per order (general schedule;
    some series differ). Treated as 0.07 per contract here, unrounded.

Rate limit (Basic tier): 200 read tokens/s at 10 tokens per request ≈ 20 requests/s. This client
stays at 4 requests/s.

Terms: the Kalshi Developer Agreement limits use to facilitating your own trading and needs written
authorization to store or share data (§3, §3.1). See modelroom.markets.config.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import teams as T
from .http import JsonClient, ProviderError
from .schema import PropQuote, price, to_float

BASE = "https://api.elections.kalshi.com/trade-api/v2"
PROVIDER = "kalshi"
MIN_INTERVAL_S = 0.25
FEE_RATE = 0.07

SERIES = {
    "nfl": {
        "KXNFLPASSYDS": "passing_yards", "KXNFLPASSATT": "passing_attempts", "KXNFLPASSCOMP": "passing_completions",
        "KXNFLPASSTDS": "passing_tds", "KXNFLPASSINT": "interceptions", "KXNFLRSHYDS": "rushing_yards",
        "KXNFLRSHATT": "rushing_attempts", "KXNFLRECYDS": "receiving_yards", "KXNFLREC": "receptions",
        "KXNFLRRYDS": "rush_rec_yards", "KXNFLTD": "anytime_td", "KXNFLLONGREC": "longest_reception",
        "KXNFLFFPTS": "fantasy_points",
    },
    "nba": {
        "KXNBAPTS": "points", "KXNBAREB": "rebounds", "KXNBAAST": "assists", "KXNBAPRA": "pra",
        "KXNBA3PT": "threes", "KXNBASTL": "steals", "KXNBABLK": "blocks",
    },
}
VARIANTS = {"KXNFLFFPTS": "sleeper_ppr"}
VOID_RULES = {"KXNFLFFPTS": "did not play: scores 0"}
DEFAULT_VOID = "active but no snap: settles at fair price before game start"
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
EVENT_RE = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")


def client(cache_dir: Path | None, opener=None) -> JsonClient:
    return JsonClient(BASE, name=PROVIDER, min_interval_s=MIN_INTERVAL_S, cache_dir=cache_dir, cache_ttl_s=60.0, opener=opener)


def parse_event_ticker(ticker: str, sub_title: str | None, league: str = "nfl") -> tuple[str | None, str | None, str | None]:
    """→ (game_date, away, home). sub_title 'CHI vs SEA (Nov 2)' gives the order and codes."""
    m = EVENT_RE.match(ticker or "")
    gd = None
    if m:
        try:
            gd = datetime(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))).date().isoformat()
        except (KeyError, ValueError):
            gd = None
    away = home = None
    if sub_title and " vs " in sub_title:
        a, rest = sub_title.split(" vs ", 1)
        h = rest.split(" (")[0]
        away, home = T.kalshi_code(league, a.strip()), T.kalshi_code(league, h.strip())
    return gd, away, home


def _team_from_ticker(market_ticker: str, event_ticker: str, raw_codes: list[str], league: str) -> str | None:
    rest = market_ticker[len(event_ticker) + 1:] if market_ticker.startswith(event_ticker + "-") else ""
    for code in sorted(raw_codes, key=len, reverse=True):
        if rest.startswith(code):
            return T.kalshi_code(league, code)
    return None


def parse_events(series: str, payload: dict, league: str) -> list[PropQuote]:
    key = SERIES[league].get(series)
    if key is None:
        return []
    out = []
    for ev in payload.get("events") or []:
        gd, away, home = parse_event_ticker(ev.get("event_ticker", ""), ev.get("sub_title"), league)
        raw = []
        if ev.get("sub_title") and " vs " in ev["sub_title"]:
            a, rest = ev["sub_title"].split(" vs ", 1)
            raw = [a.strip(), rest.split(" (")[0].strip()]
        for m in ev.get("markets") or []:
            strike = to_float(m.get("floor_strike"))
            st = m.get("strike_type")
            if strike is None or st not in ("greater", "greater_or_equal"):
                continue
            sub = m.get("yes_sub_title") or m.get("title") or ""
            name = sub.split(":")[0].strip() if ":" in sub else None
            if not name:
                continue
            cs = m.get("custom_strike") or {}
            bid, ask = price(m.get("yes_bid_dollars")), price(m.get("yes_ask_dollars"))
            out.append(PropQuote(
                provider=PROVIDER, league=league, market=key, op=">" if st == "greater" else ">=", threshold=strike,
                player_name=name, team=_team_from_ticker(m.get("ticker", ""), ev.get("event_ticker", ""), raw, league),
                game_date=gd, home_team=home, away_team=away, start_time=None,
                provider_event_id=ev.get("event_ticker"), provider_market_id=m.get("ticker"),
                sportradar_player_id=cs.get("football_player") or cs.get("basketball_player"),
                yes_bid=bid, yes_ask=ask, no_bid=price(m.get("no_bid_dollars")), no_ask=price(m.get("no_ask_dollars")),
                last_price=price(m.get("last_price_dollars")), yes_bid_size=to_float(m.get("yes_bid_size_fp")),
                yes_ask_size=to_float(m.get("yes_ask_size_fp")), volume=to_float(m.get("volume_fp")),
                open_interest=to_float(m.get("open_interest_fp")), fee_rate=FEE_RATE, status=m.get("status"),
                variant=VARIANTS.get(series), void_rule=VOID_RULES.get(series, DEFAULT_VOID), title=m.get("title"),
                quote_time=None,
            ))
    return out


def fetch(league: str, games: pd.DataFrame | None, cache_dir: Path | None, *, opener=None, log=print) -> tuple[list[PropQuote], dict]:
    c = client(cache_dir, opener)
    quotes: list[PropQuote] = []
    errors = []
    for series in SERIES[league]:
        cursor = None
        for _page in range(20):
            try:
                d = c.get("/events", {"series_ticker": series, "status": "open", "with_nested_markets": "true", "limit": 100, "cursor": cursor})
            except ProviderError as e:
                errors.append(str(e))
                break
            quotes += parse_events(series, d or {}, league)
            cursor = (d or {}).get("cursor")
            if not cursor:
                break
    if games is not None and len(games):
        want = {(str(r["game_date"])[:10], frozenset((r["home_team"], r["away_team"]))) for _, r in games.iterrows()}
        quotes = [q for q in quotes if (q.game_date, frozenset((q.home_team, q.away_team))) in want]
    return quotes, {"provider": PROVIDER, "requests": c.calls, "cache_hits": c.cache_hits, "quotes": len(quotes), "errors": errors}
