"""Polymarket US coverage audit (TEST, Moose 2026-11-27). Read-only; prints COUNTS ONLY.

For the upcoming NBA games (today and tomorrow, Pacific) and NFL games (next 8 days) on the published boards, fetches
each game's event from the public Polymarket US gateway (no key) and reports:
  * contracts per market (player props by stat, moneyline / spread / total), lines per player, two-sided quotes
  * players matched to Model Room's board EXACTLY (normalised full name, unique in the game, same team): never fuzzy
  * which per-contract fields exist (update time, last trade, volume, open interest, liquidity) - names only
  * any market types Model Room doesn't map yet
  * HTTP behaviour (requests, 404s, 429s, Retry-After)
Nothing is stored or printed beyond counts: Polymarket US data may not be redistributed except as PMUS permits
(participant agreement §I.22).

    python -m modelroom.markets.pm_audit --nba-board ... --nba-props ... --nfl-board ... --nfl-props ...
"""
from __future__ import annotations

import argparse
import json
import time
import unicodedata
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import teams as T
from .polymarket_us import BASE, MARKET_TYPES

PT = ZoneInfo("America/Los_Angeles")
GAME_TYPES = {"moneyline": "moneyline", "spreads": "spread", "totals": "total"}
SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(w for w in s.split() if w not in SUFFIX)


class Http:
    def __init__(self, gap=1.0):
        self.gap, self.last, self.n, self.c404, self.c429, self.retry_after, self.errors = gap, 0.0, 0, 0, 0, [], Counter()

    def get(self, path):
        for attempt in (1, 2):
            wait = self.gap - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.n += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"accept": "application/json", "User-Agent": "ModelRoom-audit/0.1"}), timeout=15) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    self.c404 += 1
                    return None
                if e.code == 429 and attempt == 1:
                    self.c429 += 1
                    ra = e.headers.get("Retry-After")
                    self.retry_after.append(ra)
                    time.sleep(min(30, float(ra or 5)))
                    continue
                self.errors[e.code] += 1
                return None
            except Exception as e:  # noqa: BLE001
                self.errors[type(e).__name__] += 1
                return None
        return None


def event_for(h: Http, league: str, away: str, home: str, date: str):
    for a in T.slug_codes(league, away):
        for hm in T.slug_codes(league, home):
            for slug in (f"{league}-{a}-{hm}-{date}", f"{league}-{hm}-{a}-{date}"):
                d = h.get(f"/v1/events/slug/{slug}")
                if d:
                    return d.get("event", d)
    return None


def audit_league(h: Http, league: str, board: dict, props: dict, now: datetime) -> dict:
    today = now.astimezone(PT).date()
    horizon = today + timedelta(days=1 if league == "nba" else 8)
    games = []
    for g in board.get("upcoming", []):
        st = g.get("start_time")
        if not st or datetime.fromisoformat(st.replace("Z", "+00:00")) <= now:
            continue
        d = datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone(PT).date()
        if d <= horizon:
            games.append(g)
    pboard = {g["game_id"]: g for g in props.get("games", [])}
    out = {"games_checked": len(games), "events_found": 0, "games_by_day": Counter(), "props": defaultdict(Counter), "game_lines": Counter(),
           "unmapped_types": Counter(), "fields_present": Counter(), "contracts": 0, "match": Counter(), "lines_per_player": Counter(),
           "markets_also_on_odds_api": "nba: points only" if league == "nba" else "nfl: receiving yards only"}
    for g in games:
        d = datetime.fromisoformat(g["start_time"].replace("Z", "+00:00")).astimezone(PT).date().isoformat()
        out["games_by_day"][d] += 1
        ev = event_for(h, league, g["away"]["abbr"], g["home"]["abbr"], g["game_date"])
        if not ev:
            continue
        out["events_found"] += 1
        teams = {t.get("id"): (t.get("abbreviation") or "").lower() for t in ev.get("teams") or []}
        pg = pboard.get(g["game_id"])
        players = defaultdict(list)
        for p in (pg or {}).get("players", []):
            players[norm(p["name"])].append(p)
        per_player = Counter()
        for m in ev.get("markets") or []:
            out["contracts"] += 1
            for f in ("updatedAt", "lastTradePrice", "volumeNum", "volume", "openInterest", "liquidity", "liquidityNum", "bestBidQuote", "bestAskQuote"):
                if m.get(f) not in (None, "", {}):
                    out["fields_present"][f] += 1
            smt = m.get("sportsMarketType") or ""
            key = MARKET_TYPES.get(smt)
            two = bool((m.get("bestBidQuote") or {}).get("value")) and bool((m.get("bestAskQuote") or {}).get("value"))
            if key:
                c = out["props"][key]
                c["contracts"] += 1
                c["two_sided"] += two
                name = (m.get("metadata") or {}).get("playerName")
                cands = players.get(norm(name), [])
                team = teams.get((m.get("metadata") or {}).get("teamId"))
                if not pg:
                    out["match"]["no Model Room player board for game"] += 1
                elif len(cands) == 1 and team and team in T.slug_codes(league, cands[0]["team"]):
                    out["match"]["exact (name + team)"] += 1
                    c["matched"] += 1
                    per_player[(cands[0]["player_id"], key)] += 1
                    if key in cands[0].get("markets", {}):
                        c["model_has_market"] += 1
                elif len(cands) > 1:
                    out["match"]["ambiguous name: skipped"] += 1
                elif len(cands) == 1:
                    out["match"]["team mismatch: skipped"] += 1
                else:
                    out["match"]["player not on Model Room board"] += 1
            elif GAME_TYPES.get(m.get("marketType") or ""):
                kind = GAME_TYPES[m["marketType"]]
                full = (smt.endswith("full_game_spread") if kind == "spread" else smt.endswith("full_game_total") and "team_points" not in smt if kind == "total" else smt in ("moneyline",) or smt.endswith("full_game_winner"))
                out["game_lines"][f"{kind}{'' if full else ' (partial game / other)'}"] += 1
            else:
                out["unmapped_types"][smt or (m.get("marketType") or "unknown")] += 1
        for v in per_player.values():
            out["lines_per_player"][min(v, 6)] += 1
    out["props"] = {k: dict(v) for k, v in out["props"].items()}
    for k in ("games_by_day", "game_lines", "unmapped_types", "fields_present", "match", "lines_per_player"):
        out[k] = dict(out[k])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for lg in ("nba", "nfl"):
        ap.add_argument(f"--{lg}-board")
        ap.add_argument(f"--{lg}-props")
    a = ap.parse_args(argv)
    h = Http()
    now = datetime.now(timezone.utc)
    report = {"checked_at": now.isoformat(timespec="seconds"), "source": BASE, "leagues": {}}
    h.get("/v1/events?limit=1")       # does a general listing endpoint answer without a key?
    for lg in ("nba", "nfl"):
        b, p = getattr(a, f"{lg}_board"), getattr(a, f"{lg}_props")
        if b and p:
            report["leagues"][lg] = audit_league(h, lg, json.load(open(b)), json.load(open(p)), now)
    report["http"] = {"requests": h.n, "not_found_404": h.c404, "rate_limited_429": h.c429, "retry_after_values": h.retry_after[:5], "errors": dict(h.errors)}
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
