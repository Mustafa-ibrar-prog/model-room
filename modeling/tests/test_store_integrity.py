"""Integrity checks for the egress-optimised store (Moose, 2026-11-23): the in-database chain check (server_check)
must catch exactly what the client-side verifiers catch, the checkpoint anchor must catch rewrites the chain alone
cannot, and the single-read / missing-key paths must behave like the old full reads. Records are tampered with the
way only a database superuser could (append-only triggers switched off), on a disposable database."""
import json
import os
import re
import uuid
from pathlib import Path

import pandas as pd
import pytest

from modelroom.sources import odds as O
from modelroom.sources import odds_store as S

PG = os.environ.get("MODELROOM_TEST_PG")
pytestmark = pytest.mark.skipif(not PG, reason="MODELROOM_TEST_PG not set")
MIG = Path(__file__).resolve().parents[2] / "supabase/migrations"


def _events(n_games: int, collected_hour: int):
    out = []
    for g in range(n_games):
        out.append({"home_team": f"Home {g}", "away_team": f"Away {g}", "commence_time": f"2026-11-{12 + g % 5:02d}T00:30:00Z",
                    "bookmakers": [{"key": "bookA", "last_update": f"2026-11-11T{collected_hour:02d}:00:00Z", "markets": [
                        {"key": "spreads", "outcomes": [{"name": f"Home {g}", "price": -110, "point": -1.5 - g},
                                                        {"name": f"Away {g}", "price": -110, "point": 1.5 + g}]},
                        {"key": "totals", "outcomes": [{"name": "Over", "price": -108, "point": 220.5 + g}, {"name": "Under", "price": -112, "point": 220.5 + g}]},
                        {"key": "h2h", "outcomes": [{"name": f"Home {g}", "price": -150 - g}, {"name": f"Away {g}", "price": 130 + g}]}]}]})
    return out


def frame(n_games=4, hour=15):
    df = O.parse_odds_api(_events(n_games, hour), "nba", collected_at=f"2026-11-11T{hour:02d}:00:05+00:00")
    df["game_id"] = [f"g{i}" for i in range(len(df))]
    df["raw_sha256"] = "a" * 64
    return df


@pytest.fixture
def db(tmp_path, monkeypatch):
    import psycopg
    name = "mr_int_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"create database {name}")
    url = re.sub(r"dbname=\S+", f"dbname={name}", PG) if "dbname=" in PG else PG + f" dbname={name}"
    c = psycopg.connect(url, autocommit=True)
    for role in ("anon", "authenticated"):
        c.execute(f"do $$ begin create role {role} nologin; exception when duplicate_object then null; end $$")
    c.execute((MIG / "20261111000100_odds_snapshots.sql").read_text())
    c.execute((MIG / "20261111000200_odds_analysis.sql").read_text())
    c.close()
    monkeypatch.setenv("MODELROOM_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("MODELROOM_ODDS_DB_URL", url)
    yield url
    admin.execute(f"drop database {name} with (force)")
    admin.close()


def seed(url, reports=6, comparisons=12):
    conn = S.connect(url)
    S.insert(conn, "nba", frame(4, 15), "t")
    S.insert(conn, "nba", frame(4, 19), "t")  # 24 snapshot rows
    S.insert_payloads(conn, "comparisons", "nba", [(f"c{i}", {"i": i, "x": "é" * (i % 3)}) for i in range(comparisons)], "t")
    for i in range(reports):
        S.insert_payloads(conn, "reports", "nba", [(f"r{i}", {"report": i, "lines": list(range(50 * i))})], "t")
    return conn


def tamper(url, sql, *args):
    import psycopg
    c = psycopg.connect(url, autocommit=True)
    c.execute("set session_replication_role = replica")  # what a superuser bypassing the append-only triggers could do
    c.execute(sql, args)
    c.close()


def both(conn, table):
    """(server result, client result) for the same table."""
    s = S.server_check(conn, table, "nba")
    c = S.verify(conn, "nba") if table == "snapshots" else S.verify_table(conn, table, "nba")
    return s, c


# ------------------------------------------------------------------ clean data: same verdict, same head
def test_clean_chains_server_equals_client(db):
    conn = seed(db)
    for t in S.TABLES:
        s, c = both(conn, t)
        assert s["ok"] and c["ok"], (t, s["problems"], c["problems"])
        assert s["rows"] == c["rows"] and s["head"] == c["head"]


def test_single_read_reproduces_stored_hashes_and_model_input(db):
    conn = seed(db)
    df = S.load_with_hashes(conn, "nba")
    rows = S._rows(conn.cursor(), "nba")
    assert list(df["snapshot_seq"]) == [r["seq"] for r in rows]
    assert list(df["snapshot_hash"]) == [r["row_hash"] for r in rows]          # computed locally == stored
    old = S.frame_from_payloads([r["payload"] for r in rows])                   # what `load` used to return
    pd.testing.assert_frame_equal(S.load(conn, "nba").reset_index(drop=True), old.reset_index(drop=True))


# ------------------------------------------------------------------ tampering: every case caught, by both verifiers
CASES = {
    "corrupted payload": ("update odds.{t} set payload = payload || ' ' where league = 'nba' and seq = 3", "row_hash does not match"),
    "modified payload with re-hashed row (rest of chain kept)":
        ("update odds.{t} set payload = payload || ' ', row_hash = encode(sha256(convert_to(prev_hash || payload || ' ', 'UTF8')), 'hex') "
         "where league = 'nba' and seq = 3", "prev_hash does not match"),
    "missing row": ("delete from odds.{t} where league = 'nba' and seq = 4", "out of sequence"),
    "reordered rows": ("update odds.{t} set seq = case seq when 2 then 5 when 5 then 2 end where league = 'nba' and seq in (2, 5)", "out of sequence"),
    "broken link": ("update odds.{t} set prev_hash = repeat('f', 64) where league = 'nba' and seq = 4", "prev_hash does not match"),
}


@pytest.mark.parametrize("table", S.TABLES)
@pytest.mark.parametrize("case", list(CASES))
def test_tampering_is_caught_server_side_and_client_side(db, table, case):
    conn = seed(db)
    sql, expect = CASES[case]
    if case == "reordered rows":  # swap through a free seq value (unique (league, seq))
        tamper(db, f"update odds.{table} set seq = 100000 where league = 'nba' and seq = 2")
        tamper(db, f"update odds.{table} set seq = 2 where league = 'nba' and seq = 5")
        tamper(db, f"update odds.{table} set seq = 5 where league = 'nba' and seq = 100000")
    else:
        tamper(db, sql.format(t=table))
    s, c = both(conn, table)
    assert not s["ok"], (case, table)
    assert not c["ok"], (case, table)
    assert any(expect in p for p in s["problems"]) or case == "reordered rows", s["problems"]


def test_typed_copy_and_content_key_tampering_caught_on_snapshots(db):
    conn = seed(db)
    tamper(db, "update odds.snapshots set line = line + 0.5 where league = 'nba' and seq = 2")
    s, c = both(conn, "snapshots")
    assert not s["ok"] and not c["ok"]
    assert any("typed columns" in p for p in s["problems"])


def test_content_key_tampering_caught(db):
    conn = seed(db)
    tamper(db, "update odds.snapshots set content_key = content_key || 'x' where league = 'nba' and seq = 7")
    s, c = both(conn, "snapshots")
    assert not s["ok"] and not c["ok"]


def test_null_and_numeric_fields_do_not_raise_false_alarms(db):
    conn = S.connect(db)
    df = frame(3, 15)
    df.loc[0, "line"] = None              # moneyline-style empty line
    df.loc[1, "over_price"] = None
    S.insert(conn, "nba", df, "t")
    s, c = both(conn, "snapshots")
    assert s["ok"] and c["ok"], s["problems"]


# ------------------------------------------------------------------ the checkpoint anchor
def test_checkpoint_catches_a_consistent_rewrite_the_chain_alone_cannot(db):
    """Rewrite report 2 AND re-chain every later row consistently: the chain checks pass, the anchor does not."""
    conn = seed(db)
    first = S.check_and_advance(conn, "reports", "nba", "test")
    assert first["ok"] and first["checkpoint"]["advanced"]
    rows = S.verify_table(conn, "reports", "nba")
    prev = None
    import psycopg
    c = psycopg.connect(db, autocommit=True)
    c.execute("set session_replication_role = replica")
    cur = c.cursor()
    cur.execute("select seq, payload, prev_hash from odds.reports where league = 'nba' order by seq")
    allrows = cur.fetchall()
    prev = S.GENESIS
    for seq, payload, _ in allrows:
        if seq == 2:
            payload = payload.replace('"report":1', '"report":999')
        h = S.chain(prev, payload)
        cur.execute("update odds.reports set payload = %s, prev_hash = %s, row_hash = %s where league = 'nba' and seq = %s",
                    (payload, prev, h, seq))
        prev = h
    c.close()
    assert rows["ok"]
    no_anchor = S.server_check(conn, "reports", "nba")                     # a self-consistent forged chain ...
    assert no_anchor["ok"]
    anchored = S.server_check(conn, "reports", "nba", S.anchor_for(S.read_checkpoints(), "reports", "nba"))
    assert not anchored["ok"] and any("history was rewritten" in p for p in anchored["problems"])  # ... caught by the anchor


def test_checkpoint_catches_truncation_below_it(db):
    conn = seed(db)
    assert S.check_and_advance(conn, "reports", "nba", "test")["ok"]
    tamper(db, "delete from odds.reports where league = 'nba' and seq >= 5")    # tail removed: chain still 'valid'
    res = S.server_check(conn, "reports", "nba", S.anchor_for(S.read_checkpoints(), "reports", "nba"))
    assert not res["ok"] and any("rows were removed" in p for p in res["problems"])


def test_checkpoint_never_advances_on_failure_or_backwards(db):
    conn = seed(db)
    ok = S.check_and_advance(conn, "comparisons", "nba", "test")
    seq = S.anchor_for(S.read_checkpoints(), "comparisons", "nba")["seq"]
    tamper(db, "update odds.comparisons set payload = payload || ' ' where league = 'nba' and seq = 1")
    bad = S.check_and_advance(conn, "comparisons", "nba", "test")
    assert ok["ok"] and not bad["ok"] and not bad["checkpoint"]["advanced"]
    assert S.anchor_for(S.read_checkpoints(), "comparisons", "nba")["seq"] == seq
    assert S.advance_checkpoint("comparisons", "nba", {"ok": True, "rows": 3, "max_seq": 3, "head": "x" * 64}, "t")["advanced"] is False


def test_new_rows_extend_the_checkpoint(db):
    conn = seed(db)
    assert S.check_and_advance(conn, "reports", "nba", "t")["checkpoint"]["seq"] == 6
    S.insert_payloads(conn, "reports", "nba", [("r_new", {"report": "new"})], "t")
    res = S.check_and_advance(conn, "reports", "nba", "t")
    assert res["ok"] and res["anchor"]["ok"] and res["checkpoint"]["seq"] == 7


# ------------------------------------------------------------------ egress: what actually comes back
def test_server_check_downloads_only_a_summary(db):
    conn = seed(db, reports=8)
    S._READ.update(bytes=0, rows=0, queries=0)
    S.server_check(conn, "reports", "nba")
    small = S.bytes_read()["bytes"]
    S._READ.update(bytes=0, rows=0, queries=0)
    S.verify_table(conn, "reports", "nba")
    full = S.bytes_read()["bytes"]
    assert small < 300 and full > 10 * small


def test_missing_keys_returns_only_new_keys_and_insert_dedups(db):
    conn = seed(db)
    cur = conn.cursor()
    assert S.missing_keys(cur, "comparisons", "nba", ["c1", "c2", "new1", "new2", "new1"]) == {"new1", "new2"}
    r = S.insert_payloads(conn, "comparisons", "nba", [("c1", {"i": 1}), ("new1", {"i": "n"}), ("new1", {"i": "n"})], "t")
    assert r["inserted"] == 1
    assert S.insert(conn, "nba", frame(4, 15), "t")["inserted"] == 0
    assert all(S.server_check(conn, t, "nba")["ok"] for t in S.TABLES)


def test_cli_load_sync_reuse_and_report_bytes(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_DATA_DIR", str(tmp_path / "data"))
    seed(db).close()
    out = S.cmd("load", "nba")
    assert out["rows"] == 24 and out["verify"]["ok"] and out["bytes_read"]["bytes"] > 0
    assert S.anchor_for(S.read_checkpoints(), "snapshots", "nba")["seq"] == 24
    # a later collection: sync appends to this refresh's local copy, so the analysis needs no second download
    pd.concat([pd.read_parquet(S.parquet_path("nba")), frame(4, 21)[S.PAYLOAD_FIELDS]]).to_parquet(S.parquet_path("nba"), index=False)
    res = S.cmd("sync", "nba")
    assert res["inserted"] == 12 and res["verify"]["ok"]
    conn = S.connect(db)
    S._READ.update(bytes=0, rows=0, queries=0)
    local = S.local_snapshots(conn, "nba")
    assert len(local) == 36 and S.bytes_read()["bytes"] < 200          # head query only
    assert list(local["snapshot_hash"]) == list(S.load_with_hashes(conn, "nba")["snapshot_hash"])


# ------------------------------------------------------------------ invalid checkpoints: never trusted, never overwritten
@pytest.mark.parametrize("content", ["{not json", '{"reports": {"nba": {"seq": "6", "row_hash": "%s"}}}' % ("a" * 64),
                                     '{"reports": {"nba": {"seq": 6, "row_hash": "xyz"}}}', '{"reports": {"nba": {"seq": 0, "row_hash": "%s"}}}' % ("a" * 64),
                                     '{"reports": {"nba": {"seq": true, "row_hash": "%s"}}}' % ("a" * 64), '["a list"]'])
def test_invalid_checkpoint_fails_safe_and_runs_full_verification(db, content):
    conn = seed(db)
    f = S.checkpoint_path(); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(content)
    res = S.check_and_advance(conn, "reports", "nba", "t")
    assert res["rows"] == 6 and res["max_seq"] == 6                      # every row was still verified
    assert not res["ok"] and any("not trusted" in p for p in res["problems"])
    assert res["checkpoint"]["advanced"] is False and f.read_text() == content   # left exactly as it was


def test_checkpoint_beyond_the_table_means_rows_were_removed(db):
    conn = seed(db)
    S.advance_checkpoint("reports", "nba", {"ok": True, "rows": 9, "max_seq": 9, "head": "b" * 64}, "t")
    res = S.check_and_advance(conn, "reports", "nba", "t")
    assert not res["ok"] and any("rows were removed" in p for p in res["problems"]) and not res["checkpoint"]["advanced"]


def test_anchor_history_catches_a_rewrite_with_a_replaced_checkpoint(db, tmp_path):
    """Rewrite report 2, re-chain everything after it, AND replace the checkpoint file with one matching the forged
    chain: the current check passes, but a checkpoint committed earlier (git history) does not."""
    conn = seed(db)
    S.check_and_advance(conn, "reports", "nba", "t")
    old = tmp_path / "anchors"; old.mkdir(); (old / "2026-11-23T0600.json").write_text(S.checkpoint_path().read_text())
    import psycopg
    c = psycopg.connect(db, autocommit=True); c.execute("set session_replication_role = replica")
    cur = c.cursor(); cur.execute("select seq, payload from odds.reports where league = 'nba' order by seq")
    prev = S.GENESIS
    for seq, payload in cur.fetchall():
        payload = payload.replace('"report":1', '"report":7') if seq == 2 else payload
        h = S.chain(prev, payload)
        c.execute("update odds.reports set payload = %s, prev_hash = %s, row_hash = %s where league = 'nba' and seq = %s", (payload, prev, h, seq))
        prev = h
    c.close()
    S.checkpoint_path().unlink()                                          # the forger replaces the current checkpoint
    S.check_and_advance(conn, "reports", "nba", "forger")
    assert S.server_check(conn, "reports", "nba", S.anchor_for(S.read_checkpoints(), "reports", "nba"))["ok"]
    hist = S.verify_anchor_history(conn, sorted(old.glob("*.json")))
    assert not hist["ok"] and "carries a different hash" in hist["problems"][0]


# ------------------------------------------------------------------ interrupted refreshes
def test_interrupted_insert_rolls_back_and_the_next_refresh_recovers(db):
    conn = seed(db)
    S.check_and_advance(conn, "reports", "nba", "t")
    before = S.anchor_for(S.read_checkpoints(), "reports", "nba")
    real = S.canonical
    calls = {"n": 0}
    def boom(obj):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("runner lost mid-insert")
        return real(obj)
    S.canonical = boom
    try:
        with pytest.raises(RuntimeError):
            S.insert_payloads(conn, "reports", "nba", [("a", {"x": 1}), ("b", {"x": 2})], "t")
    finally:
        S.canonical = real
    after = S.check_and_advance(conn, "reports", "nba", "t")
    assert after["ok"] and after["rows"] == 6                             # nothing half-written: the transaction rolled back
    assert S.anchor_for(S.read_checkpoints(), "reports", "nba")["seq"] == before["seq"]
    assert S.insert_payloads(conn, "reports", "nba", [("a", {"x": 1}), ("b", {"x": 2})], "t")["inserted"] == 2
    assert S.check_and_advance(conn, "reports", "nba", "t")["checkpoint"]["seq"] == 8


def test_rows_written_but_checkpoint_not_saved_is_fine_next_time(db):
    """The refresh inserted rows, then died before committing the checkpoint (or its commit was reverted): the next
    check uses the older anchor, verifies everything, and moves forward."""
    conn = seed(db)
    S.check_and_advance(conn, "reports", "nba", "t")
    saved = S.checkpoint_path().read_text()
    S.insert_payloads(conn, "reports", "nba", [("late", {"x": 1})], "t")
    S.check_and_advance(conn, "reports", "nba", "t")
    S.checkpoint_path().write_text(saved)                                 # the commit with the new checkpoint never landed
    res = S.check_and_advance(conn, "reports", "nba", "t")
    assert res["ok"] and res["anchor"]["seq"] == 6 and res["checkpoint"]["seq"] == 7


# ------------------------------------------------------------------ the daily full verification
def test_daily_full_verification_command(db, tmp_path, monkeypatch):
    monkeypatch.setenv("MODELROOM_ODDS_DB_URL", db)
    seed(db).close()
    conn = S.connect(db)
    for t in S.TABLES:
        S.check_and_advance(conn, t, "nba", "refresh")
    S._READ.update(bytes=0, rows=0, queries=0)
    out = S.cmd("verify", "nba")
    assert out["ok"] and all(out[t]["ok"] and out[t]["anchor"]["ok"] for t in S.TABLES)
    assert out["bytes_read"]["bytes"] < 2000 and all("elapsed_ms" in out[t] for t in S.TABLES)
    full = S.cmd("verify-full", "nba")                                     # manual: also recomputed locally
    assert full["ok"] and all(full[t]["client"]["same_head"] for t in S.TABLES)
    tamper(db, "update odds.comparisons set payload = payload || ' ' where league = 'nba' and seq = 3")
    bad = S.cmd("verify", "nba")
    assert not bad["ok"] and not bad["comparisons"]["ok"]
    anc = tmp_path / "anc"; anc.mkdir(); (anc / "a.json").write_text(S.checkpoint_path().read_text())
    monkeypatch.setenv("MODELROOM_ANCHOR_DIR", str(anc))
    assert S.cmd("verify-anchors", "nba")["ok"]
