"""ESPN's public site API (undocumented, no key): team rosters with injury entries, the league injury feed
(news comments, return dates), NFL depth charts, and NBA game rosters / starters once ESPN posts them.

TEST SITE ONLY: ESPN publishes no license for this API. Its terms of use limit commercial use of ESPN
content; do not use this adapter in production without written permission (see docs/data/injuries.md).

ESPN's injury statuses come from its news desk (team reports, beat writers): they are reports, not the
league's official designations, and every row says so (kind = "report").
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import UTC, datetime

import pandas as pd

from . import schema as S

SITE = "https://site.api.espn.com/apis/site/v2/sports"
PATH = {"nfl": "football/nfl", "nba": "basketball/nba"}
NFL_ABBR = {"LAR": "LA", "WSH": "WAS"}   # ESPN → nflverse; NBA abbreviations already match the engine's
UA = {"User-Agent": "Mozilla/5.0 (compatible; ModelRoom/0.1; test site)"}


def get_json(url: str, retries: int = 3, timeout: int = 30):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"ESPN request failed: {url}: {last}")


def team_abbr(league: str, a: str | None) -> str | None:
    return NFL_ABBR.get(a, a) if league == "nfl" else a


def _ts(s) -> pd.Timestamp | None:
    if not s:
        return None
    t = pd.Timestamp(s)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def teams(league: str, get=get_json) -> list[dict]:
    d = get(f"{SITE}/{PATH[league]}/teams")
    return [t["team"] for t in d["sports"][0]["leagues"][0]["teams"]]


def roster_athletes(d: dict) -> list[dict]:
    a = d.get("athletes") or []
    if a and isinstance(a[0], dict) and "items" in a[0]:   # NFL groups by unit
        return [x for g in a for x in g.get("items", [])]
    return a


def parse_team(league: str, roster: dict, feed: dict[str, dict], fetched_at: pd.Timestamp) -> tuple[list[dict], list[dict]]:
    """(injury rows, roster rows) for one team. feed = {espn athlete id: league-feed entry} (comments, details)."""
    team = team_abbr(league, (roster.get("team") or {}).get("abbreviation"))
    rows, people = [], []
    for a in roster_athletes(roster):
        aid = str(a.get("id"))
        pos = (a.get("position") or {}).get("abbreviation")
        people.append({"team": team, "source_player_id": aid, "player": a.get("displayName"), "position": pos,
                       "experience_years": (a.get("experience") or {}).get("years"), "roster_status": (a.get("status") or {}).get("name")})
        inj = sorted(a.get("injuries") or [], key=lambda i: i.get("date") or "")
        f = feed.get(aid)
        if not inj and not f:
            continue
        latest = inj[-1] if inj else {}
        # The league feed carries the comment and may be newer; take whichever entry is more recent.
        if f and (not latest or (f.get("date") or "") >= (latest.get("date") or "")):
            latest = {**latest, **f}
        raw = latest.get("status")
        comment = " ".join(x for x in (latest.get("shortComment"), latest.get("longComment")) if x) or None
        det = latest.get("details") or {}
        rmin = S.restriction(comment)
        ret_date = _ts(det.get("returnDate"))
        long_term = (str(raw or "").lower() in S.LONG_TERM) or S.season_over(comment) or bool(ret_date and ret_date - fetched_at > pd.Timedelta(days=21))
        rows.append({"league": league, "source": "espn", "kind": "report", "team": team, "player_id": None, "player": a.get("displayName"),
                     "position": pos, "source_player_id": aid, "status": S.canonical(raw), "raw_status": raw,
                     "detail": " ".join(str(det[k]) for k in ("side", "type", "detail") if det.get(k)) or None, "comment": comment,
                     "report_time": _ts(latest.get("date")), "fetched_at": fetched_at, "game_date": None,
                     "restriction": rmin[0], "restriction_minutes": rmin[1], "returning": S.returning(comment), "long_term": bool(long_term)})
    return rows, people


def depth(league: str, d: dict, team: str, fetched_at: pd.Timestamp) -> list[dict]:
    """NFL offense depth chart: (team, pos, rank, espn id)."""
    out = []
    for chart in d.get("depthchart") or []:
        for key, pos in (chart.get("positions") or {}).items():
            abb = "".join(ch for ch in key if not ch.isdigit()).upper()
            if abb not in ("QB", "RB", "WR", "TE", "FB"):
                continue
            for rank, a in enumerate(pos.get("athletes") or [], start=1):
                out.append({"team": team, "chart": chart.get("name"), "pos": abb, "slot": key, "rank": rank, "source_player_id": str(a.get("id")),
                            "player": a.get("displayName"), "fetched_at": fetched_at})
    return out


def game_starters(league: str, summary: dict, fetched_at: pd.Timestamp) -> list[dict]:
    """Starters ESPN lists for a game (box score / rosters). Empty until ESPN posts the lineups (around tip-off)."""
    out = []
    for blk in (summary.get("rosters") or []):
        team = team_abbr(league, (blk.get("team") or {}).get("abbreviation"))
        for a in blk.get("roster") or []:
            if a.get("starter") is not None:
                out.append({"team": team, "source_player_id": str((a.get("athlete") or {}).get("id")), "starter": bool(a.get("starter")),
                            "fetched_at": fetched_at, "source": "espn_rosters"})
    if out:
        return out
    for blk in ((summary.get("boxscore") or {}).get("players") or []):
        team = team_abbr(league, (blk.get("team") or {}).get("abbreviation"))
        for st in blk.get("statistics") or []:
            for a in st.get("athletes") or []:
                if "starter" in a:
                    out.append({"team": team, "source_player_id": str((a.get("athlete") or {}).get("id")), "starter": bool(a["starter"]),
                                "fetched_at": fetched_at, "source": "espn_boxscore"})
    return out


def fetch(league: str, *, get=get_json, now: pd.Timestamp | None = None, starters_within_hours: float = 3.0) -> dict:
    """Everything ESPN has for the league right now. Raises if the core roster calls fail."""
    now = now or pd.Timestamp(datetime.now(UTC))
    feed: dict[str, dict] = {}
    try:
        lf = get(f"{SITE}/{PATH[league]}/injuries")
        for t in lf.get("injuries") or []:
            for i in t.get("injuries") or []:
                aid = str(((i.get("athlete") or {}).get("links") or [{}])[0].get("href", "").split("/id/")[-1].split("/")[0] or "")
                if not aid:
                    continue
                feed[aid] = {k: i.get(k) for k in ("status", "date", "shortComment", "longComment", "details", "type")}
    except Exception:  # noqa: BLE001 — the per-team rosters are the primary source; the feed only adds comments
        feed = {}
    rows, people, dep, errors = [], [], [], []
    for t in teams(league, get):
        try:
            r = get(f"{SITE}/{PATH[league]}/teams/{t['id']}/roster")
            r.setdefault("team", {"abbreviation": t.get("abbreviation")})
            a, p = parse_team(league, r, feed, now)
            rows += a
            people += p
            if league == "nfl":
                dep += depth(league, get(f"{SITE}/{PATH[league]}/teams/{t['id']}/depthcharts"), team_abbr(league, t.get("abbreviation")), now)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{t.get('abbreviation')}: {e}")
    starters: list[dict] = []
    if league == "nba":
        for day in {now.tz_convert("America/New_York").date(), (now + pd.Timedelta(hours=starters_within_hours)).tz_convert("America/New_York").date()}:
            try:
                sb = get(f"{SITE}/{PATH[league]}/scoreboard?dates={day:%Y%m%d}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"scoreboard {day}: {e}")
                continue
            for e in sb.get("events") or []:
                st = _ts(e.get("date"))
                if st is None or not (now - pd.Timedelta(hours=1) <= st <= now + pd.Timedelta(hours=starters_within_hours)):
                    continue
                try:
                    starters += [{**x, "espn_event": e["id"], "game_start": st} for x in game_starters(league, get(f"{SITE}/{PATH[league]}/summary?event={e['id']}"), now)]
                except Exception as ex:  # noqa: BLE001
                    errors.append(f"summary {e['id']}: {ex}")
    if not people:
        raise RuntimeError(f"ESPN {league}: no rosters fetched ({'; '.join(errors[:3])})")
    return {"rows": pd.DataFrame(rows, columns=S.COLUMNS), "roster": pd.DataFrame(people), "depth": pd.DataFrame(dep),
            "starters": pd.DataFrame(starters), "errors": errors, "fetched_at": now}
