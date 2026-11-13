"""Daily scheduler health check for the TEST site (run by .github/workflows/health-check.yml).

Inputs (all read-only, no secrets in any of them):
  status.json    refresh_plan.py status, recomputed now from the refresh log + game times (missed slots, last success)
  runs.json      GitHub Actions runs of the Preview workflow in the last 24 h (REST API)
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


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00").replace(" ", "T", 1))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def evaluate(now: datetime, status: dict, runs: list[dict], supa: dict) -> list[dict]:
    out = []
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
    ap.add_argument("--now")
    ap.add_argument("--apply", action="store_true", help="open / update / close issues (default: dry run, print only)")
    ap.add_argument("--simulate", default="", help="add a synthetic incident with this key (alert-path test)")
    a = ap.parse_args(argv)
    now = _ts(a.now) if a.now else datetime.now(UTC)
    status = json.load(open(a.status))
    runs = json.load(open(a.runs))
    supa = json.load(open(a.supabase))
    inc = evaluate(now, status, runs, supa)
    if a.simulate:
        inc.append({"key": f"test-{a.simulate}", "title": "TEST alert (simulated, not a real problem)",
                    "detail": f"Simulated incident '{a.simulate}' to test the alert path. It closes on the next normal run."})
    summary = summary_of(now, status, runs, supa)
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
