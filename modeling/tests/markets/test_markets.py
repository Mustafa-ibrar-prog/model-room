"""Market-data adapters, matching and comparison. Fixtures have the live API structure (recorded
2026-11-02) with synthetic prices; no network is used."""
from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from modelroom.markets import compare as C
from modelroom.markets import config, kalshi, manual, matching, polymarket_us
from modelroom.markets.http import JsonClient, ProviderError
from modelroom.markets.schema import PropQuote

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def pm_event():
    return json.loads((FIX / "polymarket_us_event_nfl.json").read_text())["event"]


@pytest.fixture
def kx():
    return json.loads((FIX / "kalshi_events_nfl.json").read_text())


# ------------------------------------------------------------------ Polymarket US
def test_polymarket_parses_player_thresholds(pm_event):
    qs = polymarket_us.parse_event(pm_event, "nfl")
    kinds = {q.market for q in qs}
    assert {"receiving_yards", "receptions", "anytime_td", "passing_yards", "fantasy_points", "longest_reception"} <= kinds
    # Team-level and first-TD markets are not player thresholds the model prices.
    assert all(q.market != "first_td" for q in qs)
    q = next(q for q in qs if q.market == "receiving_yards")
    assert q.op == ">=" and q.threshold > 0 and q.player_name
    assert q.team in ("CHI", "SEA") and {q.home_team, q.away_team} == {"CHI", "SEA"}
    assert q.game_date == "2026-11-02"
    assert q.fee_rate is not None and q.void_rule
    fp = next(q for q in qs if q.market == "fantasy_points")
    assert fp.variant == "espn_ppr"


def test_polymarket_slugs_try_both_orders_and_code_variants():
    s = polymarket_us.candidate_slugs("nfl", "LA", "SEA", "2026-11-08")
    assert "nfl-lar-sea-2026-11-08" in s and "nfl-sea-la-2026-11-08" in s


def test_polymarket_missing_side_stays_missing(pm_event):
    ev = json.loads(json.dumps(pm_event))
    m = next(m for m in ev["markets"] if m["sportsMarketType"] == "football_player_receptions")
    m["bestBidQuote"] = {"value": "0.0000", "currency": "USD"}
    q = next(q for q in polymarket_us.parse_event(ev, "nfl") if q.provider_market_id == m["slug"])
    assert q.yes_bid is None and q.no_ask is None and q.yes_ask is not None


# ------------------------------------------------------------------ Kalshi
def test_kalshi_parses_strikes_and_skips_protected(kx):
    qs = kalshi.parse_events("KXNFLRECYDS", kx["KXNFLRECYDS"], "nfl")
    assert qs and all(q.market == "receiving_yards" and q.op == ">" for q in qs)
    q = qs[0]
    assert q.threshold == 49.5 or q.threshold % 1 == 0.5
    assert q.game_date == "2026-11-02" and {q.home_team, q.away_team} == {"CHI", "SEA"}
    assert q.sportradar_player_id and q.team in ("CHI", "SEA")
    assert q.yes_bid_size is not None
    assert kalshi.parse_events("KXNFLTDPROT", kx["KXNFLTDPROT"], "nfl") == []


def test_kalshi_fantasy_is_a_different_contract(kx):
    qs = kalshi.parse_events("KXNFLFFPTS", kx["KXNFLFFPTS"], "nfl")
    assert qs and all(q.variant == "sleeper_ppr" and "scores 0" in q.void_rule for q in qs)


def test_kalshi_team_codes():
    assert kalshi.parse_event_ticker("KXNFLREC-26NOV05JACBAL", "JAC vs BAL (Nov 5)") == ("2026-11-05", "JAX", "BAL")
    assert kalshi.parse_event_ticker("KXNFLREC-26NOV08LARWAS", "LAR vs WAS (Nov 8)")[1] == "LA"
    assert kalshi.parse_event_ticker("KXNBAPTS-26NOV02PHXGSW", "PHX vs GSW (Nov 2)", "nba") == ("2026-11-02", "PHX", "GS")


# ------------------------------------------------------------------ manual CSV
def test_manual_csv_validates(tmp_path):
    f = tmp_path / "nfl_props.csv"
    f.write_text(
        "source,game_date,home_team,away_team,team,player,market,op,threshold,yes_bid,yes_ask,over_odds,under_odds,captured_at,note\n"
        "BookA,2026-11-08,SEA,ARI,SEA,Jaxon Smith-Njigba,receiving_yards,>,74.5,,,-115,-105,2026-11-07T10:00:00-08:00,\n"
        "BookA,2026-11-08,SEA,ARI,SEA,Jaxon Smith-Njigba,receiving_yards,>,74.5,,,,,2026-11-07T10:00:00-08:00,no price\n"
        "BookA,2026-11-08,SEA,ARI,SEA,Jaxon Smith-Njigba,receiving_yards,>,74.5,,,-115,-105,2026-11-07 10:00,no tz\n"
        "BookA,2026-11-08,SEA,ARI,SEA,Jaxon Smith-Njigba,yards_per_route,>,1.5,,,-115,-105,2026-11-07T10:00:00-08:00,\n"
    )
    qs, problems = manual.load("nfl", f)
    assert len(qs) == 1 and len(problems) == 3
    q = qs[0]
    assert q.yes_ask == pytest.approx(115 / 215) and q.no_ask == pytest.approx(105 / 205)
    assert q.yes_bid is None  # never invented


# ------------------------------------------------------------------ matching
def test_matching_prefers_sportradar_then_name():
    games = pd.DataFrame([{"game_id": "2026_08_CHI_SEA", "game_date": "2026-11-02", "home_team": "SEA", "away_team": "CHI"}])
    players = pd.DataFrame([
        {"game_id": "2026_08_CHI_SEA", "player_id": "00-1", "name": "Jaxon Smith-Njigba", "team": "SEA", "sportradar_id": "sr-1"},
        {"game_id": "2026_08_CHI_SEA", "player_id": "00-2", "name": "Luther Burden III", "team": "CHI", "sportradar_id": None},
    ])
    q1 = PropQuote("kalshi", "nfl", "receptions", ">", 4.5, "J. Smith-Njigba", "SEA", "2026-11-02", "SEA", "CHI", sportradar_player_id="sr-1")
    q2 = PropQuote("polymarket_us", "nfl", "receptions", ">=", 3, "Luther Burden", "CHI", "2026-11-02", "SEA", "CHI")
    q3 = PropQuote("polymarket_us", "nfl", "receptions", ">=", 3, "Somebody Else", "CHI", "2026-11-02", "SEA", "CHI")
    q4 = PropQuote("polymarket_us", "nfl", "receptions", ">=", 3, "Luther Burden", "CHI", "2026-11-09", "SEA", "CHI")
    qs = [q1, q2, q3, q4]
    matching.match_games(qs, games)
    matching.match_players(qs, players)
    assert q1.player_id == "00-1" and "sportradar" in q1.match_note
    assert q2.player_id == "00-2"
    assert q3.player_id is None and q4.game_id is None


# ------------------------------------------------------------------ comparison
def _q(**kw):
    base = dict(provider="kalshi", league="nfl", market="receptions", op=">", threshold=4.5, player_name="X", team="SEA",
                game_date="2026-11-02", yes_bid=0.50, yes_ask=0.52, no_bid=0.48, no_ask=0.50, fee_rate=0.07,
                yes_ask_size=500.0, status="active", captured_at=(NOW - timedelta(minutes=5)).isoformat(), player_id="00-1")
    base.update(kw)
    return PropQuote(**base)


def test_ev_is_after_fees_from_the_ask():
    v = C.view(_q(), 0.60, NOW)
    assert v.usable
    assert v.ev_yes == pytest.approx(0.60 - 0.52 - 0.07 * 0.52 * 0.48, abs=1e-4)
    assert v.ev_no == pytest.approx(0.40 - 0.50 - 0.07 * 0.25, abs=1e-4)


@pytest.mark.parametrize("kw,flag", [
    ({"captured_at": (NOW - timedelta(hours=3)).isoformat()}, "stale"),
    ({"yes_bid": None}, "one-sided"),
    ({"yes_ask": 0.70}, "wide spread"),
    ({"yes_ask_size": 10.0}, "thin at ask"),
    ({"player_id": None}, "player not matched"),
    ({"void_rule": "did not play: scores 0"}, "pays 0 if inactive; model assumes he plays"),
])
def test_unusable_quotes_never_produce_an_edge(kw, flag):
    v = C.view(_q(**kw), 0.90, NOW)
    assert not v.usable and flag in v.flags
    assert C.best([v])["edge"] is None


def test_best_price_across_providers():
    a = C.view(_q(provider="kalshi", yes_ask=0.55, yes_bid=0.53), 0.65, NOW)
    b = C.view(_q(provider="polymarket_us", yes_ask=0.52, yes_bid=0.50, fee_rate=0.0695), 0.65, NOW)
    best = C.best([a, b])
    assert best["yes"]["provider"] == "polymarket_us" and best["edge"] == "yes"


# ------------------------------------------------------------------ controls and HTTP
def test_providers_are_off_by_default_and_in_production(monkeypatch):
    for k in ("MODELROOM_MARKETS_POLYMARKET_US", "MODELROOM_MARKETS_KALSHI", "MODELROOM_ENV", "MODELROOM_MARKETS_REDISTRIBUTION_OK", "MODELROOM_MARKETS_KALSHI_PUBLISH"):
        monkeypatch.delenv(k, raising=False)
    assert config.enabled_providers() == []
    monkeypatch.setenv("MODELROOM_MARKETS_POLYMARKET_US", "on")
    monkeypatch.setenv("MODELROOM_MARKETS_KALSHI", "on")
    assert config.status("polymarket_us").publishable
    k = config.status("kalshi")
    assert k.enabled and not k.publishable
    monkeypatch.setenv("MODELROOM_ENV", "production")
    assert config.enabled_providers() == []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_client_caches_retries_and_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def opener(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "slow down", {"Retry-After": "1"}, None)
        return _Resp(b'{"ok": true}')

    c = JsonClient("https://example.test", name="t", min_interval_s=0, cache_dir=tmp_path, opener=opener)
    assert c.get("/x") == {"ok": True} and calls["n"] == 2
    assert c.get("/x") == {"ok": True} and calls["n"] == 2 and c.cache_hits == 1

    def broken(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "down", {}, None)

    d = JsonClient("https://example.test", name="t", min_interval_s=0, cache_dir=None, retries=1, opener=broken)
    with pytest.raises(ProviderError):
        d.get("/y")
    assert d.failures


def test_nba_adapters_map_teams_and_markets():
    ev = json.loads((FIX / "polymarket_us_event_nba.json").read_text())["event"]
    qs = polymarket_us.parse_event(ev, "nba")
    assert {"points", "rebounds", "assists", "pra", "threes", "steals", "blocks"} <= {q.market for q in qs}
    assert {q.team for q in qs} <= {"OKC", "CLE"} and all(q.op == ">=" for q in qs)
    kx = json.loads((FIX / "kalshi_events_nba.json").read_text())
    ks = kalshi.parse_events("KXNBAPTS", kx["KXNBAPTS"], "nba")
    assert ks and all(q.market == "points" and q.op == ">" and q.team in ("OKC", "CLE") for q in ks)
    assert all(q.sportradar_player_id for q in ks)
