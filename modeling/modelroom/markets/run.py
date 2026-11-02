"""Fetch market data from every enabled provider and store a snapshot. Independent of the engines.

    python -m modelroom markets fetch nfl [--provider polymarket_us|kalshi|all] [--days 10]
    python -m modelroom markets status
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from modelroom.common.paths import data_root, processed_dir

from . import config, kalshi, polymarket_us, snapshots
from .http import ProviderError

ADAPTERS = {"polymarket_us": polymarket_us, "kalshi": kalshi}


def upcoming_games(league: str, days: int) -> pd.DataFrame:
    if league == "nfl":
        g = pd.read_parquet(processed_dir("nfl") / "games.parquet")
    else:
        g = pd.read_parquet(processed_dir("nba") / "games.parquet").rename(columns={"home_abbr": "home_team", "away_abbr": "away_team"})
        g["game_id"] = g["game_id"].astype(str)
    g = g[g["status"] == "scheduled"].copy()
    st = pd.to_datetime(g["start_time"], utc=True)
    now = datetime.now(timezone.utc)
    g = g[(st > now) & (st <= now + timedelta(days=days))]
    g["game_date"] = g["game_date"].astype(str)
    return g


def fetch(league: str, providers: list[str] | None = None, days: int = 10, log=print) -> dict:
    wanted = providers or config.PROVIDERS
    games = upcoming_games(league, days)
    report: dict = {"league": league, "games": int(len(games)), "providers": {}}
    for name in wanted:
        st = config.status(name)
        if not st.enabled:
            report["providers"][name] = {"skipped": st.reason}
            continue
        cache = data_root() / "markets" / "cache" / name
        try:
            quotes, stats = ADAPTERS[name].fetch(league, games, cache, log=log)
        except ProviderError as e:  # one provider failing never blocks the others
            report["providers"][name] = {"error": str(e)}
            continue
        stats["stored"] = snapshots.append(quotes, league).get(name, 0)
        stats["publishable"] = st.publishable
        report["providers"][name] = stats
    return report


def provider_status() -> list[dict]:
    return [config.status(p).__dict__ for p in config.PROVIDERS]


def depth(league: str, max_requests: int = 60, log=print) -> dict:
    """Fetch order-book depth for Polymarket US contracts the latest props run flagged as an edge.

    Polymarket's market listing has no sizes, so without this its edges can never be "strong". Each book
    is one request (2 s apart), so only flagged contracts are fetched, at most max_requests per run.
    The result is stored as a new snapshot of that contract (fresh bid/ask with sizes)."""
    from . import evaluation
    from .schema import PropQuote

    st = config.status("polymarket_us")
    if not st.enabled:
        return {"skipped": st.reason}
    ev = evaluation._load(league)
    if ev.empty:
        return {"contracts": 0, "note": "no evaluated contracts yet; run markets fetch, then the props run"}
    latest = ev[ev["generated_at"] == ev["generated_at"].max()]
    want = latest[(latest["provider"] == "polymarket_us") & latest["grade"].isin(["lean", "strong"])]
    want = want.drop_duplicates("market_id").head(max_requests)
    snap = snapshots.latest(league, "polymarket_us")
    by_id = {r["provider_market_id"]: r for r in snap.to_dict("records")} if len(snap) else {}
    c = polymarket_us.client(data_root() / "markets" / "cache" / "polymarket_us_books")
    c.cache_ttl_s = 0  # depth must be fresh
    out, errors = [], []
    for mid in want["market_id"]:
        base = by_id.get(mid)
        if base is None:
            continue
        try:
            b = polymarket_us.book(c, mid)
        except ProviderError as e:
            errors.append(str(e))
            continue
        q = PropQuote(**{k: (None if isinstance(v, float) and v != v else v) for k, v in base.items() if k in PropQuote.__dataclass_fields__})
        q.yes_bid, q.yes_ask = b["yes_bid"], b["yes_ask"]
        q.no_bid = 1 - b["yes_ask"] if b["yes_ask"] is not None else None
        q.no_ask = 1 - b["yes_bid"] if b["yes_bid"] is not None else None
        q.yes_bid_size, q.yes_ask_size = b["yes_bid_size"], b["yes_ask_size"]
        q.quote_time = b.get("transact_time") or q.quote_time
        q.captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        q.game_id = q.player_id = q.match_note = None
        out.append(q)
    snapshots.append(out, league)
    return {"flagged": int(len(want)), "books_fetched": len(out), "requests": c.calls, "errors": errors}


def refresh(league: str, days: int = 10, log=print) -> dict:
    """The whole local market loop: prices → props → depth for flagged contracts → props again."""
    if league == "nfl":
        from modelroom.nfl.props import pipeline as props
    else:
        from modelroom.nba.props import pipeline as props
    report = {"fetch": fetch(league, days=days, log=log)}
    report["props"] = props.run()
    report["depth"] = depth(league, log=log)
    if report["depth"].get("books_fetched"):
        report["props_after_depth"] = props.run()
    return report
