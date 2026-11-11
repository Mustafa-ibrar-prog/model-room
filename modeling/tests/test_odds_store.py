"""Append-only sportsbook snapshot store (odds.snapshots). Pure tests always run; database tests run when
MODELROOM_TEST_PG points to a disposable Postgres with migration 20261111000100 applied."""
import json
import os

import pandas as pd
import pytest

from modelroom.sources import odds as O
from modelroom.sources import odds_store as S

EVENTS = [{
    "home_team": "Boston Celtics", "away_team": "New York Knicks", "commence_time": "2026-11-12T00:30:00Z",
    "bookmakers": [{"key": "draftkings", "last_update": "2026-11-11T15:00:00Z", "markets": [
        {"key": "spreads", "last_update": "2026-11-11T14:58:00Z", "outcomes": [
            {"name": "Boston Celtics", "price": -110, "point": -5.5}, {"name": "New York Knicks", "price": -110, "point": 5.5}]},
        {"key": "totals", "outcomes": [{"name": "Over", "price": -108, "point": 221.5}, {"name": "Under", "price": -112, "point": 221.5}]},
        {"key": "h2h", "outcomes": [{"name": "Boston Celtics", "price": -230}, {"name": "New York Knicks", "price": 190}]},
    ]}],
}]


def frame(collected="2026-11-11T15:00:05+00:00", raw="a" * 64):
    df = O.parse_odds_api(EVENTS, "nba", collected_at=collected).assign(game_id="g1")
    df["raw_sha256"] = raw
    return df


def test_payload_is_canonical_and_round_trips():
    df = frame()
    rows = S.rows_from_frame(df)
    assert len(rows) == 3
    p = rows[0]["payload"]
    assert p == S.payload_of(json.loads(p))  # stable
    back = S.frame_from_payloads([r["payload"] for r in rows])
    pd.testing.assert_frame_equal(back.reset_index(drop=True), df[S.PAYLOAD_FIELDS].reset_index(drop=True), check_dtype=False)


def test_chain_verification_detects_tampering():
    rows, prev = [], S.GENESIS
    for i, r in enumerate(S.rows_from_frame(frame()), start=1):
        h = S.chain(prev, r["payload"])
        rows.append({"seq": i, "payload": r["payload"], "prev_hash": prev, "row_hash": h, "content_key": S.content_key(r["data"]),
                     **{k: r["data"].get(k) for k in S.TYPED}})
        prev = h
    assert S.verify_rows(rows)["ok"]
    bad = [dict(x) for x in rows]
    bad[1]["payload"] = bad[1]["payload"].replace("draftkings", "fanduel"); assert bad[1]["payload"] != rows[1]["payload"]
    assert not S.verify_rows(bad)["ok"]
    bad = [dict(x) for x in rows]
    bad[2]["line"] = 999.0
    assert not S.verify_rows(bad)["ok"]
    assert not S.verify_rows([rows[0], rows[2]])["ok"]  # a removed row breaks the chain


PG = os.environ.get("MODELROOM_TEST_PG")
pgonly = pytest.mark.skipif(not PG, reason="MODELROOM_TEST_PG not set")


@pytest.fixture
def fresh_db():
    """A brand-new database with the migration applied; dropped afterwards."""
    import uuid
    from pathlib import Path
    import psycopg
    name = "mr_odds_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"create database {name}")
    import re
    url = re.sub(r"dbname=\S+", f"dbname={name}", PG) if "dbname=" in PG else PG + f" dbname={name}"
    mig = Path(__file__).resolve().parents[2] / "supabase/migrations/20261111000100_odds_snapshots.sql"
    c = psycopg.connect(url, autocommit=True)
    for role in ("anon", "authenticated"):
        c.execute(f"do $$ begin create role {role} nologin; exception when duplicate_object then null; end $$")
    c.execute(mig.read_text())
    c.close()
    yield url
    admin.execute(f"drop database {name} with (force)")
    admin.close()


@pgonly
def test_database_append_only_round_trip_and_refusals(fresh_db):
    import psycopg
    conn = S.connect(fresh_db)
    league = "nfl"  # tests use the nfl chain of a disposable database
    df = frame()
    r1 = S.insert(conn, league, df, batch="test")
    assert r1["inserted"] == 3
    assert S.insert(conn, league, df, batch="test")["inserted"] == 0  # same collection again: nothing new
    later = frame(collected="2026-11-11T20:00:05+00:00", raw="b" * 64)
    assert S.insert(conn, league, pd.concat([df, later]), batch="test")["inserted"] == 3  # unchanged lines, later fetch
    v = S.verify(conn, league)
    assert v["ok"] and v["rows"] == 6
    back = S.load(conn, league)
    pd.testing.assert_frame_equal(back.reset_index(drop=True), pd.concat([df, later])[S.PAYLOAD_FIELDS].reset_index(drop=True), check_dtype=False)
    for sql in ("update odds.snapshots set line = 0", "delete from odds.snapshots", "truncate odds.snapshots"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            with conn.transaction():
                conn.execute(sql)
    conn.close()
