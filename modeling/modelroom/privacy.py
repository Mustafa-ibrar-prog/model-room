"""What may appear in PUBLIC outputs: everything committed to the public repository (the preview branch's
data/published and preview-ledger) and everything the site serves to subscribers.

Rule: no individual sportsbook's name, line or price. Book-level detail lives only in the private Supabase tables
(odds.snapshots / odds.comparisons / odds.reports), read by the owner dashboard through a read-only role.

Allowed publicly: a consensus line or price only when at least MIN_PUBLIC_BOOKS books quoted it (so it never equals
one book's number), plus counts (how many books) and timestamps. The data source's own name ("the_odds_api") is not
a sportsbook.

Secrets and private database identifiers are never published either: the same scan looks for connection strings,
Supabase hosts, known token shapes, and the literal value of any secret in the environment it runs with.

`sanitize_market` / `sanitize_edges` strip book-level structures from a board before it is written; `violations`
finds anything that slipped through and `assert_public` refuses to write it (fail closed). The refresh workflow runs

    python3 -m modelroom.privacy scan data/published preview-ledger

over everything it is about to commit, and publishes nothing if that exits non-zero.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
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


# Private infrastructure: a connection string or a database host identifies the private store.
DB_PATTERNS: list[tuple[str, str]] = [
    (r"postgres(?:ql)?://[^\s\"']{4,}", "database connection string"),
    (r"\b[a-z0-9-]+\.pooler\.supabase\.com\b", "Supabase pooler host"),
    (r"\bdb\.[a-z]{16,24}\.supabase\.co\b", "Supabase database host"),
    (r"\bproject[_-]?ref\s*[:=]\s*['\"]?[a-z]{20}\b", "Supabase project ref"),
]
# Credentials, by shape. The literal values of secrets in the environment are checked separately (and never printed).
SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained token"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "JSON Web Token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"(?i)\b(?:api[_-]?key|secret|password|token)['\"]?\s*[:=]\s*['\"][^'\"\s]{12,}['\"]", "credential assignment"),
    (r"(?i)[?&]apikey=[A-Za-z0-9]{8,}", "API key in a URL"),
]
# Environment variables whose value must never appear in a published file. The value is compared, never printed.
SECRET_ENV_VARS = ("ODDS_API_KEY", "SUPABASE_DB_URL", "MODELROOM_ODDS_DB_URL", "MODELROOM_OWNER_DB_URL",
                   "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ACCESS_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")


def secret_violations(text: str, label: str, env: dict[str, str] | None = None) -> list[str]:
    """Credentials and private database identifiers in a text that is about to be published."""
    out: list[str] = []
    for pat, what in DB_PATTERNS + SECRET_PATTERNS:
        if re.search(pat, text):
            out.append(f"{label}: {what}")
    for var in SECRET_ENV_VARS:
        val = (env or os.environ).get(var, "")
        if len(val) >= 8 and val in text:
            out.append(f"{label}: the value of {var} appears in this file")
    return out


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
    """JSON or JSON-lines text: structural violations; anything unparseable is scanned as plain text for names.
    Credentials and private database identifiers are looked for in every file, whatever its shape."""
    out: list[str] = secret_violations(text, label)
    try:
        return out + [f"{label} {v}" for v in violations(json.loads(text))]
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


def main(argv: list[str] | None = None) -> int:
    """`python3 -m modelroom.privacy scan <path>...` — exits 1 if anything in those paths may not be published."""
    ap = argparse.ArgumentParser(description="Refuse to publish sportsbook-level data, credentials or private database identifiers.")
    ap.add_argument("cmd", choices=["scan"])
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args(argv)
    files: list[Path] = []
    for p in map(Path, a.paths):
        files += sorted(f for f in ([p] if p.is_file() else p.rglob("*")) if f.is_file())
    findings = scan_paths(files)
    print(f"privacy scan: {len(files)} file(s) in {', '.join(a.paths)}")
    if not findings:
        print("privacy scan: nothing to withhold")
        return 0
    print(f"::error::privacy scan found {len(findings)} problem(s); nothing will be published")
    for f in findings[:50]:
        print(f"  {f}")
    if len(findings) > 50:
        print(f"  ... and {len(findings) - 50} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
