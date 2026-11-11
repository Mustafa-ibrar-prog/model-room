"""Sportsbook lines: optional The Odds API collector and manual CSV entry.

Every line keeps its sportsbook, market, timestamp and source. Missing lines
stay missing. Nothing here invents or fills a line.

Normalized columns (processed/<league>/market_snapshots.parquet):
  league, game_id, home_team, away_team, commence_time, sportsbook, market,
  line, home_price, away_price, over_price, under_price, captured_at, source, collected_at
Spreads use the home team's line (negative = home favored).

captured_at   when the sportsbook last changed that line (The Odds API's last_update), as published.
collected_at  when Model Room fetched it (UTC). The same unchanged line seen at two collections is kept twice,
              so a later market check can tell which lines were live at a given moment. Rows stored before this
              column existed, and manual CSV rows, have no collected_at (left empty, never back-filled).
raw_sha256    SHA-256 of the provider response the row was parsed from (collector rows only).
On the test site the permanent record is the append-only Supabase table odds.snapshots (see odds_store.py);
the parquet file is a working copy rebuilt from it at the start of each refresh.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common.paths import data_root, ensure, processed_dir, raw_dir

from . import state

ODDS_API = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
SPORT_KEYS = {"nba": "basketball_nba", "nfl": "americanfootball_nfl"}
MARKETS = ("spread", "total", "moneyline")
COLUMNS = ["league", "game_id", "home_team", "away_team", "commence_time", "sportsbook", "market", "line",
           "home_price", "away_price", "over_price", "under_price", "captured_at", "source", "collected_at"]
MANUAL_COLUMNS = ["game_date", "home_team", "away_team", "sportsbook", "market", "line", "home_price",
                  "away_price", "over_price", "under_price", "captured_at", "entered_by", "note"]

NFL_TEAMS = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
NBA_NAME_ALIASES = {"Los Angeles Clippers": "LA Clippers"}  # Odds API name -> hoopR display name


class LinesError(ValueError):
    pass


def _american(p) -> bool:
    return pd.isna(p) or float(p) <= -100 or float(p) >= 100


# ---------------------------------------------------------------- The Odds API
def parse_odds_api(events: list[dict], league: str, collected_at: str | None = None) -> pd.DataFrame:
    """Normalize a /v4/sports/{sport}/odds response (markets spreads, totals, h2h; American odds)."""
    rows = []
    for ev in events:
        home, away = ev["home_team"], ev["away_team"]
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                outcomes = {o["name"]: o for o in mk.get("outcomes", [])}
                captured = mk.get("last_update") or bm.get("last_update")
                base = {"league": league, "game_id": None, "home_team": home, "away_team": away,
                        "commence_time": ev["commence_time"], "sportsbook": bm["key"], "captured_at": captured,
                        "source": "the_odds_api", "collected_at": collected_at, "home_price": np.nan, "away_price": np.nan,
                        "over_price": np.nan, "under_price": np.nan, "line": np.nan}
                if mk["key"] == "spreads" and home in outcomes and away in outcomes:
                    rows.append({**base, "market": "spread", "line": outcomes[home].get("point"),
                                 "home_price": outcomes[home].get("price"), "away_price": outcomes[away].get("price")})
                elif mk["key"] == "totals" and "Over" in outcomes and "Under" in outcomes:
                    rows.append({**base, "market": "total", "line": outcomes["Over"].get("point"),
                                 "over_price": outcomes["Over"].get("price"), "under_price": outcomes["Under"].get("price")})
                elif mk["key"] == "h2h" and home in outcomes and away in outcomes:
                    rows.append({**base, "market": "moneyline",
                                 "home_price": outcomes[home].get("price"), "away_price": outcomes[away].get("price")})
    return pd.DataFrame(rows, columns=COLUMNS)


# Free tier: 500 credits a month, 3 per league call (us region x 3 markets). Every call is logged (no key, no URL) to
# an append-only file kept with the ledgers, so the remaining-credit count survives between workflow runs.
MIN_CREDITS = int(os.environ.get("MODELROOM_ODDS_MIN_CREDITS", "15"))


def usage_log_path() -> Path:
    d = os.environ.get("MODELROOM_LEDGER_DIR")
    return Path(d) / "odds_api_usage.jsonl" if d else data_root() / "raw" / "odds_api_usage.jsonl"


def last_usage() -> dict | None:
    p = usage_log_path()
    if not p.exists():
        return None
    lines = [l for l in p.read_text().splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def credit_guard(now: datetime | None = None) -> str | None:
    """A reason to skip the call, or None. Skips when the last call this calendar month (UTC) left fewer than
    MIN_CREDITS. (The provider's exact reset day isn't documented to us; a new month re-allows one call, whose
    response header then reports the real count.) MODELROOM_ODDS_FORCE=1 overrides."""
    if os.environ.get("MODELROOM_ODDS_FORCE") == "1":
        return None
    u = last_usage()
    if not u or u.get("remaining") is None:
        return None
    now = now or datetime.now(timezone.utc)
    at = pd.Timestamp(u["at"])
    if (at.year, at.month) != (now.year, now.month):
        return None
    if int(float(u["remaining"])) < MIN_CREDITS:
        return f"only {u['remaining']} Odds API credits left this month (minimum {MIN_CREDITS}); call skipped"
    return None


def _log_usage(row: dict) -> None:
    p = usage_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def collect_odds_api(league: str, api_key: str | None = None) -> pd.DataFrame:
    key = api_key or os.environ.get("ODDS_API_KEY")
    if not key:
        raise LinesError("ODDS_API_KEY is not set. It's optional: without it, lines come from nflverse (NFL) "
                         "or data/manual/<league>_lines.csv.")
    why = credit_guard()
    if why:
        state.record_failure("the_odds_api", why)
        raise LinesError(why)
    url = (ODDS_API.format(sport=SPORT_KEYS[league]) +
           f"?apiKey={key}&regions=us&markets=spreads,totals,h2h&oddsFormat=american&dateFormat=iso")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ModelRoom/0.1"}), timeout=60) as r:
        body = r.read()
        remaining = r.headers.get("x-requests-remaining")
        used = r.headers.get("x-requests-used")
        last_cost = r.headers.get("x-requests-last")
    now = datetime.now(timezone.utc)
    collected = now.isoformat(timespec="seconds")
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    raw = ensure(raw_dir(league) / "odds_api") / f"odds_{stamp}.json"
    raw.write_bytes(body)  # the key is not in the response; never store the request URL
    df = parse_odds_api(json.loads(body), league, collected_at=collected)
    # Provenance: fingerprint of the exact provider response these rows came from (kept with each stored row).
    df["raw_sha256"] = hashlib.sha256(body).hexdigest()
    _log_usage({"at": collected, "league": league, "rows": len(df), "remaining": remaining, "used": used, "cost": last_cost})
    state.record("the_odds_api", league=league, rows=len(df), credits_remaining=remaining)
    return df


# ---------------------------------------------------------------- manual CSV
def manual_path(league: str) -> Path:
    return data_root() / "manual" / f"{league}_lines.csv"


def validate_manual(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return (valid rows, list of problems). Invalid rows are dropped, never repaired."""
    problems, keep = [], []
    missing_cols = [c for c in MANUAL_COLUMNS if c not in df.columns]
    if missing_cols:
        raise LinesError(f"Manual lines file is missing columns: {missing_cols}")
    for i, r in df.iterrows():
        n = i + 2  # spreadsheet row number (header is row 1)
        errs = []
        for c in ("game_date", "home_team", "away_team", "sportsbook", "market", "captured_at"):
            if pd.isna(r[c]) or str(r[c]).strip() == "":
                errs.append(f"{c} is required")
        if str(r["market"]) not in MARKETS:
            errs.append(f"market must be one of {MARKETS}")
        try:
            ts = pd.Timestamp(str(r["captured_at"]))
            if ts.tzinfo is None:
                errs.append("captured_at needs a timezone, e.g. 2026-11-02T18:30:00-08:00")
        except (ValueError, TypeError):
            errs.append("captured_at is not a valid timestamp")
        if r["market"] in ("spread", "total") and pd.isna(r["line"]):
            errs.append("line is required for spread and total")
        if r["market"] == "total" and pd.notna(r["line"]) and float(r["line"]) <= 0:
            errs.append("total line must be positive")
        for c in ("home_price", "away_price", "over_price", "under_price"):
            if not _american(r[c]):
                errs.append(f"{c} must be American odds (<= -100 or >= +100)")
        if errs:
            problems.append(f"row {n}: " + "; ".join(errs))
        else:
            keep.append(i)
    return df.loc[keep], problems


def load_manual(league: str) -> tuple[pd.DataFrame, list[str]]:
    path = manual_path(league)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS), []
    df = pd.read_csv(path)
    valid, problems = validate_manual(df)
    out = pd.DataFrame(
        {
            "league": league, "game_id": None, "home_team": valid["home_team"], "away_team": valid["away_team"],
            "commence_time": valid["game_date"], "sportsbook": valid["sportsbook"], "market": valid["market"],
            "line": pd.to_numeric(valid["line"], errors="coerce"),
            "home_price": pd.to_numeric(valid["home_price"], errors="coerce"),
            "away_price": pd.to_numeric(valid["away_price"], errors="coerce"),
            "over_price": pd.to_numeric(valid["over_price"], errors="coerce"),
            "under_price": pd.to_numeric(valid["under_price"], errors="coerce"),
            "captured_at": valid["captured_at"], "source": "manual_lines",
        },
        columns=COLUMNS,
    )
    if len(out):
        state.record("manual_lines", league=league, rows=len(out), rejected=len(problems))
    return out, problems


# ---------------------------------------------------------------- matching
def match_games(lines: pd.DataFrame, games: pd.DataFrame, league: str) -> pd.DataFrame:
    """Attach game_id by date (US Eastern) + teams. Unmatched lines keep game_id = None."""
    if lines.empty:
        return lines
    l = lines.copy()
    if league == "nfl":
        l["home_key"] = l["home_team"].map(NFL_TEAMS).fillna(l["home_team"])
        l["away_key"] = l["away_team"].map(NFL_TEAMS).fillna(l["away_team"])
        g = games.assign(home_key=games["home_team"], away_key=games["away_team"])
    else:
        l["home_key"] = l["home_team"].replace(NBA_NAME_ALIASES)
        l["away_key"] = l["away_team"].replace(NBA_NAME_ALIASES)
        g = games.assign(home_key=games["home_name"], away_key=games["away_name"])
        # Manual entries may use abbreviations instead of names.
        abbr = dict(zip(games["home_abbr"], games["home_name"]))
        l["home_key"] = l["home_key"].map(lambda v: abbr.get(v, v))
        l["away_key"] = l["away_key"].map(lambda v: abbr.get(v, v))
    ct = pd.to_datetime(l["commence_time"], utc=True, errors="coerce")
    l["game_date"] = ct.dt.tz_convert("America/New_York").dt.date.where(ct.notna(), pd.to_datetime(l["commence_time"], errors="coerce").dt.date)
    g = g[["game_id", "game_date", "home_key", "away_key"]].rename(columns={"game_id": "matched_id"})
    m = l.merge(g, on=["game_date", "home_key", "away_key"], how="left")
    m["game_id"] = m["matched_id"]
    return m[COLUMNS]


def consensus(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Per game x market: latest line from each book, then the median across books."""
    s = snapshots.dropna(subset=["game_id"]).copy()
    if s.empty:
        return pd.DataFrame(columns=["game_id", "market", "line", "books", "captured_at", "sources"])
    s["captured_ts"] = pd.to_datetime(s["captured_at"], utc=True, errors="coerce")
    latest = s.sort_values("captured_ts").groupby(["game_id", "market", "sportsbook"], dropna=False).tail(1)
    agg = latest.groupby(["game_id", "market"]).agg(
        line=("line", "median"), books=("sportsbook", "nunique"),
        captured_at=("captured_ts", "max"), sources=("source", lambda x: ",".join(sorted(set(x)))),
    ).reset_index()
    return agg


def store(league: str, new: pd.DataFrame) -> pd.DataFrame:
    """Append snapshots (never rewrites a stored row), de-duplicated on (source, book, game, market, captured_at,
    collected_at). Re-running the same collection is a no-op; a later collection of an unchanged line is a new row."""
    f = ensure(processed_dir(league)) / "market_snapshots.parquet"
    old = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=COLUMNS)
    if "collected_at" not in old.columns:
        old["collected_at"] = None  # rows from before collection time was kept: left empty, never guessed
    new = new.copy()
    if "collected_at" not in new.columns:
        new["collected_at"] = None
    both = pd.concat([old, new], ignore_index=True)
    key = ["source", "sportsbook", "home_team", "away_team", "commence_time", "market", "captured_at", "collected_at"]
    both = both.drop_duplicates(key, keep="first")
    both.to_parquet(f, index=False)
    return both
