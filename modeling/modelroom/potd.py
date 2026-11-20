"""Pick of the Day (TEST site): the single strongest model-vs-market opportunity per league per day, frozen once.

    python -m modelroom potd            -> preview-ledger/potd_week_*.jsonl (append-only, hash-chained)
                                           preview-ledger/potd_grades_week_*.jsonl
                                           data/published/pick_of_the_day.json (what the site reads)

PLAYER PROPS ONLY (since 2026-11-19; the game-market picks made before that stay in the ledger, graded as recorded).
Candidates: a STORED market line from an approved source (PROP_LINE_SOURCES; none approved yet) for an eligible stat,
against the player's last pre-game record of the PUBLISHED active prop version (shadows never read). The model's chance
of the over at line L is its own ladder P(stat >= next whole number above L). With no approved line source, every day is
"no qualifying pick" and nothing is estimated. Live Polymarket lines appear only in the site's owner view, never here.

Rule (one decision per league per Pacific date, at the first refresh with games left today):
  edge = model probability of the side - market probability of that side (the source's own price when it has one,
         else 0.5, stated on the card and never shown as a market price)
  qualifies when model probability >= MIN_PROB and edge >= MIN_EDGE; the highest edge wins (ties: higher probability,
  then earlier start). Nothing qualifies -> a "no qualifying pick" record for the day, with the reason.

Thresholds come from existing validation, not from a claimed edge:
  MIN_PROB 0.565  break-even at a standard -110 price (52.4%) + 4 points of margin, larger than the live calibration error
                  of the active prop models (NBA 0.2.0 ladder 0.012, NFL 0.1.1 0.008) and equal to the largest gap the
                  game models showed in backtest
  MIN_EDGE 0.04   the same 4 points: smaller disagreements are inside the models' measured error
These are filters, not evidence of an edge: prop prices have never been collected, so no prop edge against a market has
been measured. Results are labelled unvalidated until UNVALIDATED_UNTIL settled picks per league exist.

Grades (separate append-only series, the pick record is never touched): hit | miss | push | void | pending.
"""
from __future__ import annotations

import math

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
LIMITS = ("Player props only. No approved source supplies a storable player-prop line yet: Polymarket prices may not be "
          "stored or shown publicly without documented permission (participant agreement I.22), the free sportsbook feed "
          "carries no props, the free odds-API tiers checked need a payment-page signup or forbid keeping their data, and "
          "daily-fantasy pick boards have no documented data permission. Until one does, each day shows no qualifying pick; no line "
          "is ever estimated.")


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
    who = p.get("team") or f"{p['away']} @ {p['home']}"
    pct = f"{p['model_prob'] * 100:.0f}%"
    if p["market"] == "prop":
        lab = p["stat"].replace("_", " ")
        mk = "" if p.get("market_prob") is None else f"; the market implies {p['market_prob'] * 100:.0f}%"
        shown = int(math.floor(float(p['projection']) + 0.5))   # player projections are shown as whole numbers
        return (f"Model Room projects {p['player']} for {shown} {lab} against a line of {p['line']:g}: "
                f"a {pct} chance of the {p['selection']}{mk}.")
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


ELIGIBLE = {"nba": ("points", "rebounds", "assists", "threes"),
            "nfl": ("passing_yards", "rushing_yards", "receiving_yards", "receptions", "anytime_td", "passing_tds")}
# Approved sources of STORABLE player-prop lines: none yet (see LIMITS). Each entry would be a callable
# (league, now) -> [{"player_id", "league_game_id", "market", "line", "over_prob"?, "under_prob"?, "source", "captured_at"}].
PROP_LINE_SOURCES: dict = {}


def prop_candidates(league: str, game: dict, rec: dict, q: dict) -> list[dict]:
    """The model's side of one stored market line for one player, from his last pre-game record (active version).
    Over at line L wins when the stat is above L; the model's chance is read from its own ladder P(stat >= k)."""
    pr = (rec.get("probabilities") or {}).get(q["market"])
    if not pr or q.get("line") is None:
        return []
    lad = {float(k): float(v) for k, v in pr.items() if k not in ("mean", "sd", "support")}
    L = float(q["line"])
    k_over = float(int(L) + 1) if L == int(L) else float(int(L) + 1)      # smallest whole number above L
    if k_over not in lad:
        return []
    p_over = lad[k_over]
    p_push = (lad.get(L, p_over) - p_over) if L == int(L) else 0.0
    p_under = max(0.0, 1.0 - p_over - p_push)
    side = "over" if p_over >= p_under else "under"
    mp = q.get("over_prob") if side == "over" else q.get("under_prob")
    p = p_over if side == "over" else p_under
    c = {"league": league, "league_game_id": str(game["game_id"]), "home": game["home"], "away": game["away"], "market": "prop",
         "stat": q["market"], "player": rec.get("player"), "player_id": str(rec["player_id"]), "team": rec.get("team"),
         "selection": side, "line": L, "price": q.get("price"), "model_prob": round(p, 4), "push_prob": round(p_push, 4),
         "market_prob": None if mp is None else round(float(mp), 4), "reference_prob": 0.5 if mp is None else round(float(mp), 4),
         "projection": None if pr.get("mean") is None else round(float(pr["mean"]), 1), "game_start": rec["game_start"],
         "model_version": rec["model_version"], "source_record": {"seq": rec.get("seq"), "hash": rec.get("hash"), "generated_at": rec["generated_at"]},
         "line_source": q.get("source"), "line_captured_at": q.get("captured_at"), "line_books": None}
    c["difference"] = None if c["projection"] is None else round(c["projection"] - L, 1)
    c["edge"] = round(c["model_prob"] - c["reference_prob"], 4)
    c["qualifies"] = c["model_prob"] >= MIN_PROB and c["edge"] >= MIN_EDGE
    return [c]


def select_day(league: str, now: datetime, games: pd.DataFrame, prop_recs: dict, lines: list[dict]) -> dict | None:
    """Today's (Pacific) player-prop decision for one league. None while there are no games left today.
    `lines`: stored market lines from approved sources only; none -> a "no qualifying pick" record saying why."""
    today = _pt_date(pd.Timestamp(now))
    g = games[(games["status"] == "scheduled") & games["start_time"].notna()]
    g = g[(pd.to_datetime(g["start_time"], utc=True) > pd.Timestamp(now)) &
          (pd.to_datetime(g["start_time"], utc=True).dt.tz_convert(TZ).dt.date.astype(str) == today)]
    if not len(g):
        return None
    by_game = {str(x.game_id): {"game_id": x.game_id, "home": x.home, "away": x.away} for x in g.itertuples()}
    cands = []
    for q in lines:
        gm, rec = by_game.get(str(q.get("league_game_id"))), prop_recs.get((str(q.get("league_game_id")), str(q.get("player_id"))))
        if gm and rec and q.get("market") in ELIGIBLE[league]:
            cands += prop_candidates(league, gm, rec, q)
    pick = choose(cands)
    key = f"potd:{league}:{today}"
    common = {"game_id": key, "pick_key": key, "date": today, "league": league, "kind": "pick_of_the_day", "format": "player_prop",
              "selected_at": pd.Timestamp(now).isoformat(timespec="seconds"), "generated_at": pd.Timestamp(now).isoformat(timespec="seconds"),
              "rule": {"min_prob": MIN_PROB, "min_edge": MIN_EDGE}, "candidates_considered": len(cands),
              "games_with_lines": len({c["league_game_id"] for c in cands}), "params_hash": None}
    if pick is None:
        end = pd.Timestamp(f"{today} 23:59:59", tz=TZ).tz_convert("UTC").isoformat()
        why = "no approved player-prop line source" if not lines else "no prop cleared the bar"
        return {**common, "status": "no_pick", "reason": why, "model_version": "-", "game_start": end, "inputs_hash": f"none:{len(cands)}"}
    rec = {**common, **pick, "status": "pick", "explanation": explain(pick)}
    rec["game_id"], rec["pick_key"] = key, key
    rec["inputs_hash"] = (pick["source_record"]["hash"] or "")[:16]
    return rec


def grade_prop(p: dict, game: dict | None, actual: float | None) -> str:
    if not game:
        return "pending"
    st = str(game.get("status") or "")
    if st in ("canceled", "cancelled", "postponed"):
        return "void"
    if st != "final":
        return "pending"
    if actual is None:
        return "void"                                    # the player did not play
    if actual == p["line"]:
        return "push"
    return "hit" if (actual > p["line"]) == (p["selection"] == "over") else "miss"


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
            from modelroom import published as PUB
            gk = "nfl_game_id" if lg == "nfl" else "nba_game_id"
            pr = H._pregame([r for r in ledger.read_series(ledger_path(f"{lg}_props")) if PUB.is_published(lg, r)])  # active only
            prop_recs = {(str(r[gk]), str(r["player_id"])): r for r in pr.values()}
            lines = [q for src in PROP_LINE_SOURCES.values() for q in src(lg, now)]
            rec = select_day(lg, now, games, prop_recs, lines)
        except Exception as e:  # noqa: BLE001 - a league failing never blocks the other
            print(f"potd {lg}: {e}")
            continue
        if rec and rec["pick_key"] not in existing:
            new.append(rec)
    if write and new:
        ledger.append_weekly(ledger_path("potd"), now, new)
    picks = read() if write else list(existing.values()) + new
    grades, gnew = read_grades(), []
    stats = {}
    for p in picks:
        if p.get("status") != "pick":
            continue
        gm = games_by.get(p["league"], {}).get(p["league_game_id"])
        if p.get("market") == "prop":
            if p["league"] not in stats:
                try:
                    stats[p["league"]] = H._player_stats(p["league"])[:2]
                except Exception:  # noqa: BLE001
                    stats[p["league"]] = ({}, {})
            st, stat_of = stats[p["league"]]
            row = st.get((p["league_game_id"], p["player_id"]))
            v = None if row is None else _f(row.get(stat_of.get(p["stat"])))
            r = grade_prop(p, gm, v)
        else:
            r = grade(p, gm)                                         # game-market picks made before the props-only change
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


PUBLIC = ("pick_key", "date", "league", "status", "format", "reason", "stat", "player", "player_id", "market", "selection", "team", "home", "away", "line", "price", "model_prob",
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
    for r in rows:
        if r["status"] == "pick" and r.get("market") != "prop":
            r["format"] = "game_line_before_props_only"     # recorded before the props-only change; kept as recorded
    props = [r for r in rows if r.get("format") != "game_line_before_props_only"]
    rec = {lg: summary([r["result"] for r in props if r["league"] == lg and r["status"] == "pick"]) for lg in ("nba", "nfl")}

    def card(lg):
        r = next((x for x in rows if x["league"] == lg and x["date"] == today), None)
        if r is not None and r.get("format") == "game_line_before_props_only":
            return {"pick_key": r["pick_key"], "date": today, "league": lg, "status": "no_pick", "format": "player_prop",
                    "reason": "no approved player-prop line source", "selected_at": r["selected_at"], "result": "none"}
        return r
    return {"generated_at": now.isoformat(timespec="seconds"), "date": today,
            "today": {lg: card(lg) for lg in ("nba", "nfl")},
            "history": rows, "record": rec, "rule": {"min_prob": MIN_PROB, "min_edge": MIN_EDGE, "unvalidated_until": UNVALIDATED_UNTIL},
            "notice": ("Unvalidated. Model Room has not shown an edge against the market yet: these are the model's strongest "
                       "disagreements with the consensus line, not guaranteed results and not betting advice."),
            "limits": LIMITS}
