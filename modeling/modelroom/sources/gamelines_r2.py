"""Per-sportsbook game lines for the TEST Parlay Builder, to private R2 (Moose 2026-11-27). No API call, no credits.

The 7:00 AM and 12:00 PM game-line fetches (sources/odds.py) already return every US book's spread, total and
moneyline; until now only the cross-book consensus reached the site. After a refresh, this reads the working copy
(data/processed/<league>/market_snapshots.parquet, rebuilt from the private odds store) and writes, for games that
haven't started, each book's latest line and prices to the private bucket:

    v1/market-snapshots/<league>/game-lines/<YYYY-MM-DD>/view-<ts>.json   write-once, read back and checked
    v1/market-snapshots/<league>/game-lines/latest.json                   pointer (the only object replaced)

Nothing goes into the public repository; the log prints counts only.

    python -m modelroom.sources.gamelines_r2 [--league nba,nfl] [--local DIR]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from modelroom.archive import market_snapshots as MS
from modelroom.common.paths import processed_dir

PT = ZoneInfo("America/Los_Angeles")
TITLES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars", "caesars": "Caesars",
          "espnbet": "ESPN BET", "betrivers": "BetRivers", "fanatics": "Fanatics", "bovada": "Bovada", "betonlineag": "BetOnline.ag",
          "mybookieag": "MyBookie.ag", "lowvig": "LowVig.ag", "betus": "BetUS", "ballybet": "Bally Bet", "hardrockbet": "Hard Rock Bet",
          "fliff": "Fliff", "unibet_us": "Unibet", "pointsbetus": "PointsBet", "superbook": "SuperBook", "wynnbet": "WynnBET",
          "betparx": "betPARX", "espnbet_us": "ESPN BET"}


def prefix(league: str) -> str:
    return f"v1/market-snapshots/{league}/game-lines"


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def _price(v):
    return None if v is None or pd.isna(v) else int(round(float(v)))


def build_view(df: pd.DataFrame, league: str, now: datetime) -> dict:
    """Each book's newest line per game and market, for games that haven't started. Pure (unit-tested)."""
    out = {"league": league, "generated_at": now.isoformat(timespec="seconds"), "source": "the_odds_api", "games": {}}
    if df is None or df.empty:
        return out
    d = df[df["game_id"].notna() & (df["source"] == "the_odds_api")].copy()
    d["start"] = pd.to_datetime(d["commence_time"], utc=True, errors="coerce")
    d = d[d["start"] > now]
    if d.empty:
        return out
    d["_c"] = pd.to_datetime(d["collected_at"], utc=True, errors="coerce")
    d["_u"] = pd.to_datetime(d["captured_at"], utc=True, errors="coerce")
    d = d.sort_values(["_c", "_u"], na_position="first").groupby(["game_id", "market", "sportsbook"]).tail(1)
    for gid, g in d.groupby("game_id"):
        first = g.iloc[0]
        books: dict = {}
        for r in g.itertuples(index=False):
            b = books.setdefault(r.sportsbook, {"title": TITLES.get(r.sportsbook, str(r.sportsbook).replace("_", " ").title())})
            upd = r.captured_at if isinstance(r.captured_at, str) else (None if pd.isna(r.captured_at) else str(r.captured_at))
            if r.market == "spread" and _num(r.line) is not None:
                b["spread"] = {"line": _num(r.line), "home": _price(r.home_price), "away": _price(r.away_price), "last_update": upd}
            elif r.market == "total" and _num(r.line) is not None:
                b["total"] = {"line": _num(r.line), "over": _price(r.over_price), "under": _price(r.under_price), "last_update": upd}
            elif r.market == "moneyline":
                b["moneyline"] = {"home": _price(r.home_price), "away": _price(r.away_price), "last_update": upd}
        out["games"][str(gid)] = {"commence_time": str(first.commence_time), "home_team": first.home_team, "away_team": first.away_team,
                                  "collected_at": None if pd.isna(g["_c"].max()) else g["_c"].max().isoformat(), "books": books}
    return out


def publish(store, reader, league: str, view: dict, now: datetime) -> dict:
    body = json.dumps(view, sort_keys=True, separators=(",", ":")).encode()
    day = now.astimezone(PT).date().isoformat()
    key = f"{prefix(league)}/{day}/view-{MS.stamp(now)}.json"
    put = MS.put_verified(store, reader, key, body)
    pointer = {"view": key, "view_sha256": put["sha256"], "updated_at": view["generated_at"]}
    store.put(f"{prefix(league)}/latest.json", json.dumps(pointer, sort_keys=True).encode())
    if json.loads(reader.get(f"{prefix(league)}/latest.json")) != pointer:
        raise MS.ArchiveError("latest.json read-back differs")
    return {"games": len(view["games"]), "books": len({b for g in view["games"].values() for b in g["books"]}), "bytes": len(body)}


def main(argv=None) -> int:
    from modelroom.archive.store import from_env, reader_from_env
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="nba,nfl")
    ap.add_argument("--local", default=None)
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    store, reader = from_env(a.local), reader_from_env(a.local)
    rc = 0
    for lg in a.league.split(","):
        f = processed_dir(lg) / "market_snapshots.parquet"
        if not f.exists():
            print(json.dumps({"league": lg, "skipped": "no game-line working copy in this run"}))
            continue
        try:
            v = build_view(pd.read_parquet(f), lg, now)
            print(json.dumps({"league": lg, **publish(store, reader, lg, v, now)}))
        except Exception as e:  # noqa: BLE001  counts and the error type only
            print(json.dumps({"league": lg, "error": type(e).__name__}))
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
