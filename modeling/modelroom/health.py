"""Daily scheduler health check for the TEST site (run by .github/workflows/health-check.yml).

Inputs (all read-only, no secrets in any of them):
  status.json    refresh_plan.py status, recomputed now from the refresh log + game times (missed slots, last success)
  runs.json      GitHub Actions runs of the Preview workflow in the last 24 h (REST API)
  auth.json      optional: {"status": <HTTP status of GET /auth/v1/health>, "reason": <402 restriction token or null>}
  supabase.json  one row of scheduler.health (last dispatch / last accepted, failures, token present yes/no), or
                 {"ok": false} if the database couldn't be reached

Incidents (one GitHub issue per incident type, label "health-alert"):
  stale-refresh       latest successful refresh older than 3 hours
  missed-slots        an expected refresh slot (daily or game) closed without a successful run
  workflow-failures   a Preview run failed / was cancelled / timed out in the last 24 h
  workflow-stuck      a Preview run has been queued or running for over 60 minutes
  supabase-dispatch   the scheduler is off, has no token, logged dispatch failures, or hasn't had a dispatch
                      accepted by GitHub in the last 20 minutes
  supabase-unreachable  the health view couldn't be read
  supabase-api        Supabase's API (Auth) answered with an error, e.g. HTTP 402 = project restricted for going over
                      its plan's quota or an overdue bill: every login fails while the database still looks fine
  supabase-db-size    database size at or above 70 % of the plan limit (500 MB on Free), or forecast to reach the
                      limit within 30 days at the last 7 days' growth rate
  supabase-audit-growth  the Pick of the Day audit table (odds.potd_model_outputs) is growing more than 5 MB a day
  supabase-egress     pipeline reads from the database (measured by the refresh's own byte counters over the last
                      24 h) project to more than 3 GB a month: 60 % of the Free plan's 5 GB, leaving room for site,
                      Auth and dashboard traffic, which these counters don't see

  storage.json   optional: output of scripts/supabase-storage.sql (database size, largest tables with 7-day growth
                 share, Storage objects, audit rows per day), or {"ok": false}
  egress.json    optional: {"bytes_24h", "runs", "runs_counted"} summed from the "store bytes read:" lines of the last
                 24 h of Preview runs

No duplicate alerts: an incident that is already open only has its issue body refreshed (an edit, which sends no
notification); a new issue is opened only for an incident type with no open issue; an open issue whose incident has
cleared is closed with a short note. Pure functions (evaluate, plan) are unit-tested; apply() talks to GitHub.

    python3 modelroom/health.py --status status.json --runs runs.json --supabase supabase.json [--apply] [--simulate KEY]
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import UTC, datetime, timedelta

LABEL = "health-alert"
PREFIX = "[health]"
STALE_AFTER = timedelta(hours=3)
STUCK_AFTER = timedelta(minutes=60)
# A wake time that passed this long ago without a dispatch means the scheduler is not firing.
OVERDUE_MINUTES = 20
BAD = {"failure", "cancelled", "timed_out", "startup_failure"}
MB = 1_000_000
DB_LIMIT = int(os.environ.get("MODELROOM_DB_LIMIT_BYTES", 500 * MB))       # Supabase Free plan database size
DB_WARN_SHARE = 0.70
FORECAST_DAYS = 30
AUDIT_TABLE = "odds.potd_model_outputs"
AUDIT_MB_PER_DAY = 5.0
EGRESS_QUOTA = 5_000 * MB                                                   # Free plan, uncached, per billing cycle
EGRESS_ALERT = 3_000 * MB


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00").replace(" ", "T", 1))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def evaluate(now: datetime, status: dict, runs: list[dict], supa: dict, auth: dict | None = None) -> list[dict]:
    out = []
    if auth is not None and auth.get("status") != 200:
        st = auth.get("status")
        if st == 402:
            detail = (f"Supabase has restricted the TEST project (HTTP 402: {auth.get('reason') or 'reason not given'}). Every login on the "
                      "TEST site fails until usage is back under the plan's quota or the bill is paid; resetting passwords will not help. "
                      "Check Supabase → Organization → Usage.")
        else:
            detail = f"Supabase's Auth API health check answered {st if st is not None else 'nothing (unreachable)'}; logins on the TEST site may fail."
        out.append({"key": "supabase-api", "title": "Supabase API is restricted or failing (logins affected)", "detail": detail})
    last = _ts((status.get("last_success") or {}).get("at"))
    if last is None or now - last > STALE_AFTER:
        age = "never" if last is None else f"{(now - last).total_seconds() / 3600:.1f} h ago"
        out.append({"key": "stale-refresh", "title": "Latest successful refresh is older than 3 hours",
                    "detail": f"Last successful refresh: {age} ({(status.get('last_success') or {}).get('slot')})."})
    missed = status.get("missed") or []
    if missed:
        out.append({"key": "missed-slots", "title": "Expected refresh slot(s) missed",
                    "detail": "Slots whose window closed without a successful run:\n" + "\n".join(f"- {m}" for m in missed)})
    recent = [r for r in runs if (_ts(r.get("created_at")) or now) >= now - timedelta(hours=24)]
    failed = [r for r in recent if r.get("conclusion") in BAD]
    if failed:
        out.append({"key": "workflow-failures", "title": "Preview workflow run(s) failed in the last 24 h",
                    "detail": "\n".join(f"- {r.get('created_at')} {r.get('event')} → {r.get('conclusion')} (run {r.get('id')})" for r in failed[:20])})
    stuck = [r for r in recent if r.get("status") in ("queued", "in_progress", "waiting", "pending")
             and now - (_ts(r.get("created_at")) or now) > STUCK_AFTER]
    if stuck:
        out.append({"key": "workflow-stuck", "title": "Preview workflow run(s) queued or running for over 60 minutes",
                    "detail": "\n".join(f"- {r.get('created_at')} {r.get('event')} {r.get('status')} (run {r.get('id')})" for r in stuck[:20])})
    if not supa.get("ok", True) or "enabled" not in supa:
        out.append({"key": "supabase-unreachable", "title": "Supabase scheduler health couldn't be read",
                    "detail": f"The health check couldn't read scheduler.health ({supa.get('error', 'no data')}). Dispatches may still be running."})
    else:
        why = []
        if str(supa.get("enabled")) != "on":
            why.append(f"scheduler switched {supa.get('enabled')}")
        if not supa.get("token_stored"):
            why.append("no GitHub token in Vault")
        if int(supa.get("failures_24h") or 0) > 0:
            why.append(f"{supa.get('failures_24h')} dispatch failure(s) in the last 24 h")
        # The scheduler now dispatches only when a refresh slot is due, so long quiet stretches are normal and a
        # dispatch every few minutes is not. What matters instead: has a wake time passed without a dispatch, has
        # any run reported back lately, and are dispatches going unanswered.
        la = _ts(supa.get("last_accepted"))
        overdue = supa.get("minutes_overdue")
        if overdue is not None and float(overdue) > OVERDUE_MINUTES:
            why.append(f"a refresh was due {int(float(overdue))} minutes ago and no run has started"
                       + (f" (last accepted dispatch {la.isoformat(timespec='minutes')})" if la else ""))
        if supa.get("plan_stale"):
            pu = _ts(supa.get("plan_updated_at"))
            why.append("no refresh run has reported to the scheduler for over 6 hours"
                       + (f" (last {pu.isoformat(timespec='minutes')})" if pu else ""))
        if int(supa.get("dispatches_since_update") or 0) >= 12:
            why.append(f"{supa.get('dispatches_since_update')} dispatches with no run reporting back")
        if la is None and not supa.get("plan_stale"):
            why.append("no dispatch has ever been accepted by GitHub")
        if why:
            out.append({"key": "supabase-dispatch", "title": "Supabase refresh dispatch is not healthy", "detail": "; ".join(why) + "."})
    return out


def growth(storage: dict) -> dict:
    """Bytes a day per table and in total, from each table's size × the share of its row data inserted in the last 7
    days ÷ 7, plus the forecast to the database limit. Tables without a time column count as not growing."""
    per = []
    for t in storage.get("tables") or []:
        sh = t.get("share_7d")
        if sh is None:
            continue
        age = t.get("age_days")
        days = min(7.0, max(float(age), 0.5)) if age is not None else 7.0     # a table younger than 7 days: its real age
        per.append({"name": t["name"], "bytes": int(t["bytes"]), "per_day": int(t["bytes"]) * float(sh) / days})
    per.sort(key=lambda x: -x["per_day"])
    total = sum(x["per_day"] for x in per)
    db = int(storage.get("db_bytes") or 0)
    days = (DB_LIMIT - db) / total if total > 0 and db < DB_LIMIT else (0 if db >= DB_LIMIT else None)
    audit = next((x for x in per if x["name"] == AUDIT_TABLE), None)
    return {"per_table": per, "per_day": total, "db_bytes": db, "limit": DB_LIMIT, "days_to_limit": days,
            "audit_per_day": audit["per_day"] if audit else None, "audit_bytes": audit["bytes"] if audit else None}


def evaluate_storage(storage: dict | None, egress: dict | None) -> list[dict]:
    out = []
    if storage is not None and storage.get("db_bytes") is not None:
        g = growth(storage)
        db, share = g["db_bytes"], g["db_bytes"] / DB_LIMIT
        days = g["days_to_limit"]
        why = []
        if share >= DB_WARN_SHARE:
            why.append(f"the database is {db / MB:.0f} MB, {share:.0%} of the {DB_LIMIT / MB:.0f} MB limit")
        if days is not None and days < FORECAST_DAYS:
            why.append(f"at the last 7 days' rate (+{g['per_day'] / MB:.1f} MB a day) it reaches the limit in about {days:.0f} days")
        if why:
            top = ", ".join(f"{x['name']} +{x['per_day'] / MB:.1f} MB/day" for x in g["per_table"][:3])
            out.append({"key": "supabase-db-size", "title": "Supabase database is approaching its size limit",
                        "detail": "; ".join(why).capitalize() + f". Fastest-growing tables: {top or 'none measured'}. Over the limit the "
                                  "project goes read-only. Nothing is deleted automatically; see the retention options in the infrastructure report."})
        if g["audit_per_day"] is not None and g["audit_per_day"] / MB > AUDIT_MB_PER_DAY:
            out.append({"key": "supabase-audit-growth", "title": "Pick of the Day audit table is growing fast",
                        "detail": f"{AUDIT_TABLE} is {g['audit_bytes'] / MB:.0f} MB and growing about {g['audit_per_day'] / MB:.1f} MB a day "
                                  f"(threshold {AUDIT_MB_PER_DAY:.0f} MB). The table is append-only and is not changed by this check."})
    if egress is not None and egress.get("bytes_24h") is not None:
        month = float(egress["bytes_24h"]) * 30
        if month > EGRESS_ALERT:
            out.append({"key": "supabase-egress", "title": "Supabase egress is on course to pass 3 GB this month",
                        "detail": f"Refresh reads in the last 24 h: {egress['bytes_24h'] / MB:.1f} MB over {egress.get('runs_counted')} run(s), "
                                  f"about {month / MB / 1000:.1f} GB a month against the Free plan's {EGRESS_QUOTA / MB / 1000:.0f} GB. Site, "
                                  "Auth and dashboard traffic come on top; Supabase → Organization → Usage is the exact figure."})
    return out


def storage_summary(storage: dict | None, egress: dict | None) -> str:
    lines = []
    if storage is None or storage.get("db_bytes") is None:
        lines.append(f"- Database storage: not read ({(storage or {}).get('error', 'no data')})")
    else:
        g = growth(storage)
        d = g["days_to_limit"]
        lines.append(f"- Database: {g['db_bytes'] / MB:.1f} MB of {DB_LIMIT / MB:.0f} MB ({g['db_bytes'] / DB_LIMIT:.0%}), "
                     f"+{g['per_day'] / MB:.2f} MB a day, limit in {'n/a' if d is None else f'{d:.0f} days'}")
        lines.append("- Largest tables: " + ", ".join(f"{t['name']} {int(t['bytes']) / MB:.1f} MB" for t in (storage.get("tables") or [])[:6]))
        lines.append("- Growth by table (last 7 days): " + (", ".join(f"{x['name']} +{x['per_day'] / MB:.2f} MB/day" for x in g["per_table"][:6]) or "none measured"))
        if g["audit_per_day"] is not None:
            lines.append(f"- Audit table {AUDIT_TABLE}: {g['audit_bytes'] / MB:.1f} MB, +{g['audit_per_day'] / MB:.2f} MB a day")
        lines.append(f"- Storage (files): {int(storage.get('storage_bytes') or 0) / MB:.1f} MB in {storage.get('storage_objects')} object(s)")
    if egress is not None and egress.get("bytes_24h") is not None:
        lines.append(f"- Refresh egress, last 24 h: {egress['bytes_24h'] / MB:.1f} MB over {egress.get('runs_counted')} of {egress.get('runs')} run(s) "
                     f"(≈ {egress['bytes_24h'] * 30 / MB / 1000:.2f} GB a month; site and Auth traffic not included)")
    return "\n".join(lines)


def plan(incidents: list[dict], open_issues: list[dict]) -> list[dict]:
    """open_issues: GitHub issues with the health-alert label: [{number, title, body}]. Returns actions."""
    def key_of(issue):
        t = issue.get("title", "")
        return t[len(PREFIX):].split("]")[0].strip(" [") if t.startswith(PREFIX + " [") else None

    open_by_key = {}
    for i in open_issues:
        k = key_of(i)
        if k and k not in open_by_key:
            open_by_key[k] = i
    acts = []
    keys = set()
    for inc in incidents:
        keys.add(inc["key"])
        if inc["key"] in open_by_key:
            acts.append({"action": "update", "number": open_by_key[inc["key"]]["number"], "incident": inc})
        else:
            acts.append({"action": "open", "incident": inc})
    for k, i in open_by_key.items():
        if k not in keys:
            acts.append({"action": "close", "number": i["number"], "key": k})
    return acts


def title_of(inc: dict) -> str:
    return f"{PREFIX} [{inc['key']}] {inc['title']}"


def body_of(inc: dict, now: datetime, summary: str) -> str:
    return (f"{inc['detail']}\n\n**Checked:** {now.isoformat(timespec='minutes')} (TEST site health check; refreshes are not "
            f"affected by this check).\n\n<details><summary>System summary</summary>\n\n{summary}\n</details>\n\n"
            "This issue stays open (and is updated silently) while the problem continues, and closes itself when it clears.")


def summary_of(now: datetime, status: dict, runs: list[dict], supa: dict) -> str:
    last = (status.get("last_success") or {})
    recent = [r for r in runs if (_ts(r.get("created_at")) or now) >= now - timedelta(hours=24)]
    by = {}
    for r in recent:
        by[r.get("conclusion") or r.get("status")] = by.get(r.get("conclusion") or r.get("status"), 0) + 1
    s = {k: supa.get(k) for k in ("enabled", "token_stored", "last_dispatch", "last_accepted", "failures_24h", "no_token_notes_24h",
                                  "awaiting_response", "next_check_at", "next_check_reason", "plan_updated_at",
                                  "dispatches_since_update", "minutes_overdue")} if supa.get("ok", True) else {"reachable": False}
    return (f"- Last successful refresh: {last.get('at')} ({last.get('slot')})\n- Missed slots: {len(status.get('missed') or [])}\n"
            f"- Preview runs in the last 24 h: {len(recent)} {json.dumps(by)}\n- Supabase scheduler: {json.dumps(s, default=str)}")


# ------------------------------------------------------------------ GitHub
def _gh(method: str, path: str, body: dict | None = None):
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "model-room-health"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def open_alerts() -> list[dict]:
    items = _gh("GET", f"/issues?state=open&labels={LABEL}&per_page=100") or []
    return [{"number": i["number"], "title": i["title"], "body": i.get("body") or ""} for i in items if "pull_request" not in i]


def apply(actions: list[dict], now: datetime, summary: str) -> list[str]:
    done = []
    for a in actions:
        if a["action"] == "open":
            r = _gh("POST", "/issues", {"title": title_of(a["incident"]), "body": body_of(a["incident"], now, summary), "labels": [LABEL]})
            done.append(f"opened #{r['number']} {a['incident']['key']}")
        elif a["action"] == "update":
            _gh("PATCH", f"/issues/{a['number']}", {"body": body_of(a["incident"], now, summary)})
            done.append(f"updated #{a['number']} {a['incident']['key']} (no new alert)")
        elif a["action"] == "close":
            _gh("POST", f"/issues/{a['number']}/comments", {"body": f"Cleared at {now.isoformat(timespec='minutes')}: the health check no longer sees this problem."})
            _gh("PATCH", f"/issues/{a['number']}", {"state": "closed", "state_reason": "completed"})
            done.append(f"closed #{a['number']} {a['key']}")
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--supabase", required=True)
    ap.add_argument("--auth", default="", help="auth.json from the Auth API probe (optional)")
    ap.add_argument("--storage", default="", help="storage.json from scripts/supabase-storage.sql (optional)")
    ap.add_argument("--egress", default="", help="egress.json summed from the Preview runs' byte counters (optional)")
    ap.add_argument("--now")
    ap.add_argument("--apply", action="store_true", help="open / update / close issues (default: dry run, print only)")
    ap.add_argument("--simulate", default="", help="add a synthetic incident with this key (alert-path test)")
    a = ap.parse_args(argv)
    now = _ts(a.now) if a.now else datetime.now(UTC)
    status = json.load(open(a.status))
    runs = json.load(open(a.runs))
    supa = json.load(open(a.supabase))
    auth = json.load(open(a.auth)) if a.auth and os.path.exists(a.auth) else None
    storage = json.load(open(a.storage)) if a.storage and os.path.exists(a.storage) else None
    egress = json.load(open(a.egress)) if a.egress and os.path.exists(a.egress) else None
    inc = evaluate(now, status, runs, supa, auth) + evaluate_storage(storage, egress)
    if a.simulate:
        inc.append({"key": f"test-{a.simulate}", "title": "TEST alert (simulated, not a real problem)",
                    "detail": f"Simulated incident '{a.simulate}' to test the alert path. It closes on the next normal run."})
    summary = summary_of(now, status, runs, supa) + "\n" + storage_summary(storage, egress)
    report = {"checked_at": now.isoformat(timespec="seconds"), "incidents": [i["key"] for i in inc], "summary": summary}
    if a.apply:
        acts = plan(inc, open_alerts())
        report["actions"] = apply(acts, now, summary)
    else:
        report["actions (dry run)"] = [f"{x['action']} {x.get('incident', {}).get('key') or x.get('key')}" for x in plan(inc, [])]
    print(json.dumps(report, indent=1))
    gs = os.environ.get("GITHUB_STEP_SUMMARY")
    if gs:
        with open(gs, "a") as f:
            f.write(f"### Model Room health check ({now.isoformat(timespec='minutes')})\n\nIncidents: {', '.join(report['incidents']) or 'none'}\n\n{summary}\n\n"
                    f"Actions: {', '.join(report.get('actions') or report.get('actions (dry run)') or []) or 'none'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
