"""Model-vs-market record: what the model said about each exchange contract, and how it turned out.

Every props run that has exchange prices appends one row per (contract, run) to
  data/markets/evaluations/<league>.jsonl        (local only; data/ is never committed)
with the model's probability, the price seen, and when. Nothing is edited later.

`report()` settles those rows against final box scores and measures, per market type, edge grade and
confidence bucket:
  - accuracy      log loss and Brier score of the model vs the market's mid price, on the same contracts
  - ROI           flat 1-contract bets on every lean / strong edge, bought at the ask seen, after fees
  - CLV           closing-line value: the entry price vs the last price before the game started
                  (positive = the market moved toward the model after the model flagged it)
  - early signal  share of flagged edges where the market moved toward the model before kickoff

Contracts on players who didn't play are void and excluded (exchanges settle them at a fair price).
Kalshi rows stay on this machine (see markets.config); the report is printed and written locally.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common.paths import data_root, ensure

from . import compare as C
from . import snapshots
from .schema import PropQuote


def path(league: str) -> Path:
    return data_root() / "markets" / "evaluations" / f"{league}.jsonl"


def record(league: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    f = path(league)
    ensure(f.parent)
    with f.open("a", encoding="utf-8", newline="\n") as out:
        for r in rows:
            out.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    return len(rows)


def row(q: PropQuote, model_prob: float, model_version: str, generated_at: str, game_start: str | None,
        grade: dict | None, stat: str) -> dict:
    return {
        "provider": q.provider, "market_id": q.provider_market_id, "game_id": q.game_id, "player_id": q.player_id,
        "player": q.player_name, "market": q.market, "stat": stat, "op": q.op, "threshold": q.threshold, "variant": q.variant,
        "model_prob": round(model_prob, 4), "model_version": model_version, "generated_at": generated_at,
        "yes_bid": q.yes_bid, "yes_ask": q.yes_ask, "no_ask": q.no_ask, "yes_ask_size": q.yes_ask_size, "yes_bid_size": q.yes_bid_size,
        "fee_rate": q.fee_rate, "captured_at": q.captured_at, "game_start": game_start, "void_rule": q.void_rule,
        "grade": (grade or {}).get("grade"),
    }


def _load(league: str) -> pd.DataFrame:
    f = path(league)
    if not f.exists():
        return pd.DataFrame()
    return pd.DataFrame([json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()])


def _outcomes(league: str) -> dict:
    """(game_id, player_id) → stat dict, for players who played."""
    if league == "nfl":
        from modelroom.nfl import player_data

        pg, _, _ = player_data.load()
        pg = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
        pg = pg.assign(rush_rec_yds=pg["rush_yds"] + pg["rec_yds"], td_any=pg["rush_td"] + pg["rec_td"],
                       fantasy_sleeper=pg["fantasy_ppr"] + pg["ints"])
    else:
        from modelroom.nba.props import data

        pg = data.load()
        pg = pg[pg["played"]]
    cols = [c for c in pg.columns if pg[c].dtype.kind in "fi"]
    return {(str(g), str(p)): dict(zip(cols, v)) for g, p, *v in pg[["game_id", "player_id", *cols]].itertuples(index=False)}


def _actual(o: dict, stat: str, variant: str | None) -> float | None:
    if stat == "fantasy_ppr" and variant == "sleeper_ppr":
        stat = "fantasy_sleeper"
    v = o.get(stat)
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def _logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def settle(league: str, outcomes: dict | None = None) -> pd.DataFrame:
    """One row per contract and model version: the first time the model priced it, settled."""
    ev = _load(league)
    if ev.empty:
        return ev
    ev = ev.sort_values("generated_at").drop_duplicates(["provider", "market_id", "model_version"], keep="first")
    close = snapshots.closing(league)
    cmap = {} if close.empty else {(r["provider"], r["provider_market_id"]): r for r in close.to_dict("records")}
    outcomes = outcomes if outcomes is not None else _outcomes(league)
    rows = []
    for r in ev.to_dict("records"):
        o = outcomes.get((str(r["game_id"]), str(r["player_id"])))
        if o is None:
            continue  # not played yet, or didn't play (void)
        y = _actual(o, r["stat"], r.get("variant"))
        if y is None:
            continue
        won = float(y > r["threshold"]) if r["op"] == ">" else float(y >= r["threshold"])
        c = cmap.get((r["provider"], r["market_id"]))
        mid = (r["yes_bid"] + r["yes_ask"]) / 2 if r.get("yes_bid") is not None and r.get("yes_ask") is not None else None
        close_mid = None
        if c is not None and c.get("yes_bid") is not None and c.get("yes_ask") is not None and not pd.isna(c["yes_bid"]) and not pd.isna(c["yes_ask"]):
            close_mid = (c["yes_bid"] + c["yes_ask"]) / 2
        p = r["model_prob"]
        side = None
        ev_yes = p - r["yes_ask"] - C.fee(r.get("fee_rate"), r["yes_ask"]) if r.get("yes_ask") is not None else None
        ev_no = (1 - p) - r["no_ask"] - C.fee(r.get("fee_rate"), r["no_ask"]) if r.get("no_ask") is not None else None
        if r.get("grade") in ("lean", "strong"):
            side = "yes" if (ev_yes or -1) >= (ev_no or -1) else "no"
        price = r["yes_ask"] if side == "yes" else r["no_ask"] if side == "no" else None
        fee = C.fee(r.get("fee_rate"), price) if price is not None else 0.0
        pnl = None
        if side:
            win = won if side == "yes" else 1 - won
            pnl = win - price - fee
        clv = None
        if side and close_mid is not None and price is not None:
            fair_close = close_mid if side == "yes" else 1 - close_mid
            clv = fair_close - price
        moved_toward = None
        if mid is not None and close_mid is not None:
            moved_toward = float(np.sign(close_mid - mid) == np.sign(p - mid)) if close_mid != mid and p != mid else None
        rows.append({**r, "won": won, "mid": mid, "close_mid": close_mid, "side": side, "price": price, "fee": fee, "pnl": pnl,
                     "clv": clv, "moved_toward_model": moved_toward})
    return pd.DataFrame(rows)


def _block(d: pd.DataFrame) -> dict:
    out = {"contracts": int(len(d))}
    m = d.dropna(subset=["mid"])
    if len(m):
        out["accuracy"] = {"n": int(len(m)), "model_log_loss": round(_logloss(m["model_prob"], m["won"]), 4),
                           "market_log_loss": round(_logloss(m["mid"], m["won"]), 4),
                           "model_brier": round(float(np.mean((m["model_prob"] - m["won"]) ** 2)), 4),
                           "market_brier": round(float(np.mean((m["mid"] - m["won"]) ** 2)), 4)}
    b = d.dropna(subset=["pnl"])
    if len(b):
        staked = float((b["price"] + b["fee"]).sum())
        out["bets"] = {"n": int(len(b)), "wins": int((b["pnl"] > 0).sum()), "profit_per_contract": round(float(b["pnl"].mean()), 4),
                       "roi": round(float(b["pnl"].sum() / staked), 4) if staked else None,
                       "clv_mean": round(float(b["clv"].dropna().mean()), 4) if b["clv"].notna().any() else None,
                       "clv_positive_share": round(float((b["clv"].dropna() > 0).mean()), 3) if b["clv"].notna().any() else None}
    mt = d.dropna(subset=["moved_toward_model"])
    if len(mt):
        out["market_moved_toward_model"] = round(float(mt["moved_toward_model"].mean()), 3)
    return out


def report(league: str, outcomes: dict | None = None) -> dict:
    s = settle(league, outcomes)
    out = {"league": league, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": "Settled contracts only. ROI uses the ask seen when the model ran, after fees, one contract per edge.",
           "overall": _block(s) if len(s) else {"contracts": 0}}
    if len(s):
        out["by_provider"] = {k: _block(g) for k, g in s.groupby("provider")}
        out["by_market"] = {k: _block(g) for k, g in s.groupby("market")}
        out["by_grade"] = {str(k): _block(g) for k, g in s.groupby(s["grade"].fillna("none"))}
        conf = pd.cut((s["model_prob"] - 0.5).abs(), [0, 0.1, 0.2, 0.3, 0.5], include_lowest=True).astype(str)
        out["by_confidence"] = {k: _block(g) for k, g in s.groupby(conf)}
        if s["model_version"].nunique() > 1:
            out["by_model_version"] = {k: _block(g) for k, g in s.groupby("model_version")}
    f = ensure(data_root() / "markets" / "reports") / f"{league}.json"
    f.write_text(json.dumps(out, indent=2, default=str))
    return out


def log_run(league: str, projs: list, idx_all: dict, price_fn, support_fn, reliability: dict, model_version: str,
            generated_at: str, starts: dict, now) -> int:
    """Append one evaluation row per priced contract in this run.

    price_fn(projection, quote) → (calibrated model probability, stat column) or None if not priced.
    support_fn(projection, market) → support level."""
    rows = []
    for x in projs:
        for q in idx_all.get((x.game_id, x.player_id), []):
            got = price_fn(x, q)
            if got is None:
                continue
            prob, stat = got
            v = C.view(q, prob, now)
            g = C.grade(C.best([v]), support_fn(x, q.market), reliability.get(q.market))
            rows.append(row(q, prob, model_version, generated_at, starts.get(x.game_id), g, stat))
    return record(league, rows)
