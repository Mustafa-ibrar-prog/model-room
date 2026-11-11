"""Historical sportsbook analysis: no-lookahead matching, implied probabilities with/without margin, line histories,
movement, coverage, staleness, settled vs upcoming separation, the 250-game gate, labels and storage."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from modelroom.markets import sportsbook as SB
from modelroom.sources import odds_store as S


def snap(collected, line=-3.5, hp=-110, ap=-110, market="spread", book="draftkings", gid="g1", captured=None,
         commence="2026-11-12T01:00:00Z", over=None, under=None, h="BOS", a="NYK"):
    return {"league": "nba", "game_id": gid, "home_team": h, "away_team": a, "commence_time": commence,
            "sportsbook": book, "market": market, "line": line, "home_price": hp, "away_price": ap,
            "over_price": over, "under_price": under, "captured_at": captured or collected, "source": "the_odds_api",
            "collected_at": collected, "raw_sha256": None, "snapshot_hash": f"h{abs(hash((collected, book, market, gid))) % 10**12}"}


def rec(gen, margin=4.0, total=220.0, hw=0.62, gid="g1", start="2026-11-12T01:00:00+00:00", h="r"):
    return {"game_id": gid, "generated_at": gen, "game_start": start, "pred_margin": margin, "pred_total": total,
            "home_win_prob": hw, "model_version": "1.1.0", "hash": h + gen}


SIG = {"1.1.0": {"margin": 12.0, "total": 18.0, "source": "test"}}


def test_implied_with_and_without_margin():
    P = SB.prepare(pd.DataFrame([snap("2026-11-11T15:00:00+00:00", hp=-110, ap=-110)]))
    r = P.iloc[0]
    assert r.implied_a == pytest.approx(110 / 210) and r.overround == pytest.approx(2 * 110 / 210 - 1)
    assert r.novig_a == pytest.approx(0.5) and r.novig_b == pytest.approx(0.5)


def test_matching_uses_only_the_latest_prediction_before_the_line():
    snaps = pd.DataFrame([snap("2026-11-11T15:00:00+00:00"), snap("2026-11-11T20:00:00+00:00")])
    recs = [rec("2026-11-11T14:00:00+00:00", margin=2.0, h="a"), rec("2026-11-11T16:00:00+00:00", margin=6.0, h="b"),
            rec("2026-11-11T20:00:00+00:00", margin=9.0, h="c")]  # same instant as the 2nd line: NOT before it
    C, why = SB.comparisons(SB.prepare(snaps), SB.model_index(recs), SIG)
    by = {c["collected_at"]: c for c in C}
    assert by["2026-11-11T15:00:00+00:00"]["model_pred_margin"] == 2.0
    assert by["2026-11-11T20:00:00+00:00"]["model_pred_margin"] == 6.0
    for c in C:
        assert pd.Timestamp(c["model_generated_at"]) < pd.Timestamp(c["collected_at"])


def test_no_prediction_before_line_and_post_start_lines_are_excluded():
    snaps = pd.DataFrame([snap("2026-11-11T10:00:00+00:00"), snap("2026-11-12T02:00:00+00:00")])  # 2nd after start
    C, why = SB.comparisons(SB.prepare(snaps), SB.model_index([rec("2026-11-11T12:00:00+00:00")]), SIG)
    assert C == [] and why["no_prediction_before_line"] == 1 and why["post_start"] == 1


def test_model_probability_at_exact_line():
    snaps = pd.DataFrame([snap("2026-11-11T15:00:00+00:00", line=-4.0),
                          snap("2026-11-11T15:00:00+00:00", market="total", line=220.5, hp=None, ap=None, over=-110, under=-110),
                          snap("2026-11-11T15:00:00+00:00", market="moneyline", line=None, hp=-180, ap=150)])
    C, _ = SB.comparisons(SB.prepare(snaps), SB.model_index([rec("2026-11-11T14:00:00+00:00", margin=4.0)]), SIG)
    c = {x["market"]: x for x in C}
    assert c["spread"]["model_prob_push"] > 0  # whole-number line can push
    assert c["spread"]["model_prob_a_excl_push"] == pytest.approx(0.5, abs=1e-3)  # margin 4, home -4: even without push
    assert c["total"]["model_prob_a"] == pytest.approx(0.4889, abs=1e-3)  # P(total >= 221), mean 220, sd 18
    assert c["moneyline"]["model_prob_a"] == 0.62
    assert c["moneyline"]["book_novig_a"] == pytest.approx((180 / 280) / (180 / 280 + 100 / 250), abs=1e-4)


def test_line_history_labels_and_movement():
    snaps = pd.DataFrame([snap("2026-11-11T15:00:00+00:00", line=-3.5), snap("2026-11-11T20:00:00+00:00", line=-4.5),
                          snap("2026-11-11T22:00:00+00:00", line=-5.0)])
    H = SB.line_histories(SB.prepare(snaps))
    h = H[0]
    assert h["observations"] == 3 and len(h["intermediate"]) == 1
    assert h["earliest_observed"]["line"] == -3.5 and h["latest_observed"]["line"] == -5.0
    assert h["line_change"] == -1.5 and h["direction"] == "toward home"
    assert "not a closing line" in h["latest_label"] and "closing" not in json.dumps({k: v for k, v in h.items() if k != "latest_label"})
    m = SB.movement_summary(H)
    assert m["by_team"]["BOS"]["moved_toward"] == 1 and m["by_team"]["NYK"]["moved_against"] == 1


def test_coverage_missing_books_markets_stale_and_unchanged():
    f1, f2 = "2026-11-11T15:00:00+00:00", "2026-11-11T20:00:00+00:00"
    rows = [snap(f1, book="a"), snap(f1, book="a", market="moneyline", line=None), snap(f1, book="b", gid="g2", h="LAL", a="DEN"),
            snap(f1, book="b", market="total", line=220.5, hp=None, ap=None, over=-110, under=-110),
            snap(f2, book="a"), snap(f2, book="a", market="moneyline", line=None, captured="2026-11-11T08:00:00+00:00")]
    P = SB.prepare(pd.DataFrame(rows))
    pub, priv = SB.coverage(P)
    f = {x["collected_at"]: x for x in pub["fetches"]}
    assert f[f1]["books"] == 2 and f[f1]["game_book_pairs_missing_a_book"] >= 1
    assert pub["stale_rows_total"] == 1  # book timestamp 12 h old at collection
    assert pub["unchanged_rows_total"] == 2  # spread and moneyline at f2: same line and prices as at f1
    assert any(d["missing_markets_by_book"] for d in priv["missing_by_game"])


def test_settled_kept_separate_and_gate():
    snaps = pd.DataFrame([snap("2026-11-11T15:00:00+00:00", gid="g1"), snap("2026-11-11T15:00:00+00:00", gid="g2", h="LAL", a="DEN")])
    recs = [rec("2026-11-11T14:00:00+00:00", gid="g1"), rec("2026-11-11T14:00:00+00:00", gid="g2")]
    pub, priv, C = SB.analyse("nba", snaps, recs, SIG, finals={"g1": (110, 100)})
    assert pub["accumulation"]["games_with_comparisons"] == {"settled": 1, "upcoming_or_unsettled": 1}
    assert pub["settled"]["spread"]["status"].startswith("insufficient sample") and "model_log_loss" not in pub["settled"]["spread"]
    assert all(c["game_id"] == "g2" for c in priv["upcoming_latest_comparisons"])
    assert pub["closing_line_value"]["status"] == "disabled"
    # public report carries no line values or prices
    txt = json.dumps(pub)
    assert "-3.5" not in txt and "price" not in txt.replace("prices", "")


def test_summary_statistics_only_at_gate():
    rng = np.random.default_rng(1)
    ev = [{"game_id": str(i), "market": "spread", "line": -3.5, "books": 5, "y": int(rng.random() < 0.5),
           "book_novig_a": 0.5, "model_prob_a": float(rng.uniform(0.4, 0.6)), "hours_before_start": 8.0} for i in range(250)]
    s = SB.settled_summary(ev)
    assert s["spread"]["settled_games"] == 250 and "model_log_loss" in s["spread"] and len(s["spread"]["model_minus_book_log_loss_95ci"]) == 2
    s = SB.settled_summary(ev[:249])
    assert "model_log_loss" not in s["spread"]


def test_outcome_rules():
    assert SB.outcome("spread", -3.5, 110, 100) == 1 and SB.outcome("spread", -10.0, 110, 100) is None  # push
    assert SB.outcome("total", 210.5, 110, 100) == 0 and SB.outcome("moneyline", None, 99, 100) == 0


PG = os.environ.get("MODELROOM_TEST_PG")


@pytest.mark.skipif(not PG, reason="MODELROOM_TEST_PG not set")
def test_derived_tables_append_only_and_chained():
    import re
    import uuid
    from pathlib import Path

    import psycopg
    name = "mr_an_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"create database {name}")
    url = re.sub(r"dbname=\S+", f"dbname={name}", PG) if "dbname=" in PG else PG + f" dbname={name}"
    c = psycopg.connect(url, autocommit=True)
    for role in ("anon", "authenticated"):
        c.execute(f"do $$ begin create role {role} nologin; exception when duplicate_object then null; end $$")
    root = Path(__file__).resolve().parents[2] / "supabase/migrations"
    c.execute((root / "20261111000100_odds_snapshots.sql").read_text())
    c.execute((root / "20261111000200_odds_analysis.sql").read_text())
    c.close()
    try:
        conn = S.connect(url)
        items = [("k1", {"a": 1}), ("k2", {"a": 2})]
        assert S.insert_payloads(conn, "comparisons", "nba", items, "t")["inserted"] == 2
        assert S.insert_payloads(conn, "comparisons", "nba", items + [("k3", {"a": 3})], "t")["inserted"] == 1
        v = S.verify_table(conn, "comparisons", "nba")
        assert v["ok"] and v["rows"] == 3
        assert [p["a"] for p in S.load_payloads(conn, "comparisons", "nba")] == [1, 2, 3]
        S.insert_payloads(conn, "reports", "nba", [("r1", {"x": 1})], "t")
        for sql in ("update odds.comparisons set payload = '{}'", "delete from odds.reports", "truncate odds.comparisons"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                with conn.transaction():
                    conn.execute(sql)
        conn.close()
    finally:
        admin.execute(f"drop database {name} with (force)")
        admin.close()


def test_schedule_coverage_window_is_capped():
    f = "2026-11-11T15:00:00+00:00"
    P = SB.prepare(pd.DataFrame([snap(f, gid="g1"), snap(f, gid="g9", commence="2026-12-30T01:00:00Z", h="LAL", a="DEN")]))
    sched = pd.DataFrame({"game_id": ["g1", "g2", "g3"], "start_ts": pd.to_datetime(["2026-11-12T01:00:00Z", "2026-11-12T03:00:00Z", "2026-12-01T01:00:00Z"], utc=True)})
    pub, _ = SB.coverage(P, sched)
    assert pub["fetches"][0]["scheduled_games_next_72h_without_lines"] == 1  # g2 only; g3 is beyond 72 h
