"""The NBA's official injury report (official.nba.com): a PDF the league republishes every 15 minutes on game
days, listing every player who isn't fully available for each game with Out / Doubtful / Questionable /
Probable / Available, and "NOT YET SUBMITTED" for teams that haven't filed.

    https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM.pdf   (time = US Eastern)

This is the league's own designation (kind = "official"). A player missing from a submitted team's report
is available for that game. The report covers the next day or two of games only.

Public, no key. The NBA's terms of use govern reuse; it is used on the test site only for now.
"""
from __future__ import annotations

import io
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import schema as S

ET = ZoneInfo("America/New_York")
URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{}.pdf"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ModelRoom/0.1; test site)"}
HEAD = ["Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason"]
TEAMS = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET", "Golden State Warriors": "GS",
    "Houston Rockets": "HOU", "Indiana Pacers": "IND", "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NO",
    "New York Knicks": "NY", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SA", "Toronto Raptors": "TOR", "Utah Jazz": "UTAH",
    "Washington Wizards": "WSH",
}
STATUS = {"Out", "Doubtful", "Questionable", "Probable", "Available"}


def candidate_urls(now: datetime, hours_back: float = 36) -> list[tuple[str, datetime]]:
    """Newest first: every 15-minute slot (current format) and every hour (older format)."""
    t = now.astimezone(ET).replace(second=0, microsecond=0)
    t = t.replace(minute=(t.minute // 15) * 15)
    out = []
    for i in range(int(hours_back * 4)):
        x = t - timedelta(minutes=15 * i)
        out.append((URL.format(x.strftime("%Y-%m-%d_%I_%M%p")), x))
        if x.minute == 0:
            out.append((URL.format(x.strftime("%Y-%m-%d_%I%p")), x))
    return out


def latest_pdf(now: datetime | None = None, opener=None) -> tuple[bytes, str, datetime] | None:
    now = now or datetime.now(UTC)
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read())
    for url, t in candidate_urls(now):
        try:
            return opener(url), url, t
        except Exception:  # noqa: BLE001 — not published for that slot
            continue
    return None


def _lines(page, bounds: list[float]) -> list[list[str]]:
    """Group the page's characters into rows, then split each row into the report's columns."""
    rows: dict[int, list] = {}
    for c in page.chars:
        rows.setdefault(round(c["top"] / 3), []).append(c)
    out = []
    for _, cs in sorted(rows.items()):
        cs.sort(key=lambda c: c["x0"])
        cols = [""] * len(HEAD)
        prev = None
        for c in cs:
            k = max(i for i, b in enumerate(bounds) if c["x0"] >= b - 2) if c["x0"] >= bounds[0] - 2 else 0
            gap = prev is not None and prev[0] == k and c["x0"] - prev[1] > 1.2
            cols[k] += (" " if gap else "") + c["text"]
            prev = (k, c["x1"])
        out.append([x.strip() for x in cols])
    return out


def parse(pdf_bytes: bytes, report_time: datetime, fetched_at: datetime | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """(player rows, team filings) from one report. Team filings: [{game_date, team, submitted}]."""
    import pdfplumber

    fetched_at = fetched_at or datetime.now(UTC)
    rows, filings = [], []
    date = gtime = matchup = team = None
    bounds = None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            if bounds is None:
                heads = {w["text"]: w["x0"] for w in words}
                xs = [heads.get(h.replace(" ", "")) for h in HEAD]
                if any(x is None for x in xs):
                    raise ValueError("NBA injury report: header not found (format changed?)")
                bounds = xs
            for c in _lines(page, bounds):
                joined = " ".join(c)
                if "Injury Report" in joined or re.search(r"Page \d+ of \d+", joined) or c[4] == "Player Name" or not joined.strip():
                    continue
                if re.match(r"\d{2}/\d{2}/\d{4}", c[0]):
                    date = datetime.strptime(c[0][:10], "%m/%d/%Y").date()
                if c[1]:
                    gtime = c[1]
                if c[2]:
                    matchup = c[2]
                if c[3]:
                    team = TEAMS.get(c[3], c[3])
                    filings.append({"game_date": date, "team": team, "matchup": matchup, "submitted": "NOT YET SUBMITTED" not in c[6]})
                if "NOT YET SUBMITTED" in c[6] and not c[4]:
                    if filings and filings[-1]["team"] == team:
                        filings[-1]["submitted"] = False
                    continue
                if c[4] and c[5] in STATUS:
                    rmin = S.restriction(c[6])
                    rows.append({"league": "nba", "source": "nba_official", "kind": "official", "team": team, "player_id": None,
                                 "player": c[4], "position": None, "source_player_id": None, "status": S.canonical(c[5]),
                                 "raw_status": c[5], "detail": c[6] or None, "comment": None,
                                 "report_time": pd.Timestamp(report_time).tz_convert("UTC"), "fetched_at": pd.Timestamp(fetched_at),
                                 "game_date": str(date) if date else None, "restriction": rmin[0], "restriction_minutes": rmin[1],
                                 "returning": False, "long_term": False, "game_time_et": gtime, "matchup": matchup})
    seen = {}
    for f in filings:
        seen[(f["game_date"], f["team"])] = f
    return pd.DataFrame(rows, columns=S.COLUMNS + ["game_time_et", "matchup"]), [{**f, "game_date": str(f["game_date"])} for f in seen.values()]


def fetch(now: datetime | None = None, opener=None) -> dict:
    got = latest_pdf(now, opener)
    if got is None:
        raise RuntimeError("NBA official injury report: no report found in the last 36 hours")
    b, url, t = got
    rows, filings = parse(b, t)
    return {"rows": rows, "filings": filings, "url": url, "report_time": pd.Timestamp(t).tz_convert("UTC"), "pdf": b}
