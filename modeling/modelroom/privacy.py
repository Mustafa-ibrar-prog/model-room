"""What may appear in PUBLIC outputs: everything committed to the public repository (the preview branch's
data/published and preview-ledger) and everything the site serves to subscribers.

Rule: no individual sportsbook's name, line or price. Book-level detail lives only in the private Supabase tables
(odds.snapshots / odds.comparisons / odds.reports), read by the owner dashboard through a read-only role.

Allowed publicly: a consensus line or price only when at least MIN_PUBLIC_BOOKS books quoted it (so it never equals
one book's number), plus counts (how many books) and timestamps. The data source's own name ("the_odds_api") is not
a sportsbook.

`sanitize_market` / `sanitize_edges` strip book-level structures from a board before it is written; `violations`
finds anything that slipped through and `assert_public` refuses to write it (fail closed).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

MIN_PUBLIC_BOOKS = 2

# The Odds API bookmakers for the US regions (us, us2, us_dfs, us_ex): key and title, from
# https://the-odds-api.com/sports-odds-data/bookmaker-apis.html (Nov 2026), plus common alternate spellings.
BOOKMAKERS: dict[str, str] = {
    "betonlineag": "BetOnline.ag", "betmgm": "BetMGM", "betrivers": "BetRivers", "betus": "BetUS", "bovada": "Bovada",
    "williamhill_us": "Caesars", "draftkings": "DraftKings", "fanatics": "Fanatics", "fanduel": "FanDuel",
    "lowvig": "LowVig.ag", "mybookieag": "MyBookie.ag",
    "ballybet": "Bally Bet", "betanysports": "BetAnything", "betparx": "betPARX", "betwhale": "Betwhale",
    "courtside": "Courtside", "espnbet": "theScore Bet", "fliff": "Fliff", "hardrockbet": "Hard Rock Bet",
    "hardrockbet_az": "Hard Rock Bet (AZ)", "hardrockbet_fl": "Hard Rock Bet (FL)", "hardrockbet_oh": "Hard Rock Bet (OH)",
    "rebet": "ReBet",
    "dabble_us_dfs": "Dabble", "parlayplay": "ParlayPlay", "pick6": "DraftKings Pick6", "prizepicks": "PrizePicks",
    "underdog": "Underdog Fantasy",
    "betopenly": "BetOpenly", "limitless": "Limitless Exchange", "novig": "Novig", "prophetx": "ProphetX",
}
# Extra spellings seen in other feeds (ESPN odds providers and the like).
ALIASES = ["ESPN BET", "Caesars Sportsbook", "William Hill", "Hard Rock", "BetOnline", "MyBookie", "Barstool", "PointsBet",
           "Unibet", "WynnBET", "SuperBook", "Circa", "SI Sportsbook", "Betfred", "Borgata", "Golden Nugget", "Pinnacle",
           "bet365", "Bet365", "Tipico", "FOX Bet", "Twinspires", "Betway"]

NAMES: list[str] = sorted({*BOOKMAKERS, *BOOKMAKERS.values(), *ALIASES}, key=len, reverse=True)
_NAME_RE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(n) for n in NAMES) + r")(?![A-Za-z0-9])", re.IGNORECASE)

# Keys that only ever hold book-level data.
FORBIDDEN_KEYS = {
    "by_book", "rows_by_book", "books_seen", "movement_by_book", "coverage_rows_by_book", "line_histories",
    "coverage_detail", "upcoming_latest_comparisons", "settled_events", "bookmaker", "bookmakers", "sportsbook",
    "sportsbooks", "book", "missing_books", "missing_markets_by_book",
}
# Free-text news fields from public injury feeds (ESPN player comments, report notes). A reporter's affiliation
# ("... of BetUS TV reports") is not sportsbook data, so a name inside these texts is not a finding.
NEWS_TEXT_KEYS = {"comment", "comments", "news", "headline", "description", "short_comment", "long_comment"}
# Market blocks whose lines come from a public dataset (not a sportsbook feed) are exempt from the book minimum:
# nflverse publishes each game's line openly. Lines from the Odds API (or with no stated source) are not.
PUBLIC_LINE_SOURCES = {"nflverse"}

# Words that are not sportsbook names even though a name may contain them (e.g. "Circa" the word is rare; "Underdog"
# alone is a normal betting word): only these exact, whole values are exempt.
_EXEMPT_VALUES = {"underdog", "circa", "novig", "pick6", "courtside", "limitless", "the_odds_api", "theoddsapi"}


def _name_hits(text: str) -> list[str]:
    hits = []
    for m in _NAME_RE.finditer(text):
        w = m.group(1)
        if w.lower() in _EXEMPT_VALUES:
            continue
        hits.append(w)
    return hits


def violations(obj: Any, where: str = "$") -> list[str]:
    """Every place in a JSON-like object that would expose a sportsbook: a forbidden key, a book name used as a key,
    a book name inside a string value, or a consensus line or price backed by fewer than MIN_PUBLIC_BOOKS books."""
    out: list[str] = []
    if isinstance(obj, dict):
        books = obj.get("books")
        srcs = obj.get("sources")
        public_src = isinstance(srcs, list) and bool(srcs) and all(str(s) in PUBLIC_LINE_SOURCES for s in srcs)
        if isinstance(books, (int, float)) and books < MIN_PUBLIC_BOOKS and not public_src and any(
            obj.get(k) is not None for k in ("spread", "total", "home_ml", "away_ml")
        ) and "captured_at" in obj:
            out.append(f"{where}: market line or price from {books} book(s), below the public minimum of {MIN_PUBLIC_BOOKS}")
        for k, v in obj.items():
            ks = str(k)
            if ks in FORBIDDEN_KEYS:
                out.append(f"{where}.{ks}: book-level key")
                continue
            if _name_hits(ks):
                out.append(f"{where}.{ks}: sportsbook name used as a key")
                continue
            if ks in NEWS_TEXT_KEYS and isinstance(v, str):
                continue
            out.extend(violations(v, f"{where}.{ks}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(violations(v, f"{where}[{i}]"))
    elif isinstance(obj, str):
        hits = _name_hits(obj)
        if hits:
            out.append(f"{where}: sportsbook name in text ({', '.join(sorted(set(h.lower() for h in hits)))})")
    return out


class PrivacyError(RuntimeError):
    pass


def assert_public(obj: Any, label: str) -> None:
    v = violations(obj)
    if v:
        raise PrivacyError(f"{label}: refusing to publish sportsbook-level data ({len(v)} finding(s)); first: {v[:3]}")


# ------------------------------------------------------------------ sanitizers for the public board
def sanitize_market(market: dict | None) -> dict | None:
    """Public form of a board's market block: consensus only, and only where enough books quoted it."""
    if not market:
        return market
    m = {k: v for k, v in market.items() if k not in FORBIDDEN_KEYS}
    srcs = m.get("sources") or []
    if srcs and all(str(s) in PUBLIC_LINE_SOURCES for s in srcs):
        return m
    if int(m.get("books") or 0) < MIN_PUBLIC_BOOKS:
        for k in ("spread", "total", "home_ml", "away_ml"):
            m[k] = None
    return m


def sanitize_edges(edges: dict | None) -> dict | None:
    if not edges:
        return edges
    return {k: v for k, v in edges.items() if k not in FORBIDDEN_KEYS}


# ------------------------------------------------------------------ scanning files (tests and audits)
def scan_text(text: str, label: str) -> list[str]:
    """JSON or JSON-lines text: structural violations; anything unparseable is scanned as plain text for names."""
    out: list[str] = []
    try:
        return [f"{label} {v}" for v in violations(json.loads(text))]
    except ValueError:
        pass
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.extend(f"{label}:{i} {v}" for v in violations(json.loads(line)))
        except ValueError:
            hits = _name_hits(line)
            if hits:
                out.append(f"{label}:{i}: sportsbook name in text ({', '.join(sorted(set(h.lower() for h in hits)))})")
    return out


def scan_paths(paths: Iterable[Path], root: Path | None = None) -> list[str]:
    out: list[str] = []
    for p in paths:
        label = str(p.relative_to(root)) if root else str(p)
        if p.suffix in (".json", ".jsonl", ".txt", ".csv", ".md"):
            out.extend(scan_text(p.read_text(encoding="utf-8", errors="replace"), label))
        elif p.suffix == ".parquet":
            out.append(f"{label}: parquet file in a public directory (raw tables are never published)")
    return out
