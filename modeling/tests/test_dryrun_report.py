"""Supabase archive dry-run report: verdict and projections come only from the collected inputs."""
import json

from modelroom.archive import dryrun_report as D

ROWS = [{"file": f"f{i}.jsonl", "checks": {k: True for k in ("size_matches_manifest", "stored_sha256_matches_upload", "original_size_matches",
        "original_sha256_matches_manifest", "identical_to_git_source", "chain_head_matches", "loads_with_ledger_reader")}} for i in range(26)]


def _write(d, **files):
    for k, v in files.items():
        (d / k).write_text(json.dumps(v))


def _good(d):
    ver = {t: {"rows": 10, "ok": True, "anchor": {"ok": True}} for t in ("snapshots", "comparisons", "reports")}
    _write(d, **{"auth.json": {"status": 200}, "storage.json": {"db_bytes": 150_000_000}, "verify_nba.json": ver, "verify_nfl.json": ver,
                 "readonly.json": {"ok": True, "files": 26, "objects_listed": 27, "objects_expected": 27, "unexpected_objects": [], "bytes_original": 1, "bytes_stored": 1, "rows": ROWS},
                 "projection.json": {"db_bytes": 150_000_000, "odds": [{"table": "snapshots", "league": "nba", "rows": 5000, "closed_rows": 4000, "tail_rows": 1000,
                                                                       "table_bytes": 30_000_000, "closed_share": 0.5}],
                                     "audit": {"rows": 100, "closed_rows": 80, "table_bytes": 20_000_000, "closed_share": 0.8}},
                 "egress.json": {"bytes_24h": 50_000_000, "runs_counted": 8, "loads": [{"league": "nba", "bytes": 2_000_000, "rows": 5000}]},
                 "app.json": {"archive_read_flag": "off", "last_refresh": {"conclusion": "success", "created_at": "x"}}})


def test_all_good_passes_with_projection(tmp_path):
    _good(tmp_path)
    text, ok = D.build(tmp_path)
    assert ok and "all checks passed" in text
    assert "up to **31.0 MB**" in text                  # 30 x 0.5 + 20 x 0.8
    assert "about **1.6 MB a day less**" in text         # 2 MB x 4000/5000


def test_restricted_or_failed_check_stops(tmp_path):
    _good(tmp_path)
    _write(tmp_path, **{"auth.json": {"status": 402}})
    text, ok = D.build(tmp_path)
    assert not ok and "STOPPED" in text


def test_missing_ledger_or_bad_checksum_fails(tmp_path):
    _good(tmp_path)
    bad = [dict(r, checks=dict(r["checks"], identical_to_git_source=False)) if i == 0 else r for i, r in enumerate(ROWS)]
    _write(tmp_path, **{"readonly.json": {"ok": False, "files": 26, "objects_listed": 27, "objects_expected": 27, "unexpected_objects": [], "rows": bad, "problems": ["f0"]}})
    assert not D.build(tmp_path)[1]
    (tmp_path / "readonly.json").unlink()
    assert not D.build(tmp_path)[1]


def test_archive_reads_on_is_a_failure(tmp_path):
    _good(tmp_path)
    _write(tmp_path, **{"app.json": {"archive_read_flag": "on", "last_refresh": {"conclusion": "success"}}})
    assert not D.build(tmp_path)[1]
