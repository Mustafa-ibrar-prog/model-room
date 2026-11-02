"""Land of Basketball monthly results pages: final scores for cross-checking.

Rules honored (robots.txt checked 2026-11-02): only /results/ pages, never
/box_scores or player pages, and at least 20 seconds between requests.
Data is used only to verify hoopR scores and is never republished.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from modelroom.common.download import fetch
from modelroom.common.paths import ensure, raw_dir

from . import state

BASE = "https://www.landofbasketball.com/results"
CRAWL_DELAY_S = 20.0
MONTHS = ["oct", "nov", "dec", "jan", "feb", "mar", "apr", "may", "jun"]

_TABLE = re.compile(r'<table class="color-alt">(.*?)</table>', re.S)
_DATE = re.compile(r"<h4[^>]*>\s*<a[^>]*>([^<]+)</a>", re.S)
_ROW = re.compile(r'<tr class="a-top">(.*?)</tr>', re.S)
_TEAM = re.compile(r'width:\s*180px;[^"]*">\s*([^<]+?)\s*</div>', re.S)
_SCORE = re.compile(r'<a href="[^"]*box_scores[^"]*">\s*(?:<b>)?\s*(\d+)', re.S)
_OT = re.compile(r"\b(\d?OT)\b")


def page_url(season: int, month: str) -> str:
    return f"{BASE}/{season - 1}_{season}_{month}_scores.htm"


def parse(page_html: str) -> list[list]:
    """Rows of [date, away_team, away_score, home_team, home_score, overtime]. Away is listed first."""
    rows = []
    for table in _TABLE.findall(page_html):
        m = _DATE.search(table)
        if not m:
            continue
        date = html.unescape(m.group(1)).strip()
        for row in _ROW.findall(table):
            teams = [html.unescape(t) for t in _TEAM.findall(row)]
            scores = [int(s) for s in _SCORE.findall(row)]
            if len(teams) == 2 and len(scores) == 2:
                text = re.sub(r"<[^>]+>", " ", row)
                ot = _OT.search(text)
                rows.append([date, teams[0], scores[0], teams[1], scores[1], ot.group(1) if ot else None])
    return rows


def collect(season: int, months: list[str] | None = None, *, delay: float = CRAWL_DELAY_S) -> Path:
    """Download and parse the season's monthly pages (run on a machine that can reach the site)."""
    out = ensure(raw_dir("nba"))
    all_rows: list[list] = []
    months = months or MONTHS
    for i, month in enumerate(months):
        if i:
            time.sleep(delay)
        dest = out / f"lob_{season}_{month}.htm"
        try:
            fetch(page_url(season, month), dest)
        except Exception:
            continue  # month not published yet
        all_rows += parse(dest.read_text(encoding="utf-8", errors="replace"))
    snap = out / f"lob_results_{season}.json"
    snap.write_text(json.dumps({
        "source": "land_of_basketball", "season": season,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "columns": ["date", "away_team", "away_score", "home_team", "home_score", "overtime"],
        "rows": all_rows,
    }, indent=1))
    state.record("land_of_basketball", season=season, games=len(all_rows))
    return snap


def load_snapshots() -> pd.DataFrame:
    frames = []
    for f in sorted(raw_dir("nba").glob("lob_results_*.json")):
        d = json.loads(f.read_text())
        df = pd.DataFrame(d["rows"], columns=d["columns"])
        df["snapshot"] = f.name
        df["retrieved_at"] = d.get("retrieved_at")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["game_date"] = pd.to_datetime(df["date"], format="%b %d, %Y").dt.date
    return df.drop_duplicates(["game_date", "away_team", "home_team"], keep="last")
