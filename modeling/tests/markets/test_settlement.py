"""Settlement detection and grading. Provider payloads use the live field names (checked 2026-11-02 against
settled markets); values are synthetic. No network."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from modelroom.markets import evaluation, games, grading, polymarket_us, settlement
from modelroom.markets.schema import PropQuote

FIX = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)   # after the CHI @ SEA game
START = "2026-11-03T01:15:00+00:00"
EMPTY_CTX = {"props": {}, "games": {}, "finals": {}, "stats": {}, "stat_of": {}, "labels": {}}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path))
    for k in ("MODELROOM_MARKETS_POLYMARKET_US", "MODELROOM_MARKETS_KALSHI", "MODELROOM_MARKETS_KALSHI_PUBLISH", "MODELROOM_ENV"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def kx(status, result="", value=None, ticker="KXNFLRECYDS-26NOV02CHISEA-DKM14-50", ts=None):
    return {"ticker": ticker, "status": status, "result": result, "settlement_value_dollars": value, "settlement_ts": ts}


def pm(status, side_price=None, prices=None, slug="nfl-chi-sea-2026-11-02-dkm-recyds-50"):
    m = {"slug": slug, "status": status, "updatedAt": "2026-11-03T04:40:00Z", "marketSides": [{"long": True, "price": side_price}, {"long": False}]}
    if prices is not None:
        m["outcomePrices"] = json.dumps(prices)
    return m


def predict(market_id, p, provider="kalshi", generated_at="2026-11-02T22:00:00+00:00", market="receiving_yards", game="2026_08_CHI_SEA",
            player="00-1", kind="prop", **extra):
    return {"provider": provider, "market_id": market_id, "game_id": game, "player_id": player, "player": "D.K. Metcalf",
            "market": market, "stat": "rec_yds", "op": ">=", "threshold": 50, "variant": None, "model_prob": p, "model_version": "0.1.0",
            "generated_at": generated_at, "yes_bid": 0.47, "yes_ask": 0.49, "no_ask": 0.53, "fee_rate": 0.07, "captured_at": generated_at,
            "game_start": START, "grade": None, "kind": kind, "event_id": None, **extra}


# ------------------------------------------------------------------ detection
def test_kalshi_states():
    assert settlement.parse_kalshi(kx("finalized", "yes", "1.0000", ts="2026-11-03T04:31:00Z"))[ "result"] == "yes"
    o = settlement.parse_kalshi(kx("finalized", "no", "0.0000"))
    assert (o["state"], o["result"]) == ("settled", "no")
    for st in ("determined", "amended", "disputed", "closed", "active"):
        o = settlement.parse_kalshi(kx(st, "yes" if st == "determined" else ""))
        assert o["state"] == "pending", st           # not final until finalized
    o = settlement.parse_kalshi(kx("finalized", "", "0.5000"))
    assert (o["state"], o["result"]) == ("settled", "void")
    o = settlement.parse_kalshi(kx("finalized", "yes", "0.0000"))   # contradictory fields
    assert o["state"] == "pending"


def test_polymarket_states():
    assert settlement.parse_polymarket(pm("MARKET_STATUS_RESOLVED", "1.0000", ["1", "0"]))["result"] == "yes"
    assert settlement.parse_polymarket(pm("MARKET_STATUS_RESOLVED", "0.0000", ["0", "1"]))["result"] == "no"
    o = settlement.parse_polymarket(pm("MARKET_STATUS_RESOLVED", "0.3700", ["0.37", "0.63"]))
    assert (o["state"], o["result"]) == ("settled", "void")          # settled at last fair price
    assert settlement.parse_polymarket(pm("MARKET_STATUS_RESOLVED", "1.0000", ["0", "1"]))["state"] == "pending"  # disagree
    assert settlement.parse_polymarket(pm("MARKET_STATUS_RESOLVED", None, None))["state"] == "pending"            # no value
    assert settlement.parse_polymarket(pm("MARKET_STATUS_OPEN", "0.43"))["state"] == "pending"
    assert settlement.parse_polymarket(pm("MARKET_STATUS_CANCELLED"))["result"] == "void"


def test_duplicate_observations_are_recorded_once():
    o = settlement.parse_kalshi(kx("finalized", "yes", "1.0"))
    assert settlement.record("nfl", [o], T0)["recorded"] == 1
    assert settlement.record("nfl", [dict(o)], T0 + timedelta(hours=1))["recorded"] == 0
    assert len(settlement.load("nfl")) == 1


def test_corrected_settlement_keeps_the_audit_trail():
    settlement.record("nfl", [settlement.parse_kalshi(kx("finalized", "yes", "1.0"))], T0)
    r = settlement.record("nfl", [settlement.parse_kalshi(kx("finalized", "no", "0.0"))], T0 + timedelta(hours=2))
    assert r == {"recorded": 1, "corrections": 1}
    log = settlement.load("nfl")
    assert list(log["result"]) == ["yes", "no"]                       # original kept
    assert log.iloc[-1]["corrects"]["result"] == "yes"


# ------------------------------------------------------------------ grading
def _grade():
    return {r["market_id"]: r for r in grading.records("nfl", EMPTY_CTX)}


def test_delayed_settlement_stays_pending_then_grades():
    evaluation.record("nfl", [predict("K1", 0.62)])
    calls = []

    def fake(tickers, cache):
        calls.append(tickers)
        return [settlement.parse_kalshi(kx("determined", "yes", ticker="K1"))]

    settlement.check("nfl", T0, fetchers={"kalshi": fake}, require_enabled=False)
    assert _grade()["K1"]["status"] == "pending"                      # determined isn't final
    settlement.check("nfl", T0 + timedelta(hours=1), fetchers={"kalshi": lambda t, c: [settlement.parse_kalshi(kx("finalized", "yes", "1.0", ticker="K1"))]},
                     require_enabled=False)
    g = _grade()["K1"]
    assert (g["status"], g["settlement"]["result"]) == ("won", "yes")
    assert calls == [["K1"]]


def test_grades_each_market_independently_and_against_settlement_only():
    evaluation.record("nfl", [predict("A", 0.70), predict("B", 0.30), predict("C", 0.60), predict("D", 0.55, market="receptions")])
    settlement.record("nfl", [settlement.parse_kalshi(kx("finalized", "yes", "1.0", ticker="A")),
                              settlement.parse_kalshi(kx("finalized", "yes", "1.0", ticker="B")),
                              settlement.parse_kalshi(kx("finalized", "", "0.5", ticker="C"))], T0)
    # A box score saying the player went over must not grade D: only its own market can.
    ctx = {**EMPTY_CTX, "stats": {("2026_08_CHI_SEA", "00-1"): {"rec_yds": 88.0, "rec": 7.0}}, "stat_of": {"receiving_yards": "rec_yds", "receptions": "rec"}}
    g = {r["market_id"]: r for r in grading.records("nfl", ctx)}
    assert g["A"]["status"] == "won" and g["B"]["status"] == "lost" and g["C"]["status"] == "void"
    assert g["D"]["status"] == "pending"
    assert g["A"]["actual"] == {"stat": 88.0}                          # shown as context only
    assert g["A"]["market_implied"] == pytest.approx(0.48)


def test_only_the_pre_game_prediction_counts():
    evaluation.record("nfl", [predict("E", 0.40, generated_at="2026-11-02T20:00:00+00:00"),
                              predict("E", 0.45, generated_at="2026-11-02T23:00:00+00:00"),
                              predict("E", 0.90, generated_at="2026-11-03T02:00:00+00:00")])   # after kickoff: ignored
    settlement.record("nfl", [settlement.parse_kalshi(kx("finalized", "yes", "1.0", ticker="E"))], T0)
    g = _grade()["E"]
    assert g["model_prob"] == 0.45 and g["predicted_at"].startswith("2026-11-02T23") and g["status"] == "lost"


def test_summary_and_publication_rules(monkeypatch):
    evaluation.record("nfl", [predict("A", 0.70), predict("B", 0.30), predict("P", 0.8, provider="polymarket_us")])
    settlement.record("nfl", [settlement.parse_kalshi(kx("finalized", "yes", "1.0", ticker="A")),
                              settlement.parse_kalshi(kx("finalized", "yes", "1.0", ticker="B")),
                              settlement.parse_polymarket(pm("MARKET_STATUS_RESOLVED", "1.0", ["1", "0"], slug="P"))], T0)
    monkeypatch.setenv("MODELROOM_MARKETS_POLYMARKET_US", "on")
    monkeypatch.setenv("MODELROOM_MARKETS_KALSHI", "on")                # on, but not publishable
    out = grading.run("nfl", EMPTY_CTX)
    assert out["predictions"] == 3 and out["published"] == 1 and out["withheld"] == {"kalshi": 2}
    pub = json.loads((settlement.data_root() / "published" / "market_results_nfl.json").read_text())
    assert {r["provider"] for r in pub["records"]} == {"polymarket_us"}
    s = grading.summary(grading.records("nfl", EMPTY_CTX))["overall"]
    assert (s["won"], s["lost"], s["win_pct"]) == (2, 1, pytest.approx(0.6667, abs=1e-4))
    assert s["n_scored"] == 3 and "brier" in s and s["market"]["n"] == 3


# ------------------------------------------------------------------ game markets
def test_polymarket_game_spread_is_normalized():
    ev = json.loads((FIX / "polymarket_us_event_nfl.json").read_text())["event"]
    qs = [q for q in polymarket_us.parse_event(ev, "nfl") if q.market == "game_spread"]
    assert qs and qs[0].team == "CHI" and qs[0].op == ">" and qs[0].threshold == 10.5   # CHI covers −10.5 ⇔ CHI margin > 10.5


def test_kalshi_game_markets_and_model_probability():
    payload = {"events": [{"event_ticker": "KXNFLSPREAD-26NOV02CHISEA", "sub_title": "CHI vs SEA (Nov 2)", "markets": [
        {"ticker": "KXNFLSPREAD-26NOV02CHISEA-SEA3", "floor_strike": 3.5, "strike_type": "greater", "yes_bid_dollars": "0.44", "yes_ask_dollars": "0.46"}]}]}
    q = games.parse_kalshi("KXNFLSPREAD", payload, "nfl")[0]
    assert (q.market, q.team, q.threshold, q.home_team, q.away_team) == ("game_spread", "SEA", 3.5, "SEA", "CHI")
    g = {"home": {"abbr": "SEA"}, "projection": {"margin": 3.4, "total": 40.3, "home_win_prob": 0.60, "margin_range_80": [-13.2, 20.0], "total_range_80": [23.2, 57.4]}}
    p = games.model_prob(q, g)
    assert 0.45 < p < 0.5                                              # 3.4 projected vs 3.5 needed
    win = PropQuote(provider="kalshi", league="nfl", market="game_winner", op=">", threshold=0, player_name="", team="CHI", game_date="2026-11-02")
    assert games.model_prob(win, g) == pytest.approx(0.40)
    tot = PropQuote(provider="kalshi", league="nfl", market="game_total", op=">", threshold=46.5, player_name="", team=None, game_date="2026-11-02")
    assert games.model_prob(tot, g) < 0.4
