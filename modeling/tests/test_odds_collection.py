"""Sportsbook odds collection (The Odds API): collection time is kept, unchanged lines re-seen at a later
collection are new rows, stored rows are never rewritten, and the credit guard stops a call when credits are low."""
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from modelroom.sources import odds

EVENTS = [{
    "home_team": "Boston Celtics", "away_team": "New York Knicks", "commence_time": "2026-11-10T00:30:00Z",
    "bookmakers": [{"key": "draftkings", "last_update": "2026-11-09T15:00:00Z", "markets": [
        {"key": "spreads", "last_update": "2026-11-09T14:58:00Z", "outcomes": [
            {"name": "Boston Celtics", "price": -110, "point": -5.5}, {"name": "New York Knicks", "price": -110, "point": 5.5}]},
        {"key": "totals", "last_update": "2026-11-09T14:59:00Z", "outcomes": [
            {"name": "Over", "price": -108, "point": 221.5}, {"name": "Under", "price": -112, "point": 221.5}]},
        {"key": "h2h", "outcomes": [{"name": "Boston Celtics", "price": -230}, {"name": "New York Knicks", "price": 190}]},
    ]}],
}]


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setattr(odds, "processed_dir", lambda lg: tmp_path / "data" / "processed" / lg)
    return tmp_path


def test_parse_keeps_book_market_line_times():
    df = odds.parse_odds_api(EVENTS, "nba", collected_at="2026-11-09T15:00:05+00:00")
    assert list(df.columns) == odds.COLUMNS
    assert len(df) == 3
    sp = df[df.market == "spread"].iloc[0]
    assert (sp.sportsbook, sp.line, sp.home_price, sp.captured_at) == ("draftkings", -5.5, -110, "2026-11-09T14:58:00Z")
    assert (df.collected_at == "2026-11-09T15:00:05+00:00").all()
    ml = df[df.market == "moneyline"].iloc[0]
    assert ml.captured_at == "2026-11-09T15:00:00Z"  # falls back to the bookmaker's last_update


def test_store_appends_and_never_rewrites(tmp_data):
    a = odds.parse_odds_api(EVENTS, "nba", collected_at="2026-11-09T15:00:05+00:00")
    odds.store("nba", a)
    assert len(odds.store("nba", a)) == 3  # same collection again: no new rows
    b = odds.parse_odds_api(EVENTS, "nba", collected_at="2026-11-09T20:00:05+00:00")
    allrows = odds.store("nba", b)  # unchanged lines, later collection: kept as new rows
    assert len(allrows) == 6
    assert sorted(allrows.collected_at.unique()) == ["2026-11-09T15:00:05+00:00", "2026-11-09T20:00:05+00:00"]
    c = a.copy(); c["line"] = 99.0  # a "changed" copy of a stored row with the same key never overwrites it
    allrows = odds.store("nba", c)
    assert len(allrows) == 6 and 99.0 not in set(allrows.line.dropna())


def test_store_keeps_legacy_rows_without_collection_time(tmp_data):
    legacy = odds.parse_odds_api(EVENTS, "nba").drop(columns=["collected_at"])
    f = odds.processed_dir("nba"); f.mkdir(parents=True)
    legacy.to_parquet(f / "market_snapshots.parquet", index=False)
    allrows = odds.store("nba", odds.parse_odds_api(EVENTS, "nba", collected_at="2026-11-09T15:00:05+00:00"))
    assert len(allrows) == 6
    assert allrows.collected_at.isna().sum() == 3  # legacy rows: left empty, not back-filled
    assert len(odds.store("nba", legacy)) == 6  # re-storing legacy rows doesn't duplicate them


def test_consensus_unchanged_by_repeat_collections(tmp_data):
    a = odds.parse_odds_api(EVENTS, "nba", collected_at="2026-11-09T15:00:05+00:00").assign(game_id="g1")
    b = a.assign(collected_at="2026-11-09T20:00:05+00:00")
    one = odds.consensus(a).drop(columns=[]).reset_index(drop=True)
    two = odds.consensus(pd.concat([a, b])).reset_index(drop=True)
    pd.testing.assert_frame_equal(one, two)


def test_credit_guard(tmp_data, monkeypatch):
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    assert odds.credit_guard(now) is None  # no calls logged yet
    odds._log_usage({"at": "2026-11-19T15:00:00+00:00", "league": "nba", "remaining": "40"})
    assert odds.credit_guard(now) is None
    odds._log_usage({"at": "2026-11-19T20:00:00+00:00", "league": "nfl", "remaining": "6"})
    assert "credits" in odds.credit_guard(now)
    assert odds.credit_guard(datetime(2026, 12, 1, tzinfo=timezone.utc)) is None  # new month: one call re-checks
    monkeypatch.setenv("MODELROOM_ODDS_FORCE", "1")
    assert odds.credit_guard(now) is None
    log = [json.loads(l) for l in odds.usage_log_path().read_text().splitlines()]
    assert len(log) == 2 and all("apiKey" not in json.dumps(r) for r in log)


def test_collect_needs_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    with pytest.raises(odds.LinesError, match="ODDS_API_KEY"):
        odds.collect_odds_api("nba")


def test_collect_records_collection_time_and_usage(tmp_data, monkeypatch):
    class Resp:
        headers = {"x-requests-remaining": "497", "x-requests-used": "3", "x-requests-last": "3"}
        def read(self): return json.dumps(EVENTS).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(odds.urllib.request, "urlopen", lambda req, timeout: Resp())
    monkeypatch.setattr(odds, "raw_dir", lambda lg: tmp_data / "data" / "raw" / lg)
    df = odds.collect_odds_api("nba", api_key="SECRET-TEST-KEY")
    assert df.collected_at.notna().all() and len(df) == 3
    log = odds.last_usage()
    assert log["remaining"] == "497" and log["cost"] == "3" and log["league"] == "nba"
    for p in (tmp_data).rglob("*"):
        if p.is_file():
            assert b"SECRET-TEST-KEY" not in p.read_bytes()
