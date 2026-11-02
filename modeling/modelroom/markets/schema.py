"""The normalized shape every market-data adapter produces.

Exchanges list player props as yes/no contracts on a threshold ("AJ Barner 10+ receiving yards").
A quote here is one such contract. Prices are dollars per $1 contract (0-1), which is also the
exchange's implied probability before fees. A sportsbook over/under entered by hand is stored the
same way (op ">" and the line), with the over price converted from American odds.

Nothing here fills a missing price: a side with no bid or ask stays None.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# Normalized prop market keys (same keys as modelroom.nfl.props.config.MARKETS).
NFL_MARKETS = (
    "passing_yards", "passing_attempts", "passing_completions", "passing_tds", "interceptions",
    "rushing_yards", "rushing_attempts", "receiving_yards", "receptions", "rush_rec_yards",
    "anytime_td", "longest_reception", "fantasy_points",
)
NBA_MARKETS = ("points", "rebounds", "assists", "pra", "threes", "steals", "blocks")


@dataclass
class PropQuote:
    provider: str                 # polymarket_us | kalshi | manual:<source>
    league: str                   # nfl | nba
    market: str                   # normalized key, e.g. receiving_yards
    op: str                       # ">=" (k or more) or ">" (more than x)
    threshold: float
    player_name: str
    team: str | None              # Model Room team code (nflverse), when the provider gives one
    game_date: str | None         # local (ET) date of the game, YYYY-MM-DD
    home_team: str | None = None
    away_team: str | None = None
    start_time: str | None = None
    provider_event_id: str | None = None
    provider_market_id: str | None = None
    provider_player_id: str | None = None
    sportradar_player_id: str | None = None
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    last_price: float | None = None
    yes_bid_size: float | None = None   # contracts at the best bid / ask, when published
    yes_ask_size: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    fee_rate: float | None = None       # taker fee coefficient θ: fee per contract ≈ θ·p·(1−p)
    status: str | None = None           # provider status, e.g. open / active
    variant: str | None = None          # scoring or rule variant that changes what the contract pays on
    void_rule: str | None = None        # what happens if the player doesn't play
    title: str | None = None
    quote_time: str | None = None       # provider's own last-update timestamp, if any
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    # Filled by matching
    game_id: str | None = None
    player_id: str | None = None        # nflverse gsis id
    match_note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def mid(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2

    @property
    def spread(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return self.yes_ask - self.yes_bid


def to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def price(v) -> float | None:
    """A 0-1 price. Zero means no order on that side (exchanges publish 0 for an empty side)."""
    x = to_float(v)
    if x is None or x <= 0 or x >= 1:
        return None
    return x
