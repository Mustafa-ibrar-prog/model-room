"""Weekly ledger series: new records go to the current week's file (own hash chain), deduplicated against the whole
series; the original file is never touched; reading the series returns every record."""
import hashlib
from datetime import datetime, timezone

import pytest

from modelroom.common import ledger as L


def rec(gid, ih="a", v="0.1.1", start="2026-11-20T18:00:00+00:00", gen="2026-11-08T05:00:00+00:00"):
    return {"game_id": gid, "model_version": v, "inputs_hash": ih, "params_hash": "p", "generated_at": gen, "game_start": start}


def test_weekly_series(tmp_path):
    base = tmp_path / "nfl_props.jsonl"
    L.append(base, [rec("g1"), rec("g2")])
    original = hashlib.sha256(base.read_bytes()).hexdigest()
    w45 = datetime(2026, 11, 8, 5, tzinfo=timezone.utc)
    r = L.append_weekly(base, w45, [rec("g1"), rec("g3")])           # g1 already in the original file
    assert (r.appended, r.skipped_duplicate) == (1, 1)
    r = L.append_weekly(base, w45, [rec("g3"), rec("g1", ih="b")])  # g3 already this week; g1 with new inputs
    assert (r.appended, r.skipped_duplicate) == (1, 1)
    w46 = datetime(2026, 11, 10, 5, tzinfo=timezone.utc)
    r = L.append_weekly(base, w46, [rec("g3"), rec("g4")])           # dedupe against earlier weeks too
    assert (r.appended, r.skipped_duplicate) == (1, 1)
    assert hashlib.sha256(base.read_bytes()).hexdigest() == original  # original untouched
    files = [f.name for f in L.series_files(base)]
    assert files == ["nfl_props.jsonl", "nfl_props_week_2026-W45.jsonl", "nfl_props_week_2026-W46.jsonl"]
    assert L.verify_series(base) == {"nfl_props.jsonl": 2, "nfl_props_week_2026-W45.jsonl": 2, "nfl_props_week_2026-W46.jsonl": 1}
    assert [x["game_id"] for x in L.read_series(base)] == ["g1", "g2", "g3", "g1", "g4"]
    # each weekly file is its own chain starting at seq 1
    assert [x["seq"] for x in L.read(tmp_path / "nfl_props_week_2026-W46.jsonl")] == [1]


def test_tampering_in_weekly_file_detected(tmp_path):
    base = tmp_path / "nfl_props.jsonl"
    L.append_weekly(base, datetime(2026, 11, 8, tzinfo=timezone.utc), [rec("g1"), rec("g2")])
    f = tmp_path / "nfl_props_week_2026-W45.jsonl"
    f.write_text(f.read_text().replace('"g1"', '"gX"'))
    with pytest.raises(L.LedgerError):
        L.verify_series(base)


def test_other_series_not_mixed(tmp_path):
    base = tmp_path / "nba_props.jsonl"
    L.append(base, [rec("g1")])
    L.append(tmp_path / "nba_props_shadow_0.2.3a_2026-W45.jsonl", [rec("g1", v="0.2.3a")])
    assert [f.name for f in L.series_files(base)] == ["nba_props.jsonl"]   # NBA shadow files are not part of nba_props
