"""Match provider quotes to Model Room games and players.

Games: same ET date (±1 day) and the same two teams.
Players, in order: Sportradar ID (Kalshi gives it; nflverse rosters carry it) → normalized name + team
→ normalized name alone if it is unique among that game's players. Anything else stays unmatched and
is reported, never guessed.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

import pandas as pd

from .schema import PropQuote

SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")


def norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = SUFFIX.sub("", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def match_games(quotes: list[PropQuote], games: pd.DataFrame) -> None:
    idx: dict = {}
    for _, g in games.iterrows():
        d = date.fromisoformat(str(g["game_date"])[:10])
        for off in (-1, 0, 1):
            idx.setdefault((d + timedelta(days=off), frozenset((g["home_team"], g["away_team"]))), g)
    for q in quotes:
        if not q.game_date or not q.home_team or not q.away_team:
            q.match_note = "game: provider gave no date or teams"
            continue
        g = idx.get((date.fromisoformat(q.game_date), frozenset((q.home_team, q.away_team))))
        if g is None:
            q.match_note = "game: not on the Model Room schedule"
            continue
        q.game_id = g["game_id"]
        if q.home_team != g["home_team"]:
            q.home_team, q.away_team = g["home_team"], g["away_team"]


def match_players(quotes: list[PropQuote], players: pd.DataFrame) -> None:
    """players: one row per (game_id, player_id) with name, team, sportradar_id."""
    by_sr = {str(r.sportradar_id): r for r in players.itertuples() if isinstance(r.sportradar_id, str) and r.sportradar_id}
    by_game: dict = {}
    for r in players.itertuples():
        by_game.setdefault(r.game_id, []).append(r)
    for q in quotes:
        if q.game_id is None:
            continue
        cands = by_game.get(q.game_id, [])
        if q.sportradar_player_id and q.sportradar_player_id in by_sr:
            r = by_sr[q.sportradar_player_id]
            if any(c.player_id == r.player_id for c in cands):
                q.player_id, q.match_note = r.player_id, "player: sportradar id"
                continue
        n = norm_name(q.player_name)
        hits = [c for c in cands if norm_name(c.name) == n and (q.team is None or c.team == q.team)]
        if len(hits) == 1:
            q.player_id, q.match_note = hits[0].player_id, "player: name + team"
            continue
        last = n.split(" ")[-1] if n else ""
        first = n[:1]
        loose = [c for c in cands if norm_name(c.name).split(" ")[-1:] == [last] and norm_name(c.name)[:1] == first
                 and (q.team is None or c.team == q.team)]
        if len(loose) == 1:
            q.player_id, q.match_note = loose[0].player_id, "player: first initial + last name + team"
            continue
        q.match_note = "player: no unique match" if hits or loose else "player: not projected for this game"
