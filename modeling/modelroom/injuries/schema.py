"""The normalized injury row every adapter produces, so sources can be swapped (BALLDONTLIE, an official
provider) without touching the engines.

One row = one player's availability as one source reported it at one time:

    league, source, kind          kind: "official" (league report) | "report" (news / team-sourced feed)
    team, player_id, player, position, source_player_id
    status                        canonical: out, doubtful, questionable, probable, available, unknown
    raw_status, detail, comment
    report_time                   when the source says the status was set (UTC)
    fetched_at                    when we fetched it (UTC)
    game_date                     the game the designation is for, when the source says (official reports)
    restriction                   minutes restriction mentioned (bool), restriction_minutes (number when given)
    returning                     the source says the player is returning / cleared
    long_term                     injured reserve / season-ending / return date in the future
"""
from __future__ import annotations

import re

COLUMNS = ["league", "source", "kind", "team", "player_id", "player", "position", "source_player_id", "status", "raw_status",
           "detail", "comment", "report_time", "fetched_at", "game_date", "restriction", "restriction_minutes", "returning", "long_term"]

SEVERITY = {"out": 4, "doubtful": 3, "questionable": 2, "probable": 1, "available": 0, "unknown": -1}

_MAP = {
    "out": "out", "o": "out", "injured reserve": "out", "ir": "out", "injured reserve - designated for return": "out",
    "physically unable to perform": "out", "pup": "out", "suspension": "out", "suspended": "out", "non-football injury": "out",
    "reserve/covid-19": "out", "not with team": "out", "inactive": "out",
    "doubtful": "doubtful", "d": "doubtful",
    "questionable": "questionable", "q": "questionable", "game time decision": "questionable", "day-to-day": "questionable",
    "probable": "probable", "p": "probable",
    "active": "available", "available": "available",
}
LONG_TERM = {"injured reserve", "ir", "physically unable to perform", "pup", "injured reserve - designated for return", "non-football injury"}

_RESTRICT = re.compile(r"minutes? (restriction|limit)|limited minutes|on a (strict )?minutes|minutes cap", re.IGNORECASE)
_RESTRICT_N = re.compile(r"(?:about|around|roughly|approximately|~)?\s*(\d{1,2})\s*minutes", re.IGNORECASE)
_RETURN = re.compile(r"\b(will|expected to|set to|plans to|is slated to|cleared to) (return|play|make (his|her) (season )?debut)|\bwill be available\b|\bcleared to play\b|\bwill make his return\b", re.IGNORECASE)
_SEASON_OVER = re.compile(r"season-ending|out for the (season|year)|remainder of the season", re.IGNORECASE)


def canonical(raw: str | None) -> str:
    if not raw:
        return "unknown"
    return _MAP.get(str(raw).strip().lower(), "unknown")


def restriction(text: str | None) -> tuple[bool, float | None]:
    if not text or not _RESTRICT.search(text):
        return False, None
    m = _RESTRICT_N.search(text)
    n = float(m.group(1)) if m and 5 <= int(m.group(1)) <= 40 else None
    return True, n


def returning(text: str | None) -> bool:
    return bool(text and _RETURN.search(text))


def season_over(text: str | None) -> bool:
    return bool(text and _SEASON_OVER.search(text))


def norm_name(s: str | None) -> str:
    """'Jackson Jr., Jaren' / 'Jaren Jackson Jr.' → 'jaren jackson' (for matching across sources)."""
    if not s:
        return ""
    s = str(s)
    if "," in s:
        last, first = s.split(",", 1)
        s = f"{first} {last}"
    s = re.sub(r"[.'’`-]", "", s.lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()
