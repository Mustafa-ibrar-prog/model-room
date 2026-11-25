"""Matching Odds API player-points quotes to Model Room's NBA board, and picking each book's main line (TEST; Moose
2026-11-24). Pure functions: nothing is fetched, stored or estimated here.

Game: an Odds API event matches a board game when both team nicknames agree and the start times are within 6 hours.
Player: exact name after normalising (case, accents, punctuation, Jr./Sr./II/III/IV), only among that game's players on
the board; then config/nba_player_aliases.csv (provider_name,player_id); otherwise unmatched (kept, never guessed,
no fuzzy matching).
Main line per book and player: the line whose Over/Under prices are most balanced after removing the book's margin
(no-vig Over probability closest to 0.5); ties go to the lower line. Every other line is kept, flagged as alternate.
"""
from __future__ import annotations

import csv
import re
import statistics
import unicodedata
from datetime import datetime
from pathlib import Path

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
MAX_START_GAP_H = 6


def norm_name(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’\-,]", " ", s)
    return " ".join(w for w in s.split() if w not in SUFFIXES)


def nickname(team: str | None) -> str:
    w = (team or "").strip().lower().split()
    return w[-1] if w else ""


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def match_game(event: dict, games: list[dict]) -> dict | None:
    """The board game for an Odds API event (home/away nicknames + start within 6 h), or None."""
    h, a = nickname(event.get("home_team")), nickname(event.get("away_team"))
    t = _ts(event["commence_time"])
    for g in games:
        if nickname(g["home"]["name"]) == h and nickname(g["away"]["name"]) == a and g.get("start_time"):
            if abs((_ts(g["start_time"]) - t).total_seconds()) <= MAX_START_GAP_H * 3600:
                return g
    return None


def load_aliases(path: Path | None) -> dict[str, str]:
    if not path or not Path(path).exists():
        return {}
    with open(path, newline="") as f:
        return {norm_name(r["provider_name"]): str(r["player_id"]).strip() for r in csv.DictReader(f) if r.get("provider_name") and r.get("player_id")}


def match_player(name: str, game: dict, aliases: dict[str, str]) -> tuple[str | None, str]:
    """(player_id, method). Only players of this game's two teams on the board are candidates."""
    players = game.get("players") or []
    n = norm_name(name)
    hits = [p for p in players if norm_name(p["name"]) == n]
    if len(hits) == 1:
        return str(hits[0]["player_id"]), "exact"
    if len(hits) > 1:
        return None, "ambiguous name"
    pid = aliases.get(n)
    if pid and any(str(p["player_id"]) == pid for p in players):
        return pid, "alias"
    return None, "not on the board for this game"


def implied(american) -> float | None:
    try:
        o = float(american)
    except (TypeError, ValueError):
        return None
    if -100 < o < 100:
        return None
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def rows_from_response(resp: dict, game: dict | None, aliases: dict[str, str], fetched_at: str, raw_sha256: str) -> list[dict]:
    """One row per book x player x line, with Over and Under prices side by side, as the provider gave them."""
    pairs: dict[tuple, dict] = {}
    for b in resp.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") != "player_points":
                continue
            for o in m.get("outcomes") or []:
                k = (b.get("key"), o.get("description"), o.get("point"))
                r = pairs.setdefault(k, {"event_id": resp.get("id"), "commence_time": resp.get("commence_time"), "home_team": resp.get("home_team"),
                                         "away_team": resp.get("away_team"), "book_key": b.get("key"), "book_title": b.get("title"),
                                         "market": "player_points", "book_last_update": m.get("last_update"), "player_name": o.get("description"),
                                         "line": o.get("point"), "over_price": None, "under_price": None})
                side = str(o.get("name", "")).lower()
                if side in ("over", "under"):
                    r[f"{side}_price"] = o.get("price")
    out = []
    for r in pairs.values():
        po, pu = implied(r["over_price"]), implied(r["under_price"])
        pid, how = (match_player(r["player_name"], game, aliases) if game else (None, "game not on the board"))
        out.append({**r, "over_implied": None if po is None else round(po, 5), "under_implied": None if pu is None else round(pu, 5),
                    "over_novig": None if po is None or pu is None else round(po / (po + pu), 5),
                    "game_id": game["game_id"] if game else None, "player_id": pid, "match": how, "is_main": False,
                    "fetched_at": fetched_at, "source": "the_odds_api", "raw_sha256": raw_sha256})
    mark_main(out)
    return sorted(out, key=lambda r: (str(r["player_name"]), str(r["book_key"]), float(r["line"] if r["line"] is not None else 0)))


def mark_main(rows: list[dict]) -> None:
    """Per book and player: the most balanced two-sided line is the main one (ties: lower line). Others stay, as alternates."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["book_key"], r["player_name"]), []).append(r)
    for g in groups.values():
        two = [r for r in g if r["over_novig"] is not None and r["line"] is not None]
        if not two:
            continue
        best = min(two, key=lambda r: (abs(r["over_novig"] - 0.5), float(r["line"])))
        best["is_main"] = True


def view_for_game(rows: list[dict], game: dict | None, captured_at: str) -> dict:
    """Compact per-player summary for the site: each book's main line and prices, the consensus (median of main lines)."""
    players: dict[str, dict] = {}
    for r in rows:
        if not r["player_id"]:
            continue
        p = players.setdefault(r["player_id"], {"name": r["player_name"], "books": [], "alternates": 0})
        if r["is_main"]:
            p["books"].append({"book": r["book_key"], "title": r["book_title"], "line": r["line"], "over": r["over_price"], "under": r["under_price"],
                               "over_novig": r["over_novig"], "last_update": r["book_last_update"]})
        else:
            p["alternates"] += 1
    for p in players.values():
        lines = [b["line"] for b in p["books"]]
        nv = [b["over_novig"] for b in p["books"] if b["over_novig"] is not None]
        p["consensus_line"] = statistics.median(lines) if lines else None
        p["consensus_over_novig"] = round(statistics.median(nv), 4) if nv else None
        p["last_update"] = max((b["last_update"] for b in p["books"] if b["last_update"]), default=None)
        p["books"].sort(key=lambda b: str(b["title"]))
    any_r = rows[0] if rows else {}
    return {"game_id": game["game_id"] if game else None, "event_id": any_r.get("event_id"), "commence_time": any_r.get("commence_time"),
            "home_team": any_r.get("home_team"), "away_team": any_r.get("away_team"), "captured_at": captured_at,
            "players": {k: v for k, v in players.items() if v["books"]},
            "unmatched_players": len({r["player_name"] for r in rows if not r["player_id"]})}
