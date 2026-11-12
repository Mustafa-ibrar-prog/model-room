"""Historical sportsbook analysis (TEST site): line histories, movement, coverage, model-vs-book comparisons at
matching timestamps, and settled-game evaluation, built on the append-only table odds.snapshots.

    python -m modelroom markets sportsbook nba     (and nfl; leagues are always analysed separately)

What it reads (nothing here changes a model, a probability, a grade or a stored record):
  odds.snapshots             every sportsbook line Model Room collected (7 AM / noon PT fetches only)
  preview-ledger/<lg>.jsonl  the game-prediction ledger (immutable, timestamped pre-game predictions)
  the schedule / final scores (from the regular data ingest)
  preview-ledger/odds_api_usage.jsonl  credits

What it writes:
  odds.comparisons  (private, append-only, hash-chained) one row per snapshot matched to the LATEST game prediction
                    recorded before that snapshot was collected; the model's probability at that exact line next to
                    the book's implied probability with and without its margin. Unvalidated comparisons.
  odds.reports      (private, append-only, hash-chained) the detailed report of this run (contains lines).
  preview-ledger/reports/sportsbook_<lg>.json  (public repo) aggregate counts and rates only, no sportsbook lines,
                    because the repository is public and the data provider's terms don't allow redistribution.

Labels, always:
  "earliest observed" / "latest observed, N h before start"   never "opening" / "closing": Model Room fetches at
      7 AM and noon PT, so the true opener and the close are not observed.
  Closing-line value: disabled until a genuine closing line exists (a snapshot within CLOSE_WINDOW_MIN of the start).
  Settled-game summary statistics: only from GATE settled games per league and market; below that, counts only.
  No profitability, return or edge is computed or claimed.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common import oddsmath as O

GATE = 250                 # settled games per league and market before any summary statistic is published
STALE_HOURS = 6.0          # a line whose own book timestamp is older than this when collected is "stale"
COVERAGE_HOURS = 72.0      # "scheduled games without lines" looks only this far ahead of each fetch
CLOSE_WINDOW_MIN = 10.0    # an observation this close to the start would count as a genuine closing line
MARKETS = ("spread", "total", "moneyline")
SIDES = {"spread": ("home_price", "away_price", "home", "away"), "moneyline": ("home_price", "away_price", "home", "away"),
         "total": ("over_price", "under_price", "over", "under")}
NOTICE = ("Historical sportsbook record and unvalidated model-vs-book comparisons. Lines are the earliest and latest "
          "observed by Model Room's 7 AM / noon PT fetches; they are not opening or closing lines. No profitability, "
          "return or betting edge is claimed. Summary statistics appear only once a league and market has "
          f"{GATE} settled games.")


def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def _r(x, n=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


# ------------------------------------------------------------------ preparation (pure)
def prepare(snaps: pd.DataFrame) -> pd.DataFrame:
    """Typed timestamps, a stable series key and implied probabilities for every snapshot row."""
    S = snaps.copy()
    S["collected_ts"] = pd.to_datetime(S["collected_at"], utc=True, errors="coerce")
    S["captured_ts"] = pd.to_datetime(S["captured_at"], utc=True, errors="coerce")
    S["commence_ts"] = pd.to_datetime(S["commence_time"], utc=True, errors="coerce")
    S["game_key"] = [str(g) if g is not None and not (isinstance(g, float) and math.isnan(g)) else f"{h}|{a}|{c}"
                     for g, h, a, c in zip(S["game_id"], S["home_team"], S["away_team"], S["commence_time"])]
    S["matched_game"] = S["game_id"].notna()
    S["fetch"] = S["collected_at"]
    S["hours_before_start"] = (S["commence_ts"] - S["collected_ts"]).dt.total_seconds() / 3600
    S["pre_start"] = S["hours_before_start"] > 0
    S["book_age_hours"] = (S["collected_ts"] - S["captured_ts"]).dt.total_seconds() / 3600
    S["stale"] = S["book_age_hours"] > STALE_HOURS
    ra, rb, oa, nb, na_, nbb = [], [], [], [], [], []
    for m, r in zip(S["market"], S.itertuples(index=False)):
        a_col, b_col, _, _ = SIDES.get(m, SIDES["moneyline"])
        a, b = O.implied(getattr(r, a_col)), O.implied(getattr(r, b_col))
        da, db = O.devig(getattr(r, a_col), getattr(r, b_col))
        ra.append(a); rb.append(b); oa.append(None if a is None or b is None else a + b - 1); na_.append(da); nbb.append(db)
    S["implied_a"], S["implied_b"], S["overround"], S["novig_a"], S["novig_b"] = ra, rb, oa, na_, nbb
    S = S.sort_values(["game_key", "sportsbook", "market", "collected_ts"]).reset_index(drop=True)
    g = S.groupby(["game_key", "sportsbook", "market"], sort=False)
    prev_line, prev_a, prev_b = g["line"].shift(1), g["implied_a"].shift(1), g["implied_b"].shift(1)
    S["obs_no"] = g.cumcount() + 1
    same = lambda x, y: (x.isna() & y.isna()) | ((x - y).abs() < 1e-9)
    S["unchanged_since_prev"] = (S["obs_no"] > 1) & same(S["line"], prev_line) & same(S["implied_a"], prev_a) & same(S["implied_b"], prev_b)
    return S


def latest_label(hours: float | None) -> str:
    if hours is None or (isinstance(hours, float) and math.isnan(hours)):
        return "latest observed (start time unknown)"
    if hours <= 0:
        return "observed after the start (excluded from pre-game analysis)"
    return f"latest observed, {hours:.1f} h before start (not a closing line)"


# ------------------------------------------------------------------ line histories and movement (pure)
def _obs(r) -> dict:
    return {"collected_at": r.collected_at, "book_updated_at": r.captured_at, "line": _num(r.line),
            "price_a": _num(getattr(r, SIDES[r.market][0])), "price_b": _num(getattr(r, SIDES[r.market][1])),
            "novig_a": _r(r.novig_a), "hours_before_start": _r(r.hours_before_start, 2)}


def line_histories(S: pd.DataFrame) -> list[dict]:
    """One entry per game x book x market, from pre-start observations: earliest, every intermediate, latest."""
    out = []
    P = S[S["pre_start"]]
    for (gk, book, mkt), d in P.groupby(["game_key", "sportsbook", "market"], sort=True):
        d = d.sort_values("collected_ts")
        first, last = d.iloc[0], d.iloc[-1]
        a_side, b_side = SIDES[mkt][2], SIDES[mkt][3]
        e = {"game_key": gk, "game_id": None if not first.matched_game else str(first.game_id), "home": first.home_team,
             "away": first.away_team, "commence_time": first.commence_time, "sportsbook": book, "market": mkt,
             "side_a": a_side, "side_b": b_side, "observations": int(len(d)),
             "earliest_observed": _obs(first), "intermediate": [_obs(r) for r in d.iloc[1:-1].itertuples(index=False)],
             "latest_observed": _obs(last) if len(d) > 1 else _obs(first),
             "latest_label": latest_label(float(last.hours_before_start)),
             "line_change": None, "novig_a_change": None, "direction": "unchanged"}
        if len(d) > 1:
            lc = None if pd.isna(first.line) or pd.isna(last.line) else float(last.line) - float(first.line)
            pc = None if first.novig_a is None or last.novig_a is None else float(last.novig_a) - float(first.novig_a)
            e["line_change"], e["novig_a_change"] = _r(lc, 2), _r(pc)
            e["direction"] = direction(mkt, lc, pc)
        out.append(e)
    return out


def direction(market: str, line_change, novig_a_change) -> str:
    """Which side the market moved toward between the earliest and latest observation."""
    if market == "spread" and line_change:
        return "toward home" if line_change < 0 else "toward away"   # home line more negative = home more favored
    if market == "total" and line_change:
        return "toward over" if line_change > 0 else "toward under"
    if novig_a_change and abs(novig_a_change) >= 0.005:
        return f"toward {SIDES[market][2]}" if novig_a_change > 0 else f"toward {SIDES[market][3]}"
    return "unchanged"


def movement_summary(H: list[dict]) -> dict:
    """Aggregates only (no line values): by book, by market, by team, plus a per-game count."""
    df = pd.DataFrame(H)
    if df.empty:
        return {"series": 0}
    df["moved"] = df["direction"] != "unchanged"
    multi = df[df["observations"] > 1]

    def agg(d):
        m = d[d["observations"] > 1]
        return {"series": int(len(d)), "series_with_2plus_observations": int(len(m)), "moved": int(m["moved"].sum()),
                "mean_abs_line_change": _r(m["line_change"].abs().mean(), 3) if m["line_change"].notna().any() else None,
                "mean_abs_novig_change_pp": _r(100 * m["novig_a_change"].abs().mean(), 2) if m["novig_a_change"].notna().any() else None}
    teams: dict = {}
    for r in multi.itertuples(index=False):
        if r.market == "total" or r.direction == "unchanged":
            continue
        toward = r.home if r.direction == "toward home" else r.away
        against = r.away if toward == r.home else r.home
        teams.setdefault(toward, {"moved_toward": 0, "moved_against": 0})["moved_toward"] += 1
        teams.setdefault(against, {"moved_toward": 0, "moved_against": 0})["moved_against"] += 1
    per_game = multi.groupby("game_key")["moved"].agg(["size", "sum"])
    return {"overall": agg(df), "by_market": {m: agg(d) for m, d in df.groupby("market")},
            "by_book": {b: agg(d) for b, d in df.groupby("sportsbook")},
            "by_team": dict(sorted(teams.items())),
            "games_with_any_movement": int((per_game["sum"] > 0).sum()), "games_with_repeat_observations": int(len(per_game))}


# ------------------------------------------------------------------ coverage, missing and stale (pure)
def coverage(S: pd.DataFrame, schedule: pd.DataFrame | None = None) -> tuple[dict, dict]:
    """(public aggregates, private detail) per fetch: books, games, missing books / markets, stale, unchanged."""
    fetches, detail = [], []
    for f, d in S.groupby("fetch", sort=True):
        books = sorted(d["sportsbook"].unique())
        games = d.groupby("game_key")
        miss_books, miss_mkts = 0, 0
        for gk, gd in games:
            gb = set(gd["sportsbook"])
            mb = [b for b in books if b not in gb]
            mm = {b: sorted(set(MARKETS) - set(x["market"])) for b, x in gd.groupby("sportsbook") if set(MARKETS) - set(x["market"])}
            miss_books += len(mb); miss_mkts += sum(len(v) for v in mm.values())
            if mb or mm:
                detail.append({"fetch": f, "game_key": gk, "missing_books": mb, "missing_markets_by_book": mm})
        no_lines = None
        if schedule is not None and len(schedule) and d["commence_ts"].notna().any():
            t0 = pd.to_datetime(f, utc=True)
            horizon = min(d["commence_ts"].max(), t0 + pd.Timedelta(hours=COVERAGE_HOURS))
            sch = schedule[schedule["start_ts"].notna() & (schedule["start_ts"] > t0) & (schedule["start_ts"] <= horizon)]
            no_lines = int((~sch["game_id"].astype(str).isin(set(d.loc[d["matched_game"], "game_id"].astype(str)))).sum())
        fetches.append({"collected_at": f, "rows": int(len(d)), "games": int(games.ngroups), "books": len(books),
                        "game_book_pairs_missing_a_book": miss_books, "missing_market_slots": miss_mkts,
                        "scheduled_games_next_72h_without_lines": no_lines,
                        "stale_rows": int(d["stale"].sum()), "unmatched_to_schedule_rows": int((~d["matched_game"]).sum()),
                        "unchanged_since_previous_fetch_rows": int(d["unchanged_since_prev"].sum())})
    pub = {"fetches": fetches,
           "rows_total": int(len(S)), "stale_rows_total": int(S["stale"].sum()), "stale_rule": f"book's own update time older than {STALE_HOURS:g} h when collected",
           "unchanged_rows_total": int(S["unchanged_since_prev"].sum()),
           "unchanged_rule": "same line and prices as the previous observation of that game, book and market (not necessarily stale)",
           "post_start_rows_excluded": int((~S["pre_start"]).sum()),
           "books_seen": sorted(S["sportsbook"].unique()), "markets_seen": sorted(S["market"].unique()),
           "rows_by_book": {k: int(v) for k, v in S["sportsbook"].value_counts().sort_index().items()},
           "rows_by_market": {k: int(v) for k, v in S["market"].value_counts().sort_index().items()}}
    priv = {"missing_by_game": detail,
            "stale_rows": S.loc[S["stale"], ["fetch", "game_key", "sportsbook", "market", "captured_at", "book_age_hours"]].assign(
                book_age_hours=lambda x: x["book_age_hours"].round(2)).to_dict("records")}
    return pub, priv


# ------------------------------------------------------------------ matching (pure): no prediction after the line
def model_index(records: list[dict]) -> dict:
    """game_id -> pre-game ledger records sorted by generated_at (records at/after the start are never used)."""
    idx: dict = {}
    for r in records:
        if r.get("generated_at") and r.get("game_start") and r["generated_at"] < r["game_start"]:
            idx.setdefault(str(r["game_id"]), []).append(r)
    for v in idx.values():
        v.sort(key=lambda r: r["generated_at"])
    return idx


def latest_before(recs: list[dict] | None, t: pd.Timestamp) -> dict | None:
    """The latest record generated strictly before t (None if there is none)."""
    best = None
    for r in recs or []:
        if pd.Timestamp(r["generated_at"]) < t:
            best = r
        else:
            break
    return best


def model_probs(market: str, rec: dict, line, sig: dict) -> dict | None:
    """Model probability of side a / push / side b at the book's exact line."""
    if market == "moneyline":
        h = _num(rec.get("home_win_prob"))
        return None if h is None else {"a": h, "push": 0.0, "b": 1 - h}
    if line is None or (isinstance(line, float) and math.isnan(line)):
        return None
    if market == "spread":
        s = sig.get("margin")
        if not s:
            return None
        c = O.cover_probs(float(rec["pred_margin"]), s, float(line))
        return {"a": c["home"], "push": c["push"], "b": c["away"]}
    s = sig.get("total")
    if not s:
        return None
    o = O.over_probs(float(rec["pred_total"]), s, float(line))
    return {"a": o["over"], "push": o["push"], "b": o["under"]}


def comparisons(S: pd.DataFrame, idx: dict, sigmas: dict) -> tuple[list[dict], dict]:
    """One comparison per pre-start snapshot row with a model prediction recorded before it was collected.
    sigmas: model_version -> {"margin", "total", "source"}."""
    out, why = [], {"post_start": 0, "not_matched_to_schedule": 0, "no_prediction_before_line": 0, "no_model_probability": 0}
    for r in S.itertuples(index=False):
        if not r.pre_start:
            why["post_start"] += 1; continue
        if not r.matched_game:
            why["not_matched_to_schedule"] += 1; continue
        rec = latest_before(idx.get(str(r.game_id)), r.collected_ts)
        if rec is None:
            why["no_prediction_before_line"] += 1; continue
        sig = sigmas.get(rec.get("model_version"), {})
        mp = model_probs(r.market, rec, r.line, sig)
        if mp is None:
            why["no_model_probability"] += 1; continue
        nopush = mp["a"] / (mp["a"] + mp["b"]) if (mp["a"] + mp["b"]) > 0 else None
        a_col, b_col, a_side, b_side = SIDES[r.market]
        out.append({
            "status": "unvalidated comparison", "snapshot_hash": r.snapshot_hash, "game_id": str(r.game_id),
            "home": r.home_team, "away": r.away_team, "commence_time": r.commence_time, "sportsbook": r.sportsbook,
            "market": r.market, "side_a": a_side, "side_b": b_side, "line": _num(r.line),
            "price_a": _num(getattr(r, a_col)), "price_b": _num(getattr(r, b_col)),
            "book_implied_a_with_margin": _r(r.implied_a), "book_implied_b_with_margin": _r(r.implied_b),
            "book_overround": _r(r.overround), "book_novig_a": _r(r.novig_a), "book_novig_b": _r(r.novig_b),
            "novig_method": "each side's implied probability / sum of both sides",
            "collected_at": r.collected_at, "book_updated_at": r.captured_at, "hours_before_start": _r(r.hours_before_start, 2),
            "line_label": "observed line (not opening or closing)",
            "model_version": rec.get("model_version"), "model_record_hash": rec.get("hash"), "model_generated_at": rec["generated_at"],
            "model_age_hours_at_line": _r((r.collected_ts - pd.Timestamp(rec["generated_at"])).total_seconds() / 3600, 2),
            "model_pred_margin": _num(rec.get("pred_margin")), "model_pred_total": _num(rec.get("pred_total")),
            "model_sigma": sig.get("margin") if r.market == "spread" else (sig.get("total") if r.market == "total" else None),
            "model_sigma_source": sig.get("source"),
            "model_prob_a": _r(mp["a"]), "model_prob_push": _r(mp["push"]), "model_prob_b": _r(mp["b"]),
            "model_prob_a_excl_push": _r(nopush),
            "model_minus_book_novig_a_pp": None if nopush is None or r.novig_a is None else _r(100 * (nopush - r.novig_a), 2)})
    return out, why


def comparison_key(c: dict) -> str:
    return f"{c['snapshot_hash']}|{c['model_record_hash']}"


# ------------------------------------------------------------------ settled vs upcoming (pure)
def outcome(market: str, line, home_score, away_score):
    """1 if side a won, 0 if side b won, None for a push / tie / missing score."""
    if home_score is None or away_score is None or pd.isna(home_score) or pd.isna(away_score):
        return None
    h, a = float(home_score), float(away_score)
    if market == "moneyline":
        return None if h == a else int(h > a)
    if line is None or pd.isna(line):
        return None
    v = (h - a + float(line)) if market == "spread" else (h + a - float(line))
    return None if v == 0 else int(v > 0)


def settled_events(C: list[dict], finals: dict) -> list[dict]:
    """One event per settled game and market: the books' latest pre-start observations, at the most common line;
    the market's no-vig probability (median across those books) and the model's probability at that line."""
    df = pd.DataFrame(C)
    if df.empty:
        return []
    df = df[df["game_id"].isin(finals)]
    ev = []
    for (gid, mkt), d in df.groupby(["game_id", "market"]):
        last = d.sort_values("collected_at").groupby("sportsbook").tail(1)
        if mkt != "moneyline":
            mode = last["line"].mode()
            if mode.empty:
                continue
            last = last[last["line"] == mode.iloc[0]]
        line = None if mkt == "moneyline" else float(last["line"].iloc[0])
        y = outcome(mkt, line, *finals[gid])
        if y is None or last["book_novig_a"].isna().all() or last["model_prob_a_excl_push"].isna().all():
            continue
        ev.append({"game_id": gid, "market": mkt, "line": line, "books": int(len(last)), "y": y,
                   "book_novig_a": float(last["book_novig_a"].median()), "model_prob_a": float(last["model_prob_a_excl_push"].median()),
                   "hours_before_start": float(last["hours_before_start"].median())})
    return ev


def _ll(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def settled_summary(events: list[dict], gate: int = GATE, seed: int = 7) -> dict:
    """Per market: counts always; summary statistics only at >= gate settled games."""
    df = pd.DataFrame(events)
    out = {}
    for mkt in MARKETS:
        d = df[df["market"] == mkt] if len(df) else df
        n = int(len(d))
        o = {"settled_games": n, "required_for_summary": gate, "progress_pct": round(100 * min(n, gate) / gate, 1)}
        if n < gate:
            o["status"] = f"insufficient sample: counts only until {gate} settled games"
            out[mkt] = o
            continue
        y = d["y"].to_numpy(); pm = d["model_prob_a"].to_numpy(); pb = d["book_novig_a"].to_numpy()
        llm, llb = _ll(pm, y), _ll(pb, y)
        bm, bb = (pm - y) ** 2, (pb - y) ** 2
        rng = np.random.default_rng(seed)
        boots = [(llm[i] - llb[i]).mean() for i in (rng.integers(0, n, n) for _ in range(2000))]
        cal = []
        for lo in np.arange(0, 1, 0.1):
            m = (pm >= lo) & (pm < lo + 0.1)
            if m.sum() >= 10:
                cal.append({"model_prob_bin": f"{lo:.1f}-{lo + 0.1:.1f}", "n": int(m.sum()), "mean_model_prob": _r(pm[m].mean()),
                            "observed_rate": _r(y[m].mean()), "mean_book_novig": _r(pb[m].mean())})
        o.update({"status": "summary published (historical evidence; latest observed lines, not closing lines)",
                  "model_log_loss": _r(llm.mean()), "book_novig_log_loss": _r(llb.mean()),
                  "model_minus_book_log_loss": _r((llm - llb).mean()),
                  "model_minus_book_log_loss_95ci": [_r(np.percentile(boots, 2.5)), _r(np.percentile(boots, 97.5))],
                  "model_brier": _r(bm.mean()), "book_novig_brier": _r(bb.mean()),
                  "side_a_rate": _r(y.mean()), "median_hours_before_start_of_lines": _r(float(np.median(d["hours_before_start"])), 1),
                  "calibration_by_model_prob": cal,
                  "interpretation": "Lower log loss / Brier = more accurate probabilities. A difference whose interval includes 0 is "
                                    "not evidence either way. This is an accuracy comparison, not a profitability measure."})
        out[mkt] = o
    return out


# ------------------------------------------------------------------ the whole report (pure given inputs)
def analyse(league: str, snaps: pd.DataFrame, ledger_records: list[dict], sigmas: dict, finals: dict,
            schedule: pd.DataFrame | None = None, usage: list[dict] | None = None, now: datetime | None = None) -> tuple[dict, dict, list[dict]]:
    """Returns (public aggregate report, private detailed report, comparison records)."""
    now = now or datetime.now(timezone.utc)
    S = prepare(snaps) if len(snaps) else snaps
    if len(S) == 0:
        empty = {"league": league, "generated_at": now.isoformat(timespec="seconds"), "notice": NOTICE, "snapshots": 0}
        return empty, empty, []
    H = line_histories(S)
    cov_pub, cov_priv = coverage(S, schedule)
    C, why = comparisons(S, model_index(ledger_records), sigmas)
    finals_ok = {g: v for g, v in finals.items()}
    ev = settled_events(C, finals_ok)
    settled_games = {c["game_id"] for c in C if c["game_id"] in finals_ok}
    upcoming_games = {c["game_id"] for c in C if c["game_id"] not in finals_ok}
    pre = S[S["pre_start"]]
    genuine_close = int((pre["hours_before_start"] * 60 <= CLOSE_WINDOW_MIN).sum())
    first, last = S["collected_ts"].min(), S["collected_ts"].max()
    acc = {"snapshot_rows": int(len(S)), "fetches": int(S["fetch"].nunique()),
           "first_collected_at": first.isoformat(), "last_collected_at": last.isoformat(),
           "days_of_history": round((last - first).total_seconds() / 86400, 2),
           "calendar_days_with_fetches": int(S["collected_ts"].dt.date.nunique()),
           "books": int(S["sportsbook"].nunique()), "games": int(S["game_key"].nunique()),
           "games_matched_to_schedule": int(S.loc[S["matched_game"], "game_key"].nunique()),
           "series_game_book_market": int(len(H)), "rows_by_market": cov_pub["rows_by_market"],
           "comparisons": {"matched": len(C), "not_matched": why,
                           "rule": "each line is paired only with the latest game prediction recorded before that line was collected"},
           "games_with_comparisons": {"settled": len(settled_games), "upcoming_or_unsettled": len(upcoming_games)},
           "settled_events_by_market": {m: int(sum(1 for e in ev if e["market"] == m)) for m in MARKETS},
           "gate": {m: {"settled": int(sum(1 for e in ev if e["market"] == m)), "required": GATE} for m in MARKETS}}
    if usage:
        month = now.strftime("%Y-%m")
        this = [u for u in usage if str(u.get("at", "")).startswith(month)]
        acc["odds_api"] = {"calls_logged": len(usage), "calls_this_month": len(this),
                           "credits_used_this_month_logged": int(sum(float(u.get("cost") or 0) for u in this)),
                           "credits_remaining_last_reported": usage[-1].get("remaining"), "as_of": usage[-1].get("at")}
    diffs = pd.Series([c["model_minus_book_novig_a_pp"] for c in C if c["game_id"] in upcoming_games and c["model_minus_book_novig_a_pp"] is not None], dtype=float)
    upcoming_pub = {"status": "unvalidated comparisons (games not settled)", "games": len(upcoming_games),
                    "comparisons": int(sum(1 for c in C if c["game_id"] in upcoming_games)),
                    "abs_model_minus_book_novig_pp": None if diffs.empty else {"median": _r(diffs.abs().median(), 2), "p90": _r(diffs.abs().quantile(0.9), 2)},
                    "note": "A difference is a disagreement between the model and the book, not a verified edge."}
    clv = {"status": "disabled", "reason": "no genuine closing line: lines are fetched at 7 AM and noon PT only",
           "observations_within_close_window": genuine_close, "close_window_minutes": CLOSE_WINDOW_MIN}
    mv = movement_summary(H)
    by_book = {"coverage_rows_by_book": cov_pub.pop("rows_by_book", None), "books_seen": cov_pub.pop("books_seen", None),
               "movement_by_book": mv.pop("by_book", None)}
    public = {"league": league, "generated_at": now.isoformat(timespec="seconds"), "notice": NOTICE,
              "accumulation": acc, "coverage": cov_pub, "movement": mv,
              "upcoming": upcoming_pub, "settled": settled_summary(ev), "closing_line_value": clv,
              "privacy": "Aggregates only, with no sportsbook named. Book-level and line-level detail is kept in the private "
                         "Supabase tables odds.comparisons and odds.reports."}
    # private detail: line histories, latest comparison per upcoming game/book/market, missing/stale, settled events
    latest_up = {}
    for c in C:
        if c["game_id"] in upcoming_games:
            k = (c["game_id"], c["sportsbook"], c["market"])
            if k not in latest_up or c["collected_at"] > latest_up[k]["collected_at"]:
                latest_up[k] = c
    private = {**public, **by_book, "line_histories": H, "coverage_detail": cov_priv,
               "upcoming_latest_comparisons": sorted(latest_up.values(), key=lambda c: (c["commence_time"], c["game_id"], c["sportsbook"], c["market"])),
               "settled_events": ev}
    names = list(S["sportsbook"].dropna().unique()) + (list(S["sportsbook_title"].dropna().unique()) if "sportsbook_title" in S.columns else [])
    leaks = book_names_in(public, names)
    if leaks:  # never publish a book's name: drop the report body rather than leak it
        public = {"league": league, "generated_at": public["generated_at"], "notice": NOTICE,
                  "withheld": f"public report withheld: it named {len(leaks)} sportsbook(s); detail kept privately"}
    return public, private, C


def book_names_in(report: dict, books) -> list[str]:
    """Sportsbook names (keys or titles) that appear anywhere in a report, compared case-insensitively."""
    text = json.dumps(report, default=str).lower()
    return sorted({b for b in books if isinstance(b, str) and len(b) > 2 and f'"{b.lower()}' in text})


# ------------------------------------------------------------------ I/O (used by the CLI / workflow)
def _sigmas(league: str) -> dict:
    """model_version -> sigmas: the version's own params file if it is the current version, else the published
    board's uncertainty (recorded as the source either way)."""
    out = {}
    try:
        if league == "nba":
            from modelroom.nba.config import MODEL_VERSION, ModelParams
            p = ModelParams.load(); ms, ts = p.adjustments.margin_sigma, p.adjustments.total_sigma
        else:
            from modelroom.nfl.config import MODEL_VERSION, ModelParams
            p = ModelParams.load(); ms, ts = p.points.margin_sigma, p.points.total_sigma
        out[MODEL_VERSION] = {"margin": float(ms), "total": float(ts), "source": f"params.json of {MODEL_VERSION}"}
    except Exception:  # noqa: BLE001
        pass
    return out


def run(league: str, write_store: bool = True) -> dict:
    import os

    from modelroom.common import ledger
    from modelroom.common.paths import ledger_path
    from modelroom.history import _games_table
    from modelroom.sources import odds as odds_mod
    from modelroom.sources import odds_store as S

    conn = S.connect()
    try:
        snaps = S.load_with_hashes(conn, league)
        recs = ledger.read(ledger_path(league))
        games = _games_table(league)
        fin = games[games["status"] == "final"]
        finals = {str(g): (h, a) for g, h, a in zip(fin["game_id"], fin["home_score"], fin["away_score"])}
        sched = games.assign(start_ts=pd.to_datetime(games["start_time"], utc=True, errors="coerce"))
        usage = []
        up = odds_mod.usage_log_path()
        if up.exists():
            usage = [json.loads(x) for x in up.read_text().splitlines() if x.strip()]
            usage = [u for u in usage if (u.get("league") == league)]
        public, private, C = analyse(league, snaps, recs, _sigmas(league), finals, sched, usage)
        res = {"league": league, "comparisons": len(C)}
        public.setdefault("accumulation", {})
        if write_store:
            run_id = os.environ.get("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%S")
            r1 = S.insert_payloads(conn, "comparisons", league, [(comparison_key(c), c) for c in C], "analysis", run_id)
            r2 = S.insert_payloads(conn, "reports", league, [(f"{run_id}|{league}|{public['generated_at']}", private)], "analysis", run_id)
            v1, v2 = S.verify_table(conn, "comparisons", league), S.verify_table(conn, "reports", league)
            public["accumulation"]["stored_comparisons"] = v1["rows"]
            public["storage_verification"] = {"comparisons_chain_ok": v1["ok"], "reports_chain_ok": v2["ok"],
                                              "snapshots_chain_ok": S.verify(conn, league)["ok"],
                                              "_expected_comparisons": len({comparison_key(c) for c in C})}
            res.update(new_comparisons=r1["inserted"], report_stored=r2["inserted"], **public["storage_verification"])
    finally:
        conn.close()
    if write_store:
        # What a later reader sees: committed rows only. A count below what this run inserted means nothing was kept.
        after = S.verify_after_reconnect(league)
        sv = public["storage_verification"]
        sv.update(after_reconnect={t: {"rows": v["rows"], "ok": v["ok"]} for t, v in after.items()})
        persisted = after["comparisons"]["rows"] >= sv.get("_expected_comparisons", 0) and after["reports"]["rows"] >= 1
        sv["persisted"] = bool(persisted)
        sv.pop("_expected_comparisons", None)
        public["accumulation"]["stored_comparisons"] = after["comparisons"]["rows"]
        res.update(persisted=sv["persisted"], after_reconnect=sv["after_reconnect"])
        if not persisted:
            print(f"::warning::{league} sportsbook analysis: records did not persist after the connection closed", flush=True)
    if not write_store:
        res["dry_run"] = True
        res["public_report"] = public
        return res
    out = Path(os.environ.get("MODELROOM_LEDGER_DIR", "preview-ledger")) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"sportsbook_{league}.json").write_text(json.dumps(public, indent=1, default=str))
    res["report"] = str(out / f"sportsbook_{league}.json")
    return res
