"""Official settlement of exchange markets, as the exchange reports it. Never inferred from a box score.

    python -m modelroom markets settle nfl        (also run by `markets refresh`)

For every contract the model priced before its game, once the game has started, ask the provider for the
market's status and record what it says, append-only:

  data/markets/settlements/<league>.jsonl      one observation per change (local; data/ is gitignored)

A new observation is written only when the provider's state changes, so re-running is harmless. If a
settled result later changes (a dispute or correction), the new state is recorded with `correction` set and
the earlier observation is kept: that is the audit trail.

State, from the provider's own fields (field names checked against live settled markets 2026-11-02):

  Kalshi       status finalized + result yes/no              → settled yes / no (settlement_ts)
               finalized with a settlement value strictly between 0 and 1, or result "scalar"/void
                                                              → void (settled at that value; e.g. refunded)
               determined / amended                          → pending ("result determined; settlement window open")
               disputed                                       → pending ("disputed")
               initialized / active / inactive / closed       → pending
  Polymarket   status MARKET_STATUS_RESOLVED, long-side value 1 / 0 → settled yes / no
  US           resolved at a value strictly between 0 and 1   → void (settled at last fair price, e.g. no snap)
               a status naming cancel / void                  → void (no value)
               anything else, or values that disagree        → pending (never guessed)

Polymarket US publishes no settlement timestamp; its market `updatedAt` at resolution is recorded instead
(marked as such).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from modelroom.common.paths import data_root, ensure

from . import config, kalshi, polymarket_us, snapshots
from .http import ProviderError

RECHECK_SETTLED_HOURS = 72     # keep watching settled markets this long for corrections
PENDING_RECHECK_MIN = 30       # don't ask about the same unsettled market more often than this


def path(league: str) -> Path:
    return data_root() / "markets" / "settlements" / f"{league}.jsonl"


def load(league: str) -> pd.DataFrame:
    f = path(league)
    if not f.exists():
        return pd.DataFrame()
    return pd.DataFrame([json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()])


def _num(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _list(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    return v if isinstance(v, list) else None


def _value_state(value: float | None) -> tuple[str, str | None]:
    if value is None:
        return "pending", None
    if abs(value - 1) < 1e-9:
        return "settled", "yes"
    if abs(value) < 1e-9:
        return "settled", "no"
    return "settled", "void"


# ------------------------------------------------------------------ provider parsing
def parse_kalshi(m: dict) -> dict:
    st = (m.get("status") or "").lower()
    res = (m.get("result") or "").lower()
    val = _num(m.get("settlement_value_dollars"))
    obs = {"provider": "kalshi", "market_id": m.get("ticker"), "provider_status": st, "settled_at": m.get("settlement_ts") or None,
           "settled_at_source": "settlement_ts", "value": val, "state": "pending", "result": None, "note": None}
    if st in ("finalized", "settled"):
        if res in ("yes", "no") and (val is None or abs(val - (1.0 if res == "yes" else 0.0)) < 1e-9):
            obs.update(state="settled", result=res)
        elif val is not None and 0 < val < 1:
            obs.update(state="settled", result="void", note=f"settled at {val:.2f} (refund / fair value)")
        elif res in ("void", "scalar"):
            obs.update(state="settled", result="void", note=f"result {res}")
        else:
            obs["note"] = "finalized but the result fields are inconsistent; not graded"
    elif st in ("determined", "amended"):
        obs["note"] = f"result determined ({res or 'unpublished'}); settlement window open" if st == "determined" else "re-determined after a dispute; settlement window open"
    elif st == "disputed":
        obs["note"] = "disputed"
    return obs


def parse_polymarket(m: dict) -> dict:
    raw = m.get("status") or ""
    st = raw.replace("MARKET_STATUS_", "").lower()
    obs = {"provider": "polymarket_us", "market_id": m.get("slug"), "provider_status": st, "settled_at": None,
           "settled_at_source": "updatedAt at resolution", "value": None, "state": "pending", "result": None, "note": None}
    if "cancel" in st or "void" in st:
        obs.update(state="settled", result="void", note=f"market {st}", settled_at=m.get("updatedAt"))
        return obs
    if st != "resolved":
        return obs
    long = next((s for s in m.get("marketSides") or [] if s.get("long")), None)
    v_side = _num((long or {}).get("price"))
    prices = _list(m.get("outcomePrices"))
    v_list = _num(prices[0]) if prices else None
    values = [v for v in (v_side, v_list) if v is not None]
    if not values or (len(values) == 2 and abs(values[0] - values[1]) > 1e-6):
        obs["note"] = "resolved, but the settlement value is missing or inconsistent; not graded"
        return obs
    state, result = _value_state(values[0])
    obs.update(state=state, result=result, value=values[0], settled_at=m.get("updatedAt"))
    if result == "void":
        obs["note"] = f"settled at {values[0]:.2f} (last fair price)"
    return obs


# ------------------------------------------------------------------ fetching
def _fetch_kalshi(tickers: list[str], cache: Path) -> list[dict]:
    c = kalshi.client(cache)
    c.cache_ttl_s = 0
    out = []
    for i in range(0, len(tickers), 50):
        d = c.get("/markets", {"tickers": ",".join(tickers[i:i + 50]), "limit": 100})
        out += [parse_kalshi(m) for m in (d or {}).get("markets") or []]
    return out


def _fetch_polymarket(events: dict[str, set[str]], cache: Path) -> list[dict]:
    c = polymarket_us.client(cache)
    c.cache_ttl_s = 0
    out = []
    for ev_slug, ids in events.items():
        d = c.get(f"/v1/events/slug/{ev_slug}", allow_404=True)
        ev = (d or {}).get("event", d) or {}
        for m in ev.get("markets") or []:
            if m.get("slug") in ids:
                out.append(parse_polymarket(m))
    return out


def _candidates(league: str, now: datetime) -> pd.DataFrame:
    from . import evaluation

    ev = evaluation._load(league)
    if ev.empty:
        return ev
    ev = ev.dropna(subset=["market_id"])
    st = pd.to_datetime(ev["game_start"], utc=True, errors="coerce")
    ev = ev[st.notna() & (st <= now)]
    ev = ev.drop_duplicates(["provider", "market_id"], keep="last")
    seen = load(league)
    if seen.empty:
        return ev
    last = seen.sort_values("observed_at").drop_duplicates(["provider", "market_id"], keep="last").set_index(["provider", "market_id"])
    keep = []
    for r in ev.itertuples():
        k = (r.provider, r.market_id)
        if k not in last.index:
            keep.append(True)
            continue
        o = last.loc[k]
        obs_t = pd.Timestamp(o["observed_at"])
        if o["state"] == "settled":
            settled_t = pd.Timestamp(o.get("first_settled_at") or o["observed_at"])
            keep.append(now - settled_t < timedelta(hours=RECHECK_SETTLED_HOURS) and now - obs_t > timedelta(hours=6))
        else:
            keep.append(now - obs_t > timedelta(minutes=PENDING_RECHECK_MIN))
    return ev[keep]


def record(league: str, observations: list[dict], now: datetime) -> dict:
    """Append observations whose state differs from the last one recorded for that market."""
    seen = load(league)
    last = {} if seen.empty else {(r["provider"], r["market_id"]): r for r in seen.sort_values("observed_at").to_dict("records")}
    new, corrections = [], 0
    for o in observations:
        if not o.get("market_id"):
            continue
        prev = last.get((o["provider"], o["market_id"]))
        sig = (o["state"], o["result"], o["value"], o["provider_status"])
        if prev is not None and (prev["state"], prev["result"], prev["value"], prev["provider_status"]) == sig:
            continue
        o = {**o, "observed_at": now.isoformat(timespec="seconds"), "correction": False, "first_settled_at": None}
        if prev is not None and prev["state"] == "settled":
            o["first_settled_at"] = prev.get("first_settled_at") or prev["observed_at"]
            if o["state"] != "settled" or o["result"] != prev["result"]:
                o["correction"] = True
                o["corrects"] = {"result": prev["result"], "value": prev["value"], "observed_at": prev["observed_at"]}
                corrections += 1
        elif o["state"] == "settled":
            o["first_settled_at"] = o["observed_at"]
        new.append(o)
        last[(o["provider"], o["market_id"])] = o
    if new:
        f = path(league)
        ensure(f.parent)
        with f.open("a", encoding="utf-8", newline="\n") as out:
            for o in new:
                out.write(json.dumps(o, sort_keys=True, default=str) + "\n")
    return {"recorded": len(new), "corrections": corrections}


def check(league: str, now: datetime | None = None, *, fetchers: dict | None = None, require_enabled: bool = True) -> dict:
    """Ask each enabled provider about the markets waiting for settlement. fetchers overrides the network (tests)."""
    now = now or datetime.now(timezone.utc)
    cand = _candidates(league, now)
    if cand.empty:
        return {"league": league, "checked": 0, "recorded": 0, "note": "no started games with priced contracts"}
    fetchers = fetchers or {"kalshi": _fetch_kalshi, "polymarket_us": _fetch_polymarket}
    obs, report = [], {"league": league, "providers": {}}
    for prov, rows in cand.groupby("provider"):
        if prov.startswith("manual"):
            report["providers"][prov] = {"skipped": "manual prices have no settlement feed"}
            continue
        if fetchers is not None and prov not in fetchers:
            continue
        st = config.status(prov)
        if require_enabled and not st.enabled:
            report["providers"][prov] = {"skipped": st.reason}
            continue
        cache = data_root() / "markets" / "cache" / f"{prov}_settlement"
        try:
            if prov == "kalshi":
                got = fetchers[prov](sorted(rows["market_id"].unique()), cache)
            else:
                events: dict[str, set[str]] = {}
                snap = snapshots.load(league, prov)
                ev_of = {} if snap.empty else dict(zip(snap["provider_market_id"], snap["provider_event_id"]))
                for r in rows.itertuples():
                    e = getattr(r, "event_id", None) if isinstance(getattr(r, "event_id", None), str) else ev_of.get(r.market_id)
                    if e:
                        events.setdefault(e, set()).add(r.market_id)
                got = fetchers[prov](events, cache)
        except ProviderError as e:
            report["providers"][prov] = {"error": str(e)}
            continue
        obs += got
        report["providers"][prov] = {"asked": int(rows["market_id"].nunique()), "answers": len(got),
                                     "settled": sum(1 for o in got if o["state"] == "settled")}
    report.update(record(league, obs, now))
    report["checked"] = int(len(cand))
    return report
