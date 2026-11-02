"""Team names and codes per provider, mapped to Model Room's codes (nflverse for NFL, hoopR/ESPN for NBA)."""
from __future__ import annotations

from modelroom.sources.odds import NFL_TEAMS

NBA_TEAMS = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GS", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "LA Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NO", "New York Knicks": "NY", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SA", "Toronto Raptors": "TOR", "Utah Jazz": "UTAH", "Washington Wizards": "WSH",
}

BY_NAME = {"nfl": {k.lower(): v for k, v in NFL_TEAMS.items()}, "nba": {k.lower(): v for k, v in NBA_TEAMS.items()}}

# Kalshi event-ticker codes that differ from ours.
KALSHI_CODES = {
    "nfl": {"JAC": "JAX", "LAR": "LA"},
    "nba": {"NYK": "NY", "GSW": "GS", "NOP": "NO", "SAS": "SA", "UTA": "UTAH", "WAS": "WSH", "PHO": "PHX"},
}

# Polymarket US slug codes to try for our codes (lowercase), in order.
POLYMARKET_SLUG = {
    "nfl": {"LA": ["lar", "la"], "JAX": ["jax", "jac"], "WAS": ["was", "wsh"]},
    "nba": {"GS": ["gsw", "gs"], "NY": ["nyk", "ny"], "NO": ["nop", "no"], "SA": ["sas", "sa"], "UTAH": ["uta", "utah"],
            "WSH": ["was", "wsh"], "PHX": ["phx", "pho"], "BKN": ["bkn", "brk"]},
}


def code_from_name(league: str, name: str | None) -> str | None:
    if not name:
        return None
    return BY_NAME[league].get(name.lower())


def kalshi_code(league: str, code: str) -> str:
    return KALSHI_CODES.get(league, {}).get(code, code)


def slug_codes(league: str, code: str) -> list[str]:
    return POLYMARKET_SLUG.get(league, {}).get(code, [code.lower()])
