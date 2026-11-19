"""Pick of the Day (TEST site): the single strongest model-vs-market opportunity per league per day, frozen once.

    python -m modelroom potd            -> preview-ledger/potd_week_*.jsonl (append-only, hash-chained)
                                           preview-ledger/potd_grades_week_*.jsonl
                                           data/published/pick_of_the_day.json (what the site reads)

Candidates (published active game models only; prop and game shadows are never read):
  spread, total   the pre-kickoff CONSENSUS line (at least two books, the same line the picks ledger already stores)
                  and the model's probability of the side it favours AT that line (its own normal distribution)
  moneyline       the consensus (median) prices, de-vigged to a market probability, against the model's win probability
Player props are NOT candidates: no approved source allows storing a prop market line (see LIMITS).

Rule (one decision per league per Pacific date, at the first refresh where today's games have a market line):
  edge = model probability of the side - market probability of that side
         (moneyline: the de-vigged consensus; spread/total: 0.5, the balanced line, because consensus PRICES for
         spreads and totals are not stored; this reference is stated on the card, never shown as a market price)
  qualifies when model probability >= MIN_PROB and edge >= MIN_EDGE; the highest edge wins (ties: higher probability,
  then earlier start). Nothing qualifies -> a "no qualifying pick" record for the day. Never re-selected later.

Thresholds come from existing validation, not from a claimed edge:
  MIN_PROB 0.565  break-even at a standard -110 price (52.4%) + 4 points, the largest calibration gap the NFL game
                  model showed in its 0.5-0.6 probability band in backtest (predicted 0.550, actual 0.511)
  MIN_EDGE 0.04   the same 4-point calibration gap: smaller disagreements are inside the model's own error
These are filters, not evidence of an edge: the NFL game model's backtest side record against market spreads was
48.0% (836 games) and 44.5% where it disagreed by 3+ points; NBA has no market backtest. Results are labelled
unvalidated until UNVALIDATED_UNTIL settled picks per league exist.

Grades (separate append-only series, the pick record is never touched): hit | miss | push | void | pending.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from modelroom.common import ledger
from modelroom.common import oddsmath as O
from modelroom.common.paths import data_root, ledger_path

MIN_PROB = 0.565
MIN_EDGE = 0.04
UNVALIDATED_UNTIL = 100
TZ = "America/Los_Angeles"
SOURCE = "potd"
LIMITS = ("Player props are not candidates yet: Polymarket prices may not be stored or shown publicly without documented "
          "permission (Polymarket US participant agreement I.22), the free sportsbook feed carries no props, and "
          "Sportsgameodds' free tier needs a paid-plan signup and forbids keeping its data after access ends.")


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def candidates(league: str, game: dict, rec: dict | None, market: dict | None, sig: tuple) -> list[dict]:
    """Every qualifying-or-not opportunity for one game, from its last pre-game record and pre-game consensus."""
    if not rec or not market:
        return []
    ms, ts = sig
    out = []
    base = {"league": league, "league_game_id": str(game["game_id"]), "home": game["home"], "away": game["away"],
            "game_start": rec["game_start"], "model_version": rec["model_version"], "source_record": {
                "seq": rec.get("seq"), "hash": rec.get("hash"), "generated_at": rec["generated_at"]},
            "line_source": ",".join(market.get("sources") or []) or None, "line_captured_at": market.get("captured_at"),
            "line_books": market.get("books")}
    sp, tot = _f(market.get("spread")), _f(market.get("total"))
    pm, pt, hp = _f(rec.get("pred_margin")), _f(rec.get("pred_total")), _f(rec.get("home_win_prob"))
    if sp is not None and ms and pm is not None:
        c = O.cover_probs(pm, ms, sp)
        side = "home" if c["home"] >= c["away"] else "away"
        line = sp if side == "home" else -sp
        out.append({**base, "market": "spread", "selection": side, "team": game[side], "line": line, "price": None,
                    "model_prob": round(c[side], 4), "push_prob": round(c["push"], 4), "market_prob": None, "reference_prob": 0.5,
                    "projection": round(pm if side == "home" else -pm, 1),        # the picked team's projected margin
                    "difference": round((pm if side == "home" else -pm) + line, 1)})   # margin beyond the line
    if tot is not None and ts and pt is not None:
        o = O.over_probs(pt, ts, tot)
        side = "over" if o["over"] >= o["under"] else "under"
        out.append({**base, "market": "total", "selection": side, "team": None, "line": tot, "price": None,
                    "model_prob": round(o[side], 4), "push_prob": round(o["push"], 4), "market_prob": None, "reference_prob": 0.5,
                    "projection": round(pt, 1), "difference": round(pt - tot, 1)})
    ha, aa = _f(market.get("home_ml")), _f(market.get("away_ml"))
    if hp is not None and ha is not None and aa is not None:
        mh, ma = O.devig(ha, aa)
        if mh is not None:
            for side, p, mp, price in (("home", hp, mh, ha), ("away", 1 - hp, ma, aa)):
                if p > mp:
                    out.append({**base, "market": "moneyline", "selection": side, "team": game[side], "line": None, "price": price,
                                "model_prob": round(p, 4), "push_prob": 0.0, "market_prob": round(mp, 4), "reference_prob": round(mp, 4),
                                "projection": round(pm if side == "home" else -pm, 1) if pm is not None else None, "difference": None})
    for c in out:
        c["edge"] = round(c["model_prob"] - c["reference_prob"], 4)
        c["qualifies"] = c["model_prob"] >= MIN_PROB and c["edge"] >= MIN_EDGE
    return out


def choose(cands: list[dict]) -> dict | None:
    q = [c for c in cands if c["qualifies"]]
    if not q:
        return None
    return sorted(q, key=lambda c: (-c["edge"], -c["model_prob"], c["game_start"]))[0]


def explain(p: dict) -> str:
    who = p["team"] or f"{p['away']} @ {p['home']}"
    pct = f"{p['model_prob'] * 100:.0f}%"
    if p["market"] == "spread":
        proj = p["projection"]
        fate = f"to win by {proj:g}" if proj > 0 else (f"to lose by {-proj:g}" if proj < 0 else "to tie")
        return (f"Model Room projects {who} {fate}; at {p['line']:+g} that is {abs(p['difference']):g} points of cushion, "
                f"a {pct} chance to cover.")
    if p["market"] == "total":
        return (f"Model Room projects {p['projection']} total points against a line of {p['line']:g}, {abs(p['difference'])} "
                f"{'over' if p['difference'] > 0 else 'under'}: a {pct} chance of the {p['selection']}.")
    return f"Model Room gives {who} a {pct} chance to win; the consensus price implies {p['market_prob'] * 100:.0f}%."


def _pt_date(ts) -> str:
    return pd.Timestamp(ts).tz_convert(TZ).date().isoformat()


def read() -> list[dict]:
    return ledger.read_series(ledger_path("potd"))


def read_grades() -> dict:
    out = {}
    for r in ledger.read_series(ledger_path("potd_grades")):
        out[r["pick_key"]] = r              # latest grade record wins; every earlier one stays in the file
    return out


def select_day(league: str, now: datetime, games: pd.DataFrame, recs: dict, markets: dict, sig: tuple) -> dict | None:
    """Today's (Pacific) decision for one league, or None while no game today has a market line yet."""
    today = _pt_date(pd.Timestamp(now))
    g = games[(games["status"] == "scheduled") & games["start_time"].notna()]
    g = g[(pd.to_datetime(g["start_time"], utc=True) > pd.Timestamp(now)) &
          (pd.to_datetime(g["start_time"], utc=True).dt.tz_convert(TZ).dt.date.astype(str) == today)]
    cands, priced = [], 0
    for x in g.itertuples():
        m = markets.get(x.game_id)
        if m:
            priced += 1
        cands += candidates(league, {"game_id": x.game_id, "home": x.home, "away": x.away}, recs.get(x.game_id), m, sig)
    if not priced:
        return None
    pick = choose(cands)
    key = f"potd:{league}:{today}"
    common = {"game_id": key, "pick_key": key, "date": today, "league": league, "kind": "pick_of_the_day",
              "selected_at": pd.Timestamp(now).isoformat(timespec="seconds"), "generated_at": pd.Timestamp(now).isoformat(timespec="seconds"),
              "rule": {"min_prob": MIN_PROB, "min_edge": MIN_EDGE}, "candidates_considered": len(cands),
              "games_with_lines": priced, "params_hash": None}
    if pick is None:
        end = pd.Timestamp(f"{today} 23:59:59", tz=TZ).tz_convert("UTC").isoformat()
        return {**common, "status": "no_pick", "model_version": "-", "game_start": end, "inputs_hash": f"none:{len(cands)}"}
    rec = {**common, **pick, "status": "pick", "explanation": explain(pick)}
    rec["game_id"], rec["pick_key"] = key, key
    rec["inputs_hash"] = (pick["source_record"]["hash"] or "")[:16]
    return rec


def grade(p: dict, game: dict | None) -> str:
    """hit | miss | push | void | pending, from the stored selection and line only."""
    if p.get("status") != "pick":
        return "none"
    if not game:
        return "pending"
    st = str(game.get("status") or "")
    if st in ("canceled", "cancelled", "postponed"):
        return "void"
    if st != "final" or game.get("home_score") is None or pd.isna(game["home_score"]):
        return "pending"
    h, a = float(game["home_score"]), float(game["away_score"])
    if p["market"] == "moneyline":
        return "push" if h == a else ("hit" if (h > a) == (p["selection"] == "home") else "miss")
    if p["market"] == "spread":
        v = (h - a) + (p["line"] if p["selection"] == "home" else -p["line"])
        v = v if p["selection"] == "home" else -v
        return "push" if v == 0 else ("hit" if v > 0 else "miss")
    t = h + a
    return "push" if t == p["line"] else ("hit" if (t > p["line"]) == (p["selection"] == "over") else "miss")


def summary(results: list[str]) -> dict:
    n = {k: results.count(k) for k in ("hit", "miss", "push", "void", "pending")}
    g = n["hit"] + n["miss"]
    return {**n, "graded": g, "hit_rate": round(n["hit"] / g, 4) if g else None,
            "validated": False, "note": f"Unvalidated until {UNVALIDATED_UNTIL} settled picks; {g} so far."}


def run(leagues=("nba", "nfl"), now: datetime | None = None, write: bool = True) -> dict:
    from modelroom import history as H

    now = now or datetime.now(timezone.utc)
    existing = {r["pick_key"]: r for r in read()}
    new, games_by = [], {}
    for lg in leagues:
        try:
            games = H._games_table(lg)
            games_by[lg] = games.set_index("game_id").to_dict("index")
            recs = H._pregame(ledger.read(ledger_path(lg)))          # game-model ledger: one published version
            rec = select_day(lg, now, games, recs, H._market(lg), H._sigmas(lg))
        except Exception as e:  # noqa: BLE001 - a league failing never blocks the other
            print(f"potd {lg}: {e}")
            continue
        if rec and rec["pick_key"] not in existing:
            new.append(rec)
    if write and new:
        ledger.append_weekly(ledger_path("potd"), now, new)
    picks = read() if write else list(existing.values()) + new
    grades, gnew = read_grades(), []
    for p in picks:
        if p.get("status") != "pick":
            continue
        gm = games_by.get(p["league"], {}).get(p["league_game_id"])
        r = grade(p, gm)
        if r != "pending" and (grades.get(p["pick_key"]) or {}).get("result") != r:
            gnew.append({"game_id": f"{p['pick_key']}|grade", "pick_key": p["pick_key"], "model_version": SOURCE, "result": r,
                         "final": None if not gm else {"home": _f(gm.get("home_score")), "away": _f(gm.get("away_score"))},
                         "generated_at": now.isoformat(timespec="seconds"), "game_start": "9999-12-31T00:00:00+00:00",
                         "inputs_hash": r, "params_hash": None})
    if write and gnew:
        ledger.append_weekly(ledger_path("potd_grades"), now, gnew)   # game_start far ahead: grades come after the game
    grades = read_grades() if write else {**grades, **{g["pick_key"]: g for g in gnew}}
    out = publish(picks, grades, now)
    if write:
        f = data_root() / "published" / "pick_of_the_day.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(out, indent=2, default=str))
    return {"new": len(new), "graded": len(gnew), "today": {lg: (out["today"].get(lg) or {}).get("status") for lg in leagues}}


PUBLIC = ("pick_key", "date", "league", "status", "market", "selection", "team", "home", "away", "line", "price", "model_prob",
          "push_prob", "market_prob", "reference_prob", "edge", "projection", "difference", "explanation", "model_version",
          "selected_at", "game_start", "line_source", "line_captured_at", "candidates_considered", "games_with_lines", "seq", "hash")


def publish(picks: list[dict], grades: dict, now: datetime) -> dict:
    today = _pt_date(pd.Timestamp(now))
    rows = []
    for p in sorted(picks, key=lambda r: (r["date"], r["league"]), reverse=True):
        r = {k: p.get(k) for k in PUBLIC}
        if p.get("status") == "pick":
            r["explanation"] = explain(p)     # wording from the stored numbers; the ledger record itself is never edited
        r["result"] = (grades.get(p["pick_key"]) or {}).get("result") or ("pending" if p.get("status") == "pick" else "none")
        rows.append(r)
    rec = {lg: summary([r["result"] for r in rows if r["league"] == lg and r["status"] == "pick"]) for lg in ("nba", "nfl")}
    return {"generated_at": now.isoformat(timespec="seconds"), "date": today,
            "today": {lg: next((r for r in rows if r["league"] == lg and r["date"] == today), None) for lg in ("nba", "nfl")},
            "history": rows, "record": rec, "rule": {"min_prob": MIN_PROB, "min_edge": MIN_EDGE, "unvalidated_until": UNVALIDATED_UNTIL},
            "notice": ("Unvalidated. Model Room has not shown an edge against the market yet: these are the model's strongest "
                       "disagreements with the consensus line, not guaranteed results and not betting advice."),
            "limits": LIMITS}
