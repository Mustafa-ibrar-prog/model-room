"""Report for the one-time TEST Supabase archive dry run (Moose, approved 2026-11-24). Pure: reads the JSON files the
workflow collected and writes a Markdown report plus a pass/fail verdict. Nothing here touches Supabase or R2.

Inputs (all optional except auth; a missing input is reported as a failed check, never guessed):
  auth.json        {"status": 200}                                   Supabase API answering normally
  storage.json     scripts/supabase-storage.sql                      database size, largest tables
  projection.json  scripts/archive-projection.sql                    closed-segment rows and shares per table
  verify_<lg>.json python -m modelroom odds-store verify             server-side chain checks, both leagues
  readonly.json    python -m modelroom.archive.readonly_verify       the 26 archived ledgers, read-only token
  egress.json      {"bytes_24h", "runs_counted", "loads": [{league, bytes, rows}]}   refresh byte counters
  app.json         {"archive_read_flag", "last_refresh": {conclusion, created_at}}

    python -m modelroom.archive.dryrun_report --dir /tmp/dry > report.md   (exit 1 when any check fails)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MB = 1_000_000
DB_LIMIT = 500 * MB
EXPECTED_LEDGERS = 26


def _load(d: Path, name: str):
    f = d / name
    try:
        return json.loads(f.read_text()) if f.exists() else None
    except Exception:  # noqa: BLE001
        return {"_unreadable": True}


def build(d: Path) -> tuple[str, bool]:
    auth, st, pj, ro, eg, app = (_load(d, n) for n in ("auth.json", "storage.json", "projection.json", "readonly.json", "egress.json", "app.json"))
    ver = {lg: _load(d, f"verify_{lg}.json") for lg in ("nba", "nfl")}
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Supabase API available (restriction cleared)", bool(auth) and auth.get("status") == 200,
                   f"Auth health answered HTTP {(auth or {}).get('status')}"))
    db = (st or {}).get("db_bytes")
    checks.append(("Database size read", db is not None, f"{db / MB:.1f} MB of {DB_LIMIT / MB:.0f} MB ({db / DB_LIMIT:.0%})" if db else "not read"))
    for lg, v in ver.items():
        ok = bool(v) and all((v.get(t) or {}).get("ok") for t in ("snapshots", "comparisons", "reports"))
        det = "; ".join(f"{t} {(v or {}).get(t, {}).get('rows')} rows, chain {'ok' if (v or {}).get(t, {}).get('ok') else 'FAILED'}"
                        f", anchor {'ok' if ((v or {}).get(t, {}).get('anchor') or {}).get('ok', True) else 'FAILED'}" for t in ("snapshots", "comparisons", "reports"))
        checks.append((f"Store chains intact ({lg.upper()}, checked in the database)", ok, det if v else "not run"))
    ro_ok = bool(ro) and ro.get("ok") and ro.get("files") == EXPECTED_LEDGERS and not ro.get("unexpected_objects")
    checks.append(("26 archived ledgers verified from R2 with the read-only token", bool(ro_ok),
                   (f"{ro.get('files')} files, {ro.get('objects_listed')} objects listed ({ro.get('objects_expected')} expected), "
                    f"{(ro.get('bytes_original') or 0) / MB:.1f} MB original, {(ro.get('bytes_stored') or 0) / MB:.1f} MB stored; "
                    f"problems: {ro.get('problems') or 'none'}") if ro else "not run"))
    if ro and ro.get("rows"):
        names = ("size_matches_manifest", "stored_sha256_matches_upload", "original_size_matches", "original_sha256_matches_manifest",
                 "identical_to_git_source", "chain_head_matches", "loads_with_ledger_reader")
        for n in names:
            have = [r for r in ro["rows"] if n in r["checks"]]
            checks.append((f"  every ledger: {n.replace('_', ' ')}", bool(have) and all(r["checks"][n] for r in have), f"{sum(r['checks'][n] for r in have)}/{len(have)}"))
    app_ok = bool(app) and app.get("archive_read_flag") == "off" and (app.get("last_refresh") or {}).get("conclusion") == "success"
    checks.append(("App unchanged: archive reads off, latest refresh succeeded", app_ok,
                   f"MODELROOM_ARCHIVE_READ={(app or {}).get('archive_read_flag')}; latest refresh "
                   f"{(app or {}).get('last_refresh', {}).get('conclusion')} at {(app or {}).get('last_refresh', {}).get('created_at')}" if app else "not checked"))

    lines = ["# Supabase archive dry run (TEST)", "", "Read-only. Nothing was written to, deleted from or migrated out of Supabase; "
             "archive reads stayed off; production and model versions untouched.", "", "## Checks", "", "| Check | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {det} |" for n, ok, det in checks]

    # Projected savings
    lines += ["", "## Projected savings (if archive reads were turned on later; needs separate approval)", ""]
    if pj and pj.get("odds"):
        lines += ["| Table | League | Rows | In closed segments | Tail left in Supabase | Table size | Share archivable | Storage that could be freed* |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        free = 0.0
        for r in pj["odds"]:
            f = r["table_bytes"] * float(r["closed_share"] or 0)
            free += f
            lines.append(f"| odds.{r['table']} | {r['league']} | {r['rows']} | {r['closed_rows']} | {r['tail_rows']} | {r['table_bytes'] / MB:.1f} MB "
                         f"| {float(r['closed_share'] or 0):.0%} | {f / MB:.1f} MB |")
        a = pj.get("audit") or {}
        if a:
            fa = (a.get("table_bytes") or 0) * float(a.get("closed_share") or 0)
            free += fa
            lines.append(f"| odds.potd_model_outputs (audit) | nba | {a.get('rows')} | {a.get('closed_rows')} (closed days) | {a.get('rows', 0) - a.get('closed_rows', 0)} "
                         f"| {(a.get('table_bytes') or 0) / MB:.1f} MB | {float(a.get('closed_share') or 0):.0%} | {fa / MB:.1f} MB |")
        dbb = pj.get("db_bytes") or db or 0
        lines += ["", f"Storage: up to **{free / MB:.1f} MB** of the {dbb / MB:.1f} MB database could be freed (database would drop to about "
                  f"{max(dbb - free, 0) / MB:.1f} MB). *Only by deleting the archived source rows from Supabase, which this dry run does not do "
                  "and which needs your approval; until then archiving adds safety, not space."]
    else:
        lines.append("Projection not available.")
    if eg and eg.get("loads"):
        snap = {r["league"]: r for r in (pj or {}).get("odds", []) if r["table"] == "snapshots"}
        cut = 0.0
        for ld in eg["loads"]:
            s = snap.get(ld["league"])
            if s and s["rows"]:
                cut += ld["bytes"] * (s["closed_rows"] / s["rows"])
        day = eg.get("bytes_24h") or 0
        lines += ["", f"Egress: refreshes read {day / MB:.1f} MB from Supabase in the last 24 h ({eg.get('runs_counted')} runs, about "
                  f"{day * 30 / MB / 1000:.2f} GB a month). With archive reads, the closed snapshot segments would come from R2 (free egress) "
                  f"instead: about **{cut / MB:.1f} MB a day less** (about {cut * 30 / MB / 1000:.2f} GB a month), leaving about "
                  f"{max(day - cut, 0) * 30 / MB / 1000:.2f} GB a month. Site, Auth and dashboard traffic are not in these counters."]
    else:
        lines += ["", "Egress: no refresh byte counters available for the last 24 h."]
    ok = all(c[1] for c in checks)
    lines += ["", f"**Verdict: {'all checks passed' if ok else 'STOPPED: at least one check failed (see FAIL rows); nothing further was run'}.**",
              "", "Next steps (each needs your approval): turn on archive reads for the refresh (MODELROOM_ARCHIVE_READ=on, TEST); "
              "archive closed odds segments to R2 (mode run, with Supabase); only later, and separately, consider removing archived rows from Supabase."]
    return "\n".join(lines) + "\n", ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    a = ap.parse_args(argv)
    text, ok = build(Path(a.dir))
    sys.stdout.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
