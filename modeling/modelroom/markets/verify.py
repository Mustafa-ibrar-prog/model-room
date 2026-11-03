"""Live check of the exchange integrations. Prints AGGREGATES only: counts, rates, pass/fail. No price,
quote or settlement value is printed or written anywhere that is published (provider terms).

    MODELROOM_MARKETS_POLYMARKET_US=on MODELROOM_MARKETS_KALSHI=on python -m modelroom.markets.verify nfl

Steps: fetch both exchanges → field sanity → threshold semantics against the contract's own title →
props run with prices (model probabilities, matching, edges) → the same run without prices (the model's
numbers must not change) → settled-market parsing on recently settled contracts.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

from modelroom.common.paths import data_root, output_dir

from . import config, games, kalshi, polymarket_us, run, settlement, snapshots

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}", flush=True)


def info(msg: str) -> None:
    print(f"info  {msg}", flush=True)


def rate(n: int, d: int) -> str:
    return f"{n}/{d} = {100 * n / d:.1f}%" if d else "0/0"


def _num_in(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", text or "")]


def field_checks(league: str) -> list[dict]:
    snap = snapshots.latest(league)
    rows = snap.to_dict("records") if len(snap) else []
    for prov in config.PROVIDERS:
        rs = [r for r in rows if r["provider"] == prov]
        props = [r for r in rs if not r["market"].startswith("game_")]
        gm = [r for r in rs if r["market"].startswith("game_")]
        info(f"{prov}: {len(props)} player-prop contracts, {len(gm)} game contracts; markets {dict(Counter(r['market'] for r in rs).most_common(8))}")
        if not rs:
            check(f"{prov}: quotes fetched", False, "none")
            continue
        two = [r for r in rs if r.get("yes_bid") is not None and r.get("yes_ask") is not None]
        bad = [r for r in two if not (0 < r["yes_bid"] <= r["yes_ask"] < 1)]
        check(f"{prov}: bid ≤ ask, both inside (0, 1)", not bad, f"{len(bad)} bad of {len(two)} two-sided")
        info(f"{prov}: two-sided {rate(len(two), len(rs))}; one-sided or empty books are flagged, never filled in")
        if prov == "kalshi":
            sized = [r for r in rs if r.get("yes_ask_size") is not None]
            check(f"{prov}: ask size published", len(sized) == len(rs), rate(len(sized), len(rs)))
        else:
            info(f"{prov}: listing has no sizes (book depth is fetched separately for flagged contracts)")
        now = datetime.now(timezone.utc)
        ages = [(now - datetime.fromisoformat(r["captured_at"])).total_seconds() / 60 for r in rs]
        check(f"{prov}: quote timestamps are fresh", max(ages) < 30, f"oldest {max(ages):.1f} min")
        fee = [r for r in rs if r.get("fee_rate") is not None]
        check(f"{prov}: fee rate present", len(fee) == len(rs), rate(len(fee), len(rs)))
        # Threshold semantics against the contract's own title.
        ok = bad_t = 0
        for r in props:
            t = r.get("title") or ""
            nums = _num_in(t)
            want = r["threshold"] + 0.5 if r["op"] == ">" else r["threshold"]   # "greater than 49.5" = "50+"
            if not nums:
                continue
            if any(abs(n - want) < 1e-9 or abs(n - r["threshold"]) < 1e-9 for n in nums):
                ok += 1
            else:
                bad_t += 1
        check(f"{prov}: prop thresholds agree with the contract titles", bad_t == 0 and ok > 0, f"{ok} agree, {bad_t} disagree")
    return rows


def board_checks(league: str, priced: dict) -> None:
    pub = json.loads((data_root() / "published" / f"{league}_props.json").read_text())
    local_f = output_dir(league) / "props_compare_local.json"
    local = json.loads(local_f.read_text()) if local_f.exists() else {"games": []}
    seen: dict = {}
    for b in (pub, local):
        for g in b["games"]:
            for p in g["players"]:
                for mk, m in p["markets"].items():
                    for t in m["thresholds"]:
                        for q in t["quotes"]:
                            seen[(q["provider"], p["player_id"], mk, t["op"], t["threshold"], t["variant"])] = (t, q)
    info(f"{league}: {len(seen)} (provider, player, threshold) contracts priced by the model")
    # Matching rate: player-prop quotes in snapshots vs priced on the board.
    for prov in config.PROVIDERS:
        n_snap = sum(1 for r in priced["rows"] if r["provider"] == prov and not r["market"].startswith("game_"))
        n_board = sum(1 for k in seen if k[0] == prov)
        check(f"{league} {prov}: player-prop quotes matched to a projected player", n_snap == 0 or n_board / n_snap >= 0.6, rate(n_board, n_snap))
    um = Counter(u["note"] for u in pub["data"].get("unmatched_quotes", []))
    info(f"{league}: unmatched publishable quotes by reason {dict(um)}")
    # Edge arithmetic: EV = p − ask − θ·ask·(1−ask), per side.
    errs = 0
    for (prov, *_), (t, q) in seen.items():
        p = t["model_prob"]
        if q["yes_ask"] is not None and q["ev_yes"] is not None:
            errs += abs(q["ev_yes"] - (p - q["yes_ask"] - (q["fee_yes"] or 0))) > 1e-6
        if q["no_ask"] is not None and q["ev_no"] is not None:
            errs += abs(q["ev_no"] - ((1 - p) - q["no_ask"] - (q["fee_no"] or 0))) > 1e-6
        if prov == "kalshi" and q["yes_ask"] is not None and q["fee_yes"] is not None:
            errs += abs(q["fee_yes"] - kalshi.FEE_RATE * q["yes_ask"] * (1 - q["yes_ask"])) > 1e-6
        if q["yes_bid"] is not None and q["yes_ask"] is not None:
            errs += abs(q["mid"] - (q["yes_bid"] + q["yes_ask"]) / 2) > 1e-9   # implied probability = midpoint
    check(f"{league}: implied = midpoint, fee = θ·ask·(1−ask), edge = model − ask − fee, on every priced side", errs == 0, f"{errs} mismatches")
    strong_bad = sum(1 for (t, q) in seen.values() if t["edge_grade"].get("grade") == "strong" and not q["usable"])
    check(f"{league}: no strong edge from an unusable quote", strong_bad == 0)
    grades = Counter((t["edge_grade"] or {}).get("grade") or "none" for (t, q) in seen.values())
    info(f"{league}: edge grades {dict(grades)}; usable quotes {rate(sum(q['usable'] for _, q in seen.values()), len(seen))}")
    flags = Counter(f for _, q in seen.values() for f in q["flags"])
    info(f"{league}: quote flags {dict(flags.most_common(8))}")


def independence(league: str, with_prices: dict) -> None:
    """Re-run the props model with every provider off; the model's numbers must be identical."""
    for k in ("MODELROOM_MARKETS_POLYMARKET_US", "MODELROOM_MARKETS_KALSHI"):
        os.environ.pop(k, None)
    _props(league)
    b = json.loads((data_root() / "published" / f"{league}_props.json").read_text())
    without = {(p["player_id"], mk, t["op"], t["threshold"], t["variant"]): t["model_prob"]
               for g in b["games"] for p in g["players"] for mk, m in p["markets"].items() for t in m["thresholds"]}
    both = set(without) & set(with_prices)
    diff = [k for k in both if abs(without[k] - with_prices[k]) > 1e-12]
    check(f"{league}: model probabilities identical with and without exchange prices", bool(both) and not diff, f"{len(both)} compared, {len(diff)} differ")


def _props(league: str) -> None:
    if league == "nfl":
        from modelroom.nfl.props import pipeline
    else:
        from modelroom.nba.props import pipeline
    pipeline.run(write_ledger=False)


def settled_checks(league: str) -> None:
    c = kalshi.client(None)
    states: Counter = Counter()
    for series in list(kalshi.SERIES[league])[:3] + list(games.KALSHI_SERIES[league])[:2]:
        d = c.get("/events", {"series_ticker": series, "status": "settled", "with_nested_markets": "true", "limit": 5})
        for ev in (d or {}).get("events") or []:
            for m in ev.get("markets") or []:
                o = settlement.parse_kalshi(m)
                states[(o["state"], o["result"])] += 1
    graded = sum(v for (s, r), v in states.items() if s == "settled")
    check(f"{league} kalshi: settled contracts parse to a final result", graded > 0, f"{graded} of {sum(states.values())}; states {dict((f'{s}/{r}', v) for (s, r), v in states.items())}")
    pm = polymarket_us.client(None)
    d = pm.get("/v1/events", {"closed": "true", "limit": 10})
    ps: Counter = Counter()
    for ev in (d or {}).get("events") or []:
        for m in ev.get("markets") or []:
            o = settlement.parse_polymarket(m)
            ps[(o["state"], o["result"])] += 1
    info(f"polymarket_us: closed markets parse as {dict((f'{s}/{r}', v) for (s, r), v in ps.items())}")


def main(league: str) -> int:
    os.environ["MODELROOM_MARKETS_POLYMARKET_US"] = "on"
    os.environ["MODELROOM_MARKETS_KALSHI"] = "on"
    for k in ("MODELROOM_ENV", "MODELROOM_MARKETS_KALSHI_PUBLISH", "MODELROOM_MARKETS_REDISTRIBUTION_OK"):
        os.environ.pop(k, None)
    rep = run.fetch(league, days=10, log=lambda *_: None)
    for prov, st in rep["providers"].items():
        info(f"{prov}: fetch {json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in st.items() if k in ('quotes', 'requests', 'events_found', 'events_missing', 'errors', 'stored', 'skipped', 'error')})}")
        check(f"{prov}: fetch ran without errors", not st.get("error") and not st.get("errors"), str(st.get("error") or (st.get("errors") or [""])[0])[:120])
    rows = field_checks(league)
    _props(league)
    b = json.loads((data_root() / "published" / f"{league}_props.json").read_text())
    with_prices = {(p["player_id"], mk, t["op"], t["threshold"], t["variant"]): t["model_prob"]
                   for g in b["games"] for p in g["players"] for mk, m in p["markets"].items() for t in m["thresholds"]}
    board_checks(league, {"rows": rows})
    n = games.evaluate(league)
    info(f"{league}: game-market contracts evaluated {n}")
    try:
        settled_checks(league)
    except Exception as e:  # noqa: BLE001
        check(f"{league}: settled-market parsing", False, type(e).__name__)
    independence(league, with_prices)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{league}: {len(RESULTS) - len(failed)} passed, {len(failed)} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "nfl"))
