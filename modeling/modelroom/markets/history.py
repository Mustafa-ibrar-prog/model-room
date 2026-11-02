"""Historical exchange prices, so ROI and closing-line value can be measured on games already played.

Kalshi publishes hourly candlesticks (bid / ask open-high-low-close) for settled markets:
  GET /events?series_ticker=…&status=settled&with_nested_markets=true
  GET /series/{series}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval=60

`backfill_kalshi` stores each hourly close as a snapshot (captured_at = the candle's end), local only.
`replay` then prices those contracts with the model exactly as it would have run before each game
(walk-forward: only games before that day / week), using the price from at least ENTRY_LEAD_HOURS
before kickoff as the entry, and writes evaluation rows. `evaluation.report` settles them.

Polymarket US has no working public price-history query (checked 2026-11-02: /v1/price-history returns
400 for every parameter tried), so Polymarket history comes only from snapshots taken going forward.

Kalshi terms: storing data is limited to facilitating your own trading (Developer Agreement §3.1).
Everything here stays in data/markets on this machine; nothing is published.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from modelroom.common.paths import data_root

from . import config, kalshi, snapshots
from .http import ProviderError
from .schema import price, to_float

ENTRY_LEAD_HOURS = 3.0


def candles_to_quotes(series: str, market: dict, event: dict, candles: list[dict], league: str) -> list:
    """Each hourly candle → a quote snapshot at the candle's end."""
    base = kalshi.parse_events(series, {"events": [{**event, "markets": [market]}]}, league)
    if not base:
        return []
    q0 = base[0]
    out = []
    for c in candles:
        ts = c.get("end_period_ts")
        if ts is None:
            continue
        bid = price((c.get("yes_bid") or {}).get("close_dollars"))
        ask = price((c.get("yes_ask") or {}).get("close_dollars"))
        q = type(q0)(**{**q0.to_dict()})
        q.yes_bid, q.yes_ask = bid, ask
        q.no_bid = 1 - ask if ask is not None else None
        q.no_ask = 1 - bid if bid is not None else None
        q.yes_bid_size = q.yes_ask_size = None  # candles carry no book sizes
        q.volume = to_float(c.get("volume_fp"))
        q.status = "historical"
        q.start_time = market.get("occurrence_datetime") or market.get("expected_expiration_time")
        q.captured_at = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(timespec="seconds")
        q.game_id = q.player_id = q.match_note = None
        out.append(q)
    return out


def backfill_kalshi(league: str, days: int = 30, max_markets: int = 3000, log=print) -> dict:
    st = config.status("kalshi")
    if not st.enabled:
        return {"skipped": st.reason}
    c = kalshi.client(data_root() / "markets" / "cache" / "kalshi_history")
    c.cache_ttl_s = 365 * 86400  # settled history doesn't change
    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    stored, markets_done, errors = 0, 0, []
    for series in kalshi.SERIES[league]:
        cursor = None
        for _page in range(50):
            try:
                d = c.get("/events", {"series_ticker": series, "status": "settled", "with_nested_markets": "true", "limit": 100, "cursor": cursor})
            except ProviderError as e:
                errors.append(str(e))
                break
            evs = (d or {}).get("events") or []
            older = False
            for ev in evs:
                gd, _, _ = kalshi.parse_event_ticker(ev.get("event_ticker", ""), ev.get("sub_title"), league)
                if gd is None or datetime.fromisoformat(gd).date() < since:
                    older = True
                    continue
                qs = []
                for m in ev.get("markets") or []:
                    if markets_done >= max_markets:
                        break
                    start = int(datetime.fromisoformat(m["open_time"].replace("Z", "+00:00")).timestamp()) if m.get("open_time") else None
                    end = int(datetime.fromisoformat((m.get("occurrence_datetime") or m["close_time"]).replace("Z", "+00:00")).timestamp())
                    try:
                        cd = c.get(f"/series/{series}/markets/{m['ticker']}/candlesticks",
                                   {"start_ts": start or end - 7 * 86400, "end_ts": end, "period_interval": 60})
                    except ProviderError as e:
                        errors.append(str(e))
                        continue
                    markets_done += 1
                    qs += candles_to_quotes(series, m, ev, (cd or {}).get("candlesticks") or [], league)
                stored += sum(snapshots.append(qs, league).values()) if qs else 0
            cursor = (d or {}).get("cursor")
            if not cursor or older or markets_done >= max_markets:
                break
    return {"markets": markets_done, "snapshots_stored": stored, "requests": c.calls, "errors": errors[:20]}


def entry_quotes(league: str, provider: str = "kalshi") -> pd.DataFrame:
    """For each contract, the last snapshot at least ENTRY_LEAD_HOURS before its start (the replay's entry price)."""
    df = snapshots.load(league, provider)
    if df.empty:
        return df
    st = pd.to_datetime(df["start_time"], utc=True, errors="coerce")
    ct = pd.to_datetime(df["captured_at"], utc=True, errors="coerce")
    df = df[st.notna() & (ct <= st - pd.Timedelta(hours=ENTRY_LEAD_HOURS))]
    return df.sort_values("captured_at").drop_duplicates(["provider", "provider_market_id"], keep="last")


def replay(league: str, provider: str = "kalshi", log=print) -> dict:
    """Price stored historical contracts with the walk-forward model and write evaluation rows."""
    from . import evaluation, matching
    from .schema import PropQuote

    ent = entry_quotes(league, provider)
    if ent.empty:
        return {"contracts": 0, "note": "no historical snapshots; run markets backfill first"}
    if league == "nfl":
        from modelroom.nfl.props import replay as R
    else:
        from modelroom.nba.props import replay as R
    quotes = [PropQuote(**{k: (None if isinstance(v, float) and v != v else v) for k, v in r.items() if k in PropQuote.__dataclass_fields__})
              for r in ent.to_dict("records")]
    for q in quotes:
        q.game_id = q.player_id = q.match_note = None
    sched = R.schedule()
    matching.match_games(quotes, sched)
    total, days = 0, 0
    for gid_date, qs in _by_date(quotes, sched).items():
        games = sched[sched["game_date"] == gid_date]
        projs, price_fn, support_fn, reliability, version = R.project(games)
        players = pd.DataFrame([{"game_id": x.game_id, "player_id": x.player_id, "name": x.name, "team": x.team,
                                 "sportradar_id": R.sportradar(x.player_id)} for x in projs])
        if players.empty:
            continue
        matching.match_players(qs, players)
        idx: dict = {}
        for q in qs:
            if q.player_id:
                idx.setdefault((q.game_id, q.player_id), []).append(q)
        starts = {g: s for g, s in zip(games["game_id"], games["start_iso"])}
        # The model "ran" when the entry price was seen; its inputs only include games before that day.
        for x in projs:
            for q in idx.get((x.game_id, x.player_id), []):
                got = price_fn(x, q)
                if got is None:
                    continue
                prob, stat = got
                ts = datetime.fromisoformat(q.captured_at)
                from . import compare as C

                v = C.view(q, prob, ts)
                g = C.grade(C.best([v]), support_fn(x, q.market), reliability.get(q.market))
                total += evaluation.record(league, [{**evaluation.row(q, prob, version + "+replay", q.captured_at, starts.get(x.game_id), g, stat)}])
        days += 1
    return {"game_days": days, "evaluated_contracts": total}


def _by_date(quotes, sched) -> dict:
    dates = dict(zip(sched["game_id"], sched["game_date"]))
    out: dict = {}
    for q in quotes:
        if q.game_id in dates:
            out.setdefault(dates[q.game_id], []).append(q)
    return out
