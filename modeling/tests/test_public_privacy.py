"""Public outputs never expose an individual sportsbook: no book names, no book-level lines or prices, no consensus
built from a single book. Book-level detail stays in the private odds tables.

The last test scans real public output directories when they exist (the preview branch's data/published and
preview-ledger, or any directory named in MODELROOM_PUBLIC_SCAN_DIRS), so a refresh's actual files are checked too.
"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from modelroom import privacy as P
from modelroom.common import board as B
from modelroom.common.publish import write_board
from modelroom.sources import odds


def snaps(rows):
    base = {"source": "the_odds_api", "home_team": "Home", "away_team": "Away", "commence_time": "2026-11-12T00:00:00Z"}
    return pd.DataFrame([{**base, **r} for r in rows])


TWO_BOOKS = snaps([
    {"game_id": "g1", "sportsbook": "draftkings", "market": "spread", "line": -3.5, "home_price": -110, "away_price": -110, "captured_at": "2026-11-11T15:00:00Z"},
    {"game_id": "g1", "sportsbook": "fanduel", "market": "spread", "line": -4.5, "home_price": -105, "away_price": -115, "captured_at": "2026-11-11T15:00:00Z"},
    {"game_id": "g1", "sportsbook": "draftkings", "market": "moneyline", "line": None, "home_price": -170, "away_price": 150, "captured_at": "2026-11-11T15:00:00Z"},
    {"game_id": "g1", "sportsbook": "fanduel", "market": "moneyline", "line": None, "home_price": -190, "away_price": 160, "captured_at": "2026-11-11T15:00:00Z"},
    # g2: one book only for every market
    {"game_id": "g2", "sportsbook": "betmgm", "market": "total", "line": 221.5, "over_price": -110, "under_price": -110, "captured_at": "2026-11-11T15:00:00Z"},
    {"game_id": "g2", "sportsbook": "betmgm", "market": "moneyline", "line": None, "home_price": -130, "away_price": 110, "captured_at": "2026-11-11T15:00:00Z"},
])

PROJ = {"margin": 4.0, "total": 220.0, "spread": -4.0, "home_win_prob": 0.62, "margin_range_80": [-8, 16], "total_range_80": [205, 235]}


def test_board_market_is_consensus_only():
    m = B.market_by_game(odds.consensus(TWO_BOOKS), TWO_BOOKS)
    g1, g2 = m["g1"], m["g2"]
    assert "by_book" not in g1 and "by_book" not in g2
    assert g1["spread"] == -4.0 and g1["books"] == 2  # median of -3.5 and -4.5
    assert (g1["home_ml"], g1["away_ml"]) == (-180.0, 155.0)  # medians
    # one book: no line or price at all, only that a book exists
    assert g2["total"] is None and g2["home_ml"] is None and g2["away_ml"] is None and g2["books"] == 1
    assert P.violations(m) == []


def test_edges_have_no_book_level_block_and_consensus_math_is_unchanged():
    m = B.market_by_game(odds.consensus(TWO_BOOKS), TWO_BOOKS)
    e = B.model_vs_market(PROJ, m["g1"])
    assert "by_book" not in e
    assert e["spread"] == round(-4.0 - PROJ["spread"], 2) and e["at_spread"]["line"] == -4.0
    assert e["moneyline"]["home"]["market_price"] == -180.0
    assert P.violations(e) == []


def test_writer_refuses_book_level_data_and_writes_nothing(tmp_path):
    for bad in (
        {"upcoming": [{"market": {"spread": -3, "books": 9, "captured_at": "x", "by_book": {"draftkings": {"spread": -3}}}}]},
        {"upcoming": [{"edges": {"by_book": {"fanduel": {}}}}]},
        {"upcoming": [{"market": {"spread": -3.5, "total": None, "home_ml": None, "away_ml": None, "books": 1, "captured_at": "x", "sources": ["the_odds_api"]}}]},
        {"note": "Line from DraftKings at 3 PM"},
        {"rows": {"BetMGM": 4}},
    ):
        f = tmp_path / "board.json"
        with pytest.raises(P.PrivacyError):
            write_board(f, bad)
        assert not f.exists()
    ok = write_board(tmp_path / "ok.json", {"upcoming": [{"market": {"spread": -3, "books": 9, "captured_at": "x", "sources": ["the_odds_api"]}}]})
    assert ok.exists()


def test_scanner_rules():
    assert P.violations({"sources": ["the_odds_api"], "books": 9}) == []
    assert P.violations({"market": {"spread": 3.0, "books": 0, "captured_at": None, "sources": ["nflverse"]}}) == []  # public dataset
    assert P.violations({"players": [{"comment": "reported by Dianna Russini of BetUS TV"}]}) == []  # injury news text
    assert P.violations({"players": [{"note": "per BetUS"}]})  # elsewhere a name is a finding
    assert P.violations({"x": "williamhill_us"}) and P.violations({"x": "Caesars"}) and P.violations({"x": "theScore Bet"})
    assert P.violations({"line_histories": []}) and P.violations({"sportsbook": "x"})
    assert P.violations({"label": "Underdog"}) == []  # an ordinary betting word, not a finding on its own
    assert P.sanitize_market({"spread": -3, "books": 1, "captured_at": "x", "sources": ["the_odds_api"], "by_book": {}}) == {
        "spread": None, "books": 1, "captured_at": "x", "sources": ["the_odds_api"], "total": None, "home_ml": None, "away_ml": None}
    assert "by_book" not in P.sanitize_edges({"by_book": {}, "spread": 1})


def test_sportsbook_public_report_writer_is_guarded():
    import inspect
    from modelroom.markets import sportsbook
    from modelroom.nba.props import monitor as nba_mon, shadow
    from modelroom.nfl.props import monitor as nfl_mon
    from modelroom.injuries import merge
    for mod in (sportsbook, nba_mon, nfl_mon, shadow, merge):
        assert "assert_public(" in inspect.getsource(mod), mod.__name__


def _public_dirs() -> list[Path]:
    env = [Path(p) for p in os.environ.get("MODELROOM_PUBLIC_SCAN_DIRS", "").split(os.pathsep) if p]
    here = Path(__file__).resolve().parents[1]
    return [d for d in env + [here / "data" / "published", here / "preview-ledger", here / "ledger"] if d.is_dir()]


@pytest.mark.skipif(not _public_dirs(), reason="no public output directory in this checkout")
def test_public_output_files_expose_no_sportsbook():
    files = [p for d in _public_dirs() for p in d.rglob("*") if p.is_file() and p.suffix in (".json", ".jsonl", ".parquet", ".csv", ".txt")]
    findings = P.scan_paths(files)
    assert findings == [], f"{len(findings)} finding(s), e.g. {findings[:5]}"
