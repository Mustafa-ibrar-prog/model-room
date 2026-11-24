"""Private archive (R2 / local folder) for the odds tables, closed ledgers and Pick of the Day audit days.
Database tests need MODELROOM_TEST_PG (a disposable Postgres); the R2 test uses moto's S3 mock when installed."""
import io
import json
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from modelroom.archive import audit, ledgers, odds
from modelroom.archive.store import LocalStore, R2Store, sha256
from modelroom.common import ledger as L
from modelroom.sources import odds_store as S

PG = os.environ.get("MODELROOM_TEST_PG")
pg = pytest.mark.skipif(not PG, reason="MODELROOM_TEST_PG not set")
MIG = Path(__file__).resolve().parents[2] / "supabase/migrations"


@pytest.fixture
def db(monkeypatch, tmp_path):
    import psycopg
    name = "mr_arc_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"create database {name}")
    url = re.sub(r"dbname=\S+", f"dbname={name}", PG) if "dbname=" in PG else PG + f" dbname={name}"
    c = psycopg.connect(url, autocommit=True)
    for role in ("anon", "authenticated"):
        c.execute(f"do $$ begin create role {role} nologin; exception when duplicate_object then null; end $$")
    for m in ("20261111000100_odds_snapshots.sql", "20261111000200_odds_analysis.sql", "20261122000100_potd_model_audit.sql"):
        c.execute((MIG / m).read_text())
    c.close()
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path / "ledger"))
    yield url
    admin.execute(f"drop database {name} with (force)")
    admin.close()


def fill(url, n=57):
    conn = S.connect(url)
    S.insert_payloads(conn, "reports", "nba", [(f"r{i}", {"report": i, "lines": list(range(i))}) for i in range(n)], "t")
    return conn


def tamper(url, sql):
    import psycopg
    c = psycopg.connect(url, autocommit=True)
    c.execute("set session_replication_role = replica")
    c.execute(sql)
    c.close()


@pg
def test_only_closed_segments_archived_and_chain_verified(db, tmp_path):
    conn = fill(db)                                                       # 57 reports, segments of 25 -> 2 closed
    st = LocalStore(tmp_path / "bucket")
    r = odds.archive_table(conn, st, "dryrun/v1", "reports", "nba", run_id="t")
    assert not r["problems"] and r["db_chain_ok"]
    assert [(s["first"], s["last"]) for s in r["new_segments"]] == [(1, 25), (26, 50)]
    assert r["archived_rows"] == 50 and r["tail_rows_in_supabase_only"] == 7
    v = odds.verify_archive(st, "dryrun/v1", "reports", "nba", conn)
    assert v["ok"] and v["rows"] == 50 and v["head"] == S._fetchone(conn.cursor().execute("select row_hash from odds.reports where seq = 50"))[0]
    # the archive matches the database row for row
    back = odds.load_archived(st, "dryrun/v1", "reports", "nba")
    db_rows = conn.cursor().execute("select seq, payload, row_hash from odds.reports where seq <= 50 order by seq").fetchall()
    assert list(back[["seq", "payload", "row_hash"]].itertuples(index=False, name=None)) == [tuple(x) for x in db_rows]
    # a second run downloads nothing it already has
    S._READ.update(bytes=0, rows=0, queries=0)
    r2 = odds.archive_table(conn, st, "dryrun/v1", "reports", "nba")
    assert r2["skipped_existing"] == 2 and not r2["new_segments"] and S.bytes_read()["bytes"] < 500


@pg
def test_partial_read_touches_only_needed_segments(db, tmp_path):
    conn = fill(db, 80)
    st = LocalStore(tmp_path / "b")
    odds.archive_table(conn, st, "v1", "reports", "nba", rows_per_segment=10)
    got = odds.load_archived(st, "v1", "reports", "nba", 31, 35)
    assert list(got["seq"]) == [31, 32, 33, 34, 35]


@pg
def test_corrupt_or_missing_archive_objects_are_caught(db, tmp_path):
    conn = fill(db)
    st = LocalStore(tmp_path / "b")
    odds.archive_table(conn, st, "v1", "reports", "nba")
    f = tmp_path / "b" / "v1/odds/reports/nba/seg-00000026-00000050.parquet"
    f.write_bytes(f.read_bytes()[:-10] + b"0123456789")                 # corrupted object
    v = odds.verify_archive(st, "v1", "reports", "nba", conn)
    assert not v["ok"] and "checksum" in v["problems"][0]
    f.unlink()                                                            # missing object
    with pytest.raises(Exception):
        odds.verify_archive(st, "v1", "reports", "nba", conn)


@pg
def test_database_tampering_stops_archiving_and_is_reported(db, tmp_path):
    conn = fill(db)
    tamper(db, "update odds.reports set payload = payload || ' ' where seq = 7")
    r = odds.archive_table(conn, LocalStore(tmp_path / "b"), "v1", "reports", "nba")
    assert not r["db_chain_ok"] and r["problems"] and not r["new_segments"]


@pg
def test_rewritten_history_after_archiving_is_caught_against_the_database(db, tmp_path):
    conn = fill(db)
    st = LocalStore(tmp_path / "b")
    odds.archive_table(conn, st, "v1", "reports", "nba")
    tamper(db, "update odds.reports set row_hash = repeat('a', 64) where seq = 25")
    v = odds.verify_archive(st, "v1", "reports", "nba", conn)
    assert not v["ok"] and any("database row 25" in p for p in v["problems"])


def test_verify_block_catches_gaps_reordering_and_edits():
    rows, prev = [], S.GENESIS
    for i in range(1, 6):
        p = json.dumps({"i": i}); h = S.chain(prev, p)
        rows.append({"seq": i, "payload": p, "prev_hash": prev, "row_hash": h}); prev = h
    assert odds.verify_block(rows, 1, S.GENESIS) == []
    assert odds.verify_block(rows[:2] + rows[3:], 1, S.GENESIS)                          # missing row
    assert odds.verify_block([rows[1], rows[0]] + rows[2:], 1, S.GENESIS)                 # reordered
    bad = [dict(r) for r in rows]; bad[2]["payload"] = bad[2]["payload"].replace("3", "4")
    assert odds.verify_block(bad, 1, S.GENESIS)                                          # edited
    assert odds.verify_block(rows[2:], 3, "f" * 64)                                       # doesn't continue the previous segment


def _ledger(tmp_path, name, n=4):
    base = tmp_path / "led"; base.mkdir(exist_ok=True)
    f = base / name
    L.append(f, [{"game_id": f"g{i}", "model_version": "0.2.0", "inputs_hash": "x", "params_hash": "y",
                  "generated_at": "2026-11-10T00:00:00+00:00", "game_start": "2026-11-11T00:00:00+00:00", "p": i} for i in range(n)])
    return base, f


def test_closed_ledgers_copied_byte_for_byte_open_week_left(tmp_path):
    base, f = _ledger(tmp_path, "nba_props_shadow_0.2.3c_2026-W47.jsonl")
    _ledger(tmp_path, "nba_props_week_2026-W48.jsonl")
    st = LocalStore(tmp_path / "b")
    r = ledgers.archive_ledgers(st, "v1", base, now=datetime(2026, 11, 24, tzinfo=timezone.utc))
    assert [c["file"] for c in r["copied"]] == ["nba_props_shadow_0.2.3c_2026-W47.jsonl"]
    assert r["skipped_open"] == ["nba_props_week_2026-W48.jsonl"]
    import zstandard
    assert zstandard.ZstdDecompressor().decompress(st.get("v1/ledgers/nba_props_shadow_0.2.3c_2026-W47.jsonl.zst")) == f.read_bytes()
    assert ledgers.verify_ledgers(st, "v1")["ok"]
    # a closed ledger that later changes is never silently replaced
    t = f.read_text(); f.write_text(t.replace('"p": 1', '"p": 9').replace('"p":1', '"p":9'))
    assert f.read_text() != t
    r2 = ledgers.archive_ledgers(st, "v1", base, now=datetime(2026, 11, 24, tzinfo=timezone.utc))
    assert r2["problems"] and "changed since it was archived" in r2["problems"][0]


def test_broken_ledger_is_not_archived(tmp_path):
    base, f = _ledger(tmp_path, "nba_props_week_2026-W40.jsonl")
    lines = f.read_text().splitlines(); f.write_text("\n".join(lines[:1] + lines[2:]) + "\n")   # a line removed
    r = ledgers.archive_ledgers(LocalStore(tmp_path / "b"), "v1", base, now=datetime(2026, 11, 24, tzinfo=timezone.utc))
    assert r["problems"] and not r["copied"]


@pg
def test_audit_days_copied_with_counts_and_versions(db, tmp_path):
    import psycopg
    c = psycopg.connect(db, autocommit=True)
    for d, n in (("2026-11-20", 3), ("2026-11-21", 2), ("2026-11-23", 4)):
        for i in range(n):
            c.execute("insert into odds.potd_model_outputs (game_date, game_id, player_id, player, stat, model_version, board_generated_at, projection, reference, explanation) "
                      "values (%s, 'g', %s, 'P', 'points', '0.2.0', now() + make_interval(secs => %s), 20, 'season average', 'x')", (d, f"p{i}", i))
    c.close()
    conn = S.connect(db)
    st = LocalStore(tmp_path / "b")
    r = audit.archive_days(conn, st, "v1", today=date(2026, 11, 23))
    assert [x["day"] for x in r["copied"]] == ["2026-11-20", "2026-11-21"] and r["rows_archived"] == 5 and not r["problems"]
    assert audit.archive_days(conn, st, "v1", today=date(2026, 11, 23))["already"] == 2


def test_r2_store_round_trip_with_checksum_metadata():
    moto = pytest.importorskip("moto")
    import boto3
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="mr-test")
        st = R2Store.__new__(R2Store)
        st.bucket, st.s3 = "mr-test", boto3.client("s3", region_name="us-east-1")
        put = st.put("v1/x.bin", b"hello", {"rows": 1})
        assert put["sha256"] == sha256(b"hello") and st.get("v1/x.bin") == b"hello" and st.exists("v1/x.bin") and not st.exists("v1/nope")
        assert st.s3.head_object(Bucket="mr-test", Key="v1/x.bin")["Metadata"]["sha256"] == sha256(b"hello")


@pg
def test_refresh_load_uses_archive_plus_tail_and_falls_back_on_mismatch(db, tmp_path, monkeypatch):
    from modelroom.sources import odds as O
    conn = S.connect(db)
    for h in range(10, 22):                                               # 12 collections x 3 lines = 36 snapshot rows
        ev = [{"home_team": "H", "away_team": "A", "commence_time": "2026-11-30T00:30:00Z", "bookmakers": [{"key": "bk", "last_update": f"2026-11-11T{h}:00:00Z", "markets": [
            {"key": "spreads", "outcomes": [{"name": "H", "price": -110, "point": -1.5 - h}, {"name": "A", "price": -110, "point": 1.5 + h}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 200 + h}, {"name": "Under", "price": -110, "point": 200 + h}]},
            {"key": "h2h", "outcomes": [{"name": "H", "price": -150, "point": None}, {"name": "A", "price": 130, "point": None}]}]}]}]
        df = O.parse_odds_api(ev, "nba", collected_at=f"2026-11-11T{h}:00:05+00:00").assign(game_id="g1", raw_sha256="a" * 64)
        S.insert(conn, "nba", df, "t")
    full = S.load_with_hashes(conn, "nba", use_archive=False)
    st = LocalStore(tmp_path / "bucket")
    odds.archive_table(conn, st, "v1", "snapshots", "nba", rows_per_segment=10)          # 30 archived, 6 left in Supabase
    import modelroom.archive.store as ST
    monkeypatch.setattr(ST, "from_env", lambda local_root=None: st)
    monkeypatch.setenv("MODELROOM_ARCHIVE_READ", "on")
    S._READ.update(bytes=0, rows=0, queries=0)
    mixed = S.load_with_hashes(conn, "nba")
    assert S.bytes_read()["rows"] == 6                                    # only the tail came from Supabase
    pd.testing.assert_frame_equal(mixed, full)
    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODELROOM_ODDS_DB_URL", db)
    assert S.cmd("load", "nba")["verify"]["ok"]
    # a corrupted archive object is refused (checksum) and the full Supabase read is used instead
    f = tmp_path / "bucket" / "v1/odds/snapshots/nba/seg-00000011-00000020.parquet"
    f.write_bytes(b"x" + f.read_bytes()[1:])
    S._READ.update(bytes=0, rows=0, queries=0)
    assert len(S.load_with_hashes(conn, "nba")) == 36 and S.bytes_read()["rows"] == 36
