"""Grade the model's pre-game predictions against OFFICIAL market settlement.

    python -m modelroom markets settle nfl      (settlement.check, then this)

Inputs, all append-only and never rewritten:
  - the prediction record: data/markets/evaluations/<league>.jsonl. Each contract's prediction is the
    LAST one made before its game started (what the model said at kickoff), with the price seen then;
  - settlement observations: data/markets/settlements/<league>.jsonl (see settlement.py);
  - the prediction ledgers, for the projected stat or score shown alongside.

A prediction is graded only when its own market has settled, independently of every other market on the
same game or player:
  won       the model's side (probability above 50%) matches the settled result
  lost      it doesn't
  void      the market settled void / refunded / at a fair price (e.g. no snap, cancelled game)
  pending   not settled yet (including determined-but-in-dispute-window, disputed, or delayed)
  no_call   the model was at exactly 50%
A box score is never used to grade; the actual stat is shown only as context.

Writes
  data/markets/results/<league>.json            every provider (local)
  data/published/market_results_<league>.json  only providers whose data may be published (markets.config)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.paths import data_root, ensure, ledger_path

from . import config, evaluation, settlement

LABELS = {"game_winner": "Winner", "game_spread": "Spread", "game_total": "Total"}


def _f(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _s(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def _context(league: str) -> dict:
    """Projected stat per (game, player, market) and projected scores per game, from the ledgers; finals and
    player stats for display. Best effort: missing context never blocks grading."""
    out = {"props": {}, "games": {}, "finals": {}, "stats": {}, "stat_of": {}, "labels": {}}
    try:
        gid = "nfl_game_id" if league == "nfl" else "nba_game_id"
        for r in ledger.read_series(ledger_path(f"{league}_props")):
            if r["generated_at"] >= r["game_start"]:
                continue
            k = (str(r[gid]), str(r["player_id"]))
            if k not in out["props"] or r["generated_at"] > out["props"][k]["generated_at"]:
                out["props"][k] = r
        for r in ledger.read(ledger_path(league)):
            if r["generated_at"] < r["game_start"] and (r["game_id"] not in out["games"] or r["generated_at"] > out["games"][r["game_id"]]["generated_at"]):
                out["games"][r["game_id"]] = r
    except Exception:  # noqa: BLE001
        pass
    try:
        from modelroom import history

        g = history._games_table(league)
        g = g[g["status"] == "final"]
        out["finals"] = {r.game_id: {"home": r.home, "away": r.away, "home_score": int(r.home_score), "away_score": int(r.away_score),
                                     "game_date": r.game_date} for r in g.itertuples() if pd.notna(r.home_score)}
        out["stats"], out["stat_of"], out["labels"] = history._player_stats(league)
    except Exception:  # noqa: BLE001
        pass
    return out


def _predictions(league: str) -> pd.DataFrame:
    ev = evaluation._load(league)
    if ev.empty:
        return ev
    ev = ev.dropna(subset=["market_id", "game_start"])
    ev = ev[pd.to_datetime(ev["generated_at"], utc=True) < pd.to_datetime(ev["game_start"], utc=True)]
    return ev.sort_values("generated_at").drop_duplicates(["provider", "market_id"], keep="last")


def _call(p: float) -> str | None:
    return "yes" if p > 0.5 else "no" if p < 0.5 else None


def records(league: str, ctx: dict | None = None) -> list[dict]:
    pred = _predictions(league)
    if pred.empty:
        return []
    obs = settlement.load(league)
    hist: dict = {}
    if not obs.empty:
        for o in obs.sort_values("observed_at").to_dict("records"):
            hist.setdefault((o["provider"], o["market_id"]), []).append(o)
    ctx = ctx if ctx is not None else _context(league)
    out = []
    for r in pred.to_dict("records"):
        r = {k: _s(v) for k, v in r.items()}
        h = hist.get((r["provider"], r["market_id"]), [])
        last = h[-1] if h else None
        p = float(r["model_prob"])
        bid, ask = _f(r.get("yes_bid")), _f(r.get("yes_ask"))
        implied = (bid + ask) / 2 if bid is not None and ask is not None else None
        call = _call(p)
        status = "pending"
        if last and last["state"] == "settled":
            if last["result"] == "void":
                status = "void"
            elif call is None:
                status = "no_call"
            else:
                status = "won" if call == last["result"] else "lost"
        kind = r.get("kind") or "prop"
        rec = {
            "id": f"{r['provider']}:{r['market_id']}", "league": league, "kind": kind, "game_id": r.get("game_id"),
            "game_start": r.get("game_start"), "provider": r["provider"], "market_id": r["market_id"], "market": r["market"],
            "market_label": LABELS.get(r["market"]) or ctx["labels"].get(r["market"], r["market"].replace("_", " ").capitalize()),
            "op": r["op"], "threshold": _f(r["threshold"]), "variant": r.get("variant"), "team": r.get("team"),
            "player": r.get("player") or None, "player_id": r.get("player_id") or None,
            "model_version": r["model_version"], "predicted_at": r["generated_at"], "captured_at": r.get("captured_at"),
            "model_prob": round(p, 4), "model_call": call,
            "market_bid": bid, "market_ask": ask, "market_implied": round(implied, 4) if implied is not None else None,
            "edge": {"grade": r.get("grade")} if r.get("grade") in ("lean", "strong") else None,
            "status": status,
            "settlement": None if last is None else {k: last.get(k) for k in ("state", "result", "value", "settled_at", "settled_at_source", "provider_status", "note", "observed_at", "first_settled_at")},
            "corrections": [{"observed_at": o["observed_at"], "result": o["result"], "was": (o.get("corrects") or {}).get("result")} for o in h if o.get("correction")],
            "projection": None, "actual": None,
        }
        if rec["edge"]:
            fee = lambda x: (r.get("fee_rate") or 0) * x * (1 - x)  # noqa: E731
            ev_y = p - ask - fee(ask) if ask is not None else None
            no_ask = _f(r.get("no_ask"))
            ev_n = (1 - p) - no_ask - fee(no_ask) if no_ask is not None else None
            side = "yes" if (ev_y if ev_y is not None else -1) >= (ev_n if ev_n is not None else -1) else "no"
            rec["edge"]["side"] = side
            rec["edge"]["result"] = None if status in ("pending", "void") or last is None else ("won" if last["result"] == side else "lost")
        gid = str(r.get("game_id"))
        if kind == "prop":
            lr = ctx["props"].get((gid, str(r.get("player_id"))))
            m = (lr or {}).get("probabilities", {}).get(r["market"]) or {}
            if m:
                rec["projection"] = {"mean": m.get("mean"), "sd": m.get("sd")}
            st = ctx["stats"].get((gid, str(r.get("player_id"))))
            stat = ctx["stat_of"].get(r["market"])
            if st and stat in st:
                rec["actual"] = {"stat": _f(st[stat])}
        else:
            pj = r.get("projection") if isinstance(r.get("projection"), dict) else None
            gr = ctx["games"].get(gid)
            if pj:
                rec["projection"] = {"margin": pj.get("margin"), "total": pj.get("total"), "home": pj.get("home"), "away": pj.get("away")}
            elif gr:
                rec["projection"] = {"margin": gr.get("pred_margin"), "total": gr.get("pred_total"), "home": gr.get("home_team"), "away": gr.get("away_team")}
            f = ctx["finals"].get(gid)
            if f:
                rec["actual"] = {"home": f["home"], "away": f["away"], "home_score": f["home_score"], "away_score": f["away_score"]}
        rec["game_date"] = (ctx["finals"].get(gid) or {}).get("game_date") or (str(r.get("game_start"))[:10] if r.get("game_start") else None)
        out.append(rec)
    return sorted(out, key=lambda x: (x["game_start"] or "", x["id"]), reverse=True)


# ------------------------------------------------------------------ summaries
def _block(recs: list[dict]) -> dict:
    n = len(recs)
    won = sum(r["status"] == "won" for r in recs)
    lost = sum(r["status"] == "lost" for r in recs)
    out = {"predictions": n, "settled": sum(r["status"] in ("won", "lost", "void", "no_call") for r in recs), "won": won, "lost": lost,
           "void": sum(r["status"] == "void" for r in recs), "pending": sum(r["status"] == "pending" for r in recs),
           "win_pct": round(won / (won + lost), 4) if won + lost else None}
    graded = [r for r in recs if r["settlement"] and r["settlement"]["state"] == "settled" and r["settlement"]["result"] in ("yes", "no")]
    if graded:
        p = np.clip([r["model_prob"] for r in graded], 1e-4, 1 - 1e-4)
        y = np.array([1.0 if r["settlement"]["result"] == "yes" else 0.0 for r in graded])
        out["n_scored"] = len(graded)
        out["brier"] = round(float(np.mean((p - y) ** 2)), 4)
        out["log_loss"] = round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)
        m = [(r["market_implied"], yy) for r, yy in zip(graded, y) if r["market_implied"] is not None]
        if m:
            q = np.clip([a for a, _ in m], 1e-4, 1 - 1e-4)
            yy = np.array([b for _, b in m])
            out["market"] = {"n": len(m), "brier": round(float(np.mean((q - yy) ** 2)), 4),
                             "log_loss": round(float(-np.mean(yy * np.log(q) + (1 - yy) * np.log(1 - q))), 4)}
    return out


def calibration(recs: list[dict]) -> list[dict]:
    graded = [r for r in recs if r["settlement"] and r["settlement"]["state"] == "settled" and r["settlement"]["result"] in ("yes", "no")]
    bins = []
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        g = [r for r in graded if lo <= r["model_prob"] < hi or (i == 9 and r["model_prob"] == 1)]
        if g:
            bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(g), "predicted": round(float(np.mean([r["model_prob"] for r in g])), 3),
                         "actual": round(float(np.mean([r["settlement"]["result"] == "yes" for r in g])), 3)})
    return bins


def summary(recs: list[dict]) -> dict:
    by = lambda key: {k: _block([r for r in recs if r[key] == k]) for k in sorted({r[key] for r in recs if r[key]})}  # noqa: E731
    return {"overall": _block(recs), "by_market": by("market"), "by_provider": by("provider"), "by_kind": by("kind"),
            "calibration": calibration(recs)}


def run(league: str, ctx: dict | None = None) -> dict:
    recs = records(league, ctx)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    note = ("Graded only on each exchange's official settlement, never on a box score. Prediction = the last one made "
            "before the game started, with the price seen then. Accuracy only: no money was traded, so there is no ROI.")
    local = {"league": league, "kind": "market_results", "generated_at": now, "note": note, "summary": summary(recs), "records": recs}
    f = ensure(data_root() / "markets" / "results") / f"{league}.json"
    f.write_text(json.dumps(local, indent=2, default=str))
    providers = []
    for prov in config.PROVIDERS:
        st = config.status(prov)
        providers.append({"provider": prov, "enabled": st.enabled, "publishable": st.publishable, "reason": st.reason})
    pub_ok = {p["provider"] for p in providers if p["publishable"]}
    pub = [r for r in recs if r["provider"] in pub_ok]
    withheld: dict = {}
    for r in recs:
        if r["provider"] not in pub_ok:
            withheld[r["provider"]] = withheld.get(r["provider"], 0) + 1
    from modelroom.common.publish import write_board

    write_board(data_root() / "published" / f"market_results_{league}.json",
                {"league": league, "kind": "market_results", "generated_at": now, "note": note, "providers": providers,
                 "withheld": withheld, "summary": summary(pub), "records": pub})
    return {"league": league, "predictions": len(recs), "published": len(pub), "withheld": withheld, **{k: v for k, v in summary(recs)["overall"].items() if k in ("settled", "won", "lost", "void", "pending")}}
