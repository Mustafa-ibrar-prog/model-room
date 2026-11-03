"""Polymarket US adapter (public market data, no key).

  Base URL   https://gateway.polymarket.us  (public, read-only)
  Events     GET /v1/events/slug/{league}-{away}-{home}-{YYYY-MM-DD}  → event with every market
  Book       GET /v1/markets/{slug}/book  (optional depth; one request per market)

Structure (checked 2026-11-02): each player prop is a yes/no contract "Player N+ stat", with
sportsMarketType (e.g. football_player_receiving_yards), line (N), metadata.playerName / teamId,
bestBidQuote / bestAskQuote for the Yes side, and feeCoefficient. If a player doesn't take a snap the
contract settles at its last fair price (it is not refunded).

Rate limits are not published. Responses are cached at the edge for 30 s; a developer report shows
throttling after about five quick requests. This client waits 2 s between requests and honours
Retry-After.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import teams as T
from .http import JsonClient, ProviderError
from .schema import PropQuote, price, to_float

BASE = "https://gateway.polymarket.us"
PROVIDER = "polymarket_us"
MIN_INTERVAL_S = 2.0

MARKET_TYPES = {
    "football_player_passing_yards": "passing_yards",
    "football_player_passing_attempts": "passing_attempts",
    "football_player_passing_completions": "passing_completions",
    "football_player_passing_touchdowns": "passing_tds",
    "football_player_interceptions_thrown": "interceptions",
    "football_player_rushing_yards": "rushing_yards",
    "football_player_rushing_attempts": "rushing_attempts",
    "football_player_receiving_yards": "receiving_yards",
    "football_player_receptions": "receptions",
    "football_player_scrimmage_yards": "rush_rec_yards",
    "football_player_touchdowns": "anytime_td",          # excludes passing TDs, per the contract text
    "football_player_longest_reception": "longest_reception",
    "football_player_fantasy_points_ppr": "fantasy_points",
    "basketball_player_points": "points",
    "basketball_player_rebounds": "rebounds",
    "basketball_player_assists": "assists",
    "basketball_player_points_rebounds_assists": "pra",
    "basketball_player_threes": "threes",
    "basketball_player_steals": "steals",
    "basketball_player_blocks": "blocks",
}
VARIANTS = {"football_player_fantasy_points_ppr": "espn_ppr"}
VOID_RULE = "no snap: settles at last fair price"


def client(cache_dir: Path | None, opener=None) -> JsonClient:
    return JsonClient(BASE, name=PROVIDER, min_interval_s=MIN_INTERVAL_S, cache_dir=cache_dir, cache_ttl_s=60.0, opener=opener)


def candidate_slugs(league: str, away: str, home: str, game_date: str) -> list[str]:
    out = []
    for a in T.slug_codes(league, away):
        for h in T.slug_codes(league, home):
            out += [f"{league}-{a}-{h}-{game_date}", f"{league}-{h}-{a}-{game_date}"]
    return list(dict.fromkeys(out))


def fetch_event(c: JsonClient, league: str, away: str, home: str, game_date: str) -> dict | None:
    for slug in candidate_slugs(league, away, home, game_date):
        d = c.get(f"/v1/events/slug/{slug}", allow_404=True)
        if d:
            return d.get("event", d)
    return None


def parse_event(ev: dict, league: str, captured_at: str | None = None) -> list[PropQuote]:
    def _team_code(name):
        return T.code_from_name(league, name)

    teams = {t.get("id"): t for t in ev.get("teams") or []}
    out = []
    slug = ev.get("slug") or ""
    game_date = slug[-10:] if len(slug) >= 10 else None
    home = away = None
    for t in teams.values():
        code = _team_code(t.get("name"))
        if t.get("ordering") == "home":
            home = code
        elif t.get("ordering") == "away":
            away = code
    if (home is None or away is None) and len(teams) == 2:
        # No ordering given: the slug lists away then home ("nfl-chi-sea-…"). Matching re-checks against the schedule.
        parts = slug.split("-")
        ts = sorted(teams.values(), key=lambda t: parts.index((t.get("abbreviation") or "").lower())
                    if (t.get("abbreviation") or "").lower() in parts else 99)
        away, home = _team_code(ts[0].get("name")), _team_code(ts[1].get("name"))
    for m in ev.get("markets") or []:
        kind = m.get("sportsMarketType")
        key = MARKET_TYPES.get(kind)
        if key is None:
            continue
        md = m.get("metadata") or {}
        line = to_float(m.get("line"))
        name = md.get("playerName")
        if line is None or not name:
            continue
        team_obj = teams.get(md.get("teamId"))
        if team_obj is None:
            sides = m.get("marketSides") or []
            team_obj = (sides[0].get("team") if sides else None) or {}
        bid = price((m.get("bestBidQuote") or {}).get("value"))
        ask = price((m.get("bestAskQuote") or {}).get("value"))
        q = PropQuote(
            provider=PROVIDER, league=league, market=key, op=">=", threshold=line, player_name=name,
            team=_team_code(team_obj.get("name")), game_date=game_date, home_team=home, away_team=away,
            start_time=ev.get("startTime"), provider_event_id=slug, provider_market_id=m.get("slug"),
            provider_player_id=str(md.get("playerId")) if md.get("playerId") is not None else None,
            yes_bid=bid, yes_ask=ask, no_bid=(1 - ask) if ask is not None else None, no_ask=(1 - bid) if bid is not None else None,
            last_price=price(m.get("lastTradePrice")), fee_rate=to_float(m.get("feeCoefficient")),
            status=(m.get("status") or "").replace("MARKET_STATUS_", "").lower() or None,
            variant=VARIANTS.get(kind), void_rule=VOID_RULE, title=m.get("titleShort") or m.get("question"),
            quote_time=m.get("updatedAt"), volume=to_float(m.get("volumeNum")),
        )
        if captured_at:
            q.captured_at = captured_at
        if not m.get("active", True) or m.get("closed"):
            q.status = "closed"
        out.append(q)
    from . import games as G

    game_qs = G.parse_polymarket(ev, league, home, away, game_date)
    if captured_at:
        for q in game_qs:
            q.captured_at = captured_at
    return out + game_qs


def parse_book(d: dict) -> dict:
    """GET /v1/markets/{slug}/book → best bid / ask and the contracts available at exactly those prices.

    Shape (checked 2026-11-02): {"marketData": {"bids": [{"px": {"value": "0.70"}, "qty": "25"}], "offers": [...],
    "transactTime": ...}}."""
    md = (d or {}).get("marketData") or {}

    def levels(side):
        out = []
        for lv in md.get(side) or []:
            px = lv.get("px")
            px = to_float(px.get("value") if isinstance(px, dict) else px)
            qty = to_float(lv.get("qty"))
            if px is not None and qty is not None and 0 < px < 1 and qty > 0:
                out.append((px, qty))
        return out

    bids, offers = levels("bids"), levels("offers")
    bb = max((p for p, _ in bids), default=None)
    ba = min((p for p, _ in offers), default=None)
    return {"yes_bid": bb, "yes_ask": ba,
            "yes_bid_size": sum(q for p, q in bids if p == bb) if bb is not None else None,
            "yes_ask_size": sum(q for p, q in offers if p == ba) if ba is not None else None,
            "transact_time": md.get("transactTime")}


def book(c: JsonClient, market_slug: str) -> dict:
    return parse_book(c.get(f"/v1/markets/{market_slug}/book"))


def fetch(league: str, games: pd.DataFrame, cache_dir: Path | None, *, opener=None, log=print) -> tuple[list[PropQuote], dict]:
    """games: rows with game_date (YYYY-MM-DD, ET), home_team, away_team (nflverse codes)."""
    c = client(cache_dir, opener)
    quotes: list[PropQuote] = []
    found, missing, errors = 0, [], []
    for _, g in games.iterrows():
        gd = str(g["game_date"])[:10]
        try:
            ev = fetch_event(c, league, g["away_team"], g["home_team"], gd)
        except ProviderError as e:
            errors.append(str(e))
            continue
        if ev is None:
            missing.append(f"{g['away_team']}@{g['home_team']} {gd}")
            continue
        found += 1
        quotes += parse_event(ev, league)
    stats = {"provider": PROVIDER, "events_found": found, "events_missing": missing, "errors": errors,
             "requests": c.calls, "cache_hits": c.cache_hits, "quotes": len(quotes), "fetched_on": date.today().isoformat()}
    return quotes, stats
