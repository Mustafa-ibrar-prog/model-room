"""Picks: what the model selected before a game, frozen once, and graded against what happened.

A projection is a number ("Boston by 9.4"). A pick is a side ("Boston -7.5"). The prediction ledgers record
projections; this module turns the last projection recorded before a game into picks, writes each pick ONCE to an
append-only, hash-chained picks ledger, and from then on only ever reads it back. Grading therefore uses the stored
selection, market, line and team/player identity. The final score is never used to decide which side was picked.

How a pick is selected (always from a record written before the game started, never recomputed afterwards):
  moneyline   the team the recorded win probability favoured (exactly 50%: no pick)
  spread      the side of the pre-game market spread the recorded margin fell on (exactly on the line: no pick)
  total       over or under the pre-game market total, by the recorded projected total (exactly on it: no pick)
  player prop the model's own threshold nearest its projection: "20 or more" when the recorded probability was above
              50%, "under 20" when below (exactly 50%: no pick). No sportsbook line is involved, and none is invented;
              when a market line is published in future the pick is over/under that line and can push.

Spread and total picks exist only for games that had a market line captured before kickoff (consensus of at least
two books). Without one there is nothing to pick a side of, so there is no pick.

When a pick is written: at the last refresh before a game (the pre-game refresh runs 30 minutes before every start),
so the side and the line are on record before anything is known about the result. A spread or total pick is ONLY
ever written before the start: its line is not part of the model's own prediction record, so one reconstructed
afterwards would not be a recorded selection, and no such pick is created. The winner and the player thresholds are
in the hash-chained prediction ledger with their probabilities, so if the pre-game refresh was missed those picks
are still written from that record within 48 hours (frozen_before_start: false), and for games played before this
ledger existed they were written once from it (backfilled: true).

Results:  hit | miss | push | void | cancelled | pending
  void       the bet would not have had action: the player did not play
  cancelled  the game was postponed or cancelled
  pending    the game has started but a verified final score or stat is not on file yet
Only hit, miss and push count as graded; the hit rate is hit / (hit + miss).

Files (preview-ledger/, all append-only):
  picks_<league>.jsonl                        game picks, one line per pick, hash-chained like the prediction ledger
  picks_<league>_props[_week_<tag>].jsonl     player-prop picks, as a weekly series
  pick_grades_<league>[_week_<tag>].jsonl     every settlement and every later correction, with the reason
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from modelroom.common import ledger
from modelroom.common.paths import ledger_path

GRADED = ("hit", "miss", "push")
TERMINAL = ("hit", "miss", "push", "void", "cancelled")


# ------------------------------------------------------------------ selection (from pre-game records only)
def _source(rec: dict) -> dict:
    return {"seq": rec.get("seq"), "generated_at": rec["generated_at"], "model_version": rec["model_version"], "hash": rec.get("hash")}


def _base(league: str, game: dict, rec: dict, market: str, suffix: str = "") -> dict:
    return {
        "game_id": f"{league}:{game['game_id']}:{market}{suffix}",  # the ledger's unique key: one line per pick, ever
        "league": league, "league_game_id": str(game["game_id"]), "date": game["date"], "home": game["home"], "away": game["away"],
        "market": market, "model_version": rec["model_version"], "generated_at": rec["generated_at"], "game_start": rec["game_start"],
        "inputs_hash": (rec.get("hash") or "")[:16], "params_hash": None, "source": _source(rec),
    }


def game_picks(league: str, game: dict, rec: dict | None, market: dict | None) -> list[dict]:
    """Moneyline, spread and total picks for one game from its last pre-game ledger record. `market` is the
    pre-kickoff consensus {spread (home line), total, books, captured_at, sources} or None."""
    if not rec:
        return []
    out = []
    p = rec.get("home_win_prob")
    if p is not None and p != 0.5:
        side = "home" if p > 0.5 else "away"
        out.append({**_base(league, game, rec, "moneyline"), "selection": side, "team": game[side], "line": None,
                    "model_prob": round(p if side == "home" else 1 - p, 4), "model_number": rec.get("pred_margin")})
    if market:
        src = {"line_source": ",".join(sorted(market.get("sources") or [])) or None, "line_captured_at": market.get("captured_at"),
               "line_books": market.get("books")}
        sp = market.get("spread")
        if sp is not None and rec.get("pred_margin") is not None:
            v = rec["pred_margin"] + sp  # > 0: the model has the home side covering
            if v != 0:
                side = "home" if v > 0 else "away"
                out.append({**_base(league, game, rec, "spread"), "selection": side, "team": game[side],
                            "home_line": float(sp), "line": float(sp if side == "home" else -sp),
                            "model_number": rec["pred_margin"], **src})
        tot = market.get("total")
        if tot is not None and rec.get("pred_total") is not None and rec["pred_total"] != tot:
            out.append({**_base(league, game, rec, "total"), "selection": "over" if rec["pred_total"] > tot else "under",
                        "team": None, "line": float(tot), "model_number": rec["pred_total"], **src})
    return out


def prop_picks(league: str, game: dict, rec: dict, labels: dict | None = None) -> list[dict]:
    """One pick per stat for one player from his last pre-game ledger record: the recorded threshold nearest the
    recorded projection, on the side the recorded probability favoured."""
    out = []
    for mkey, probs in (rec.get("probabilities") or {}).items():
        mean = probs.get("mean")
        ladder = {float(k): float(v) for k, v in probs.items() if k not in ("mean", "sd", "support")}
        if mean is None or not ladder:
            continue
        k = min(ladder, key=lambda t: (abs(t - mean), t))
        p = ladder[k]
        if p == 0.5:
            continue
        side = "at_least" if p > 0.5 else "below"
        # Kept small on purpose: there are about a thousand of these a night, and the line never changes once written.
        out.append({"game_id": f"{league}:{game['game_id']}:prop:{rec['player_id']}:{mkey}", "league_game_id": str(game["game_id"]),
                    "date": game["date"], "market": "prop", "selection": side, "team": rec.get("team"),
                    "player": rec["player"], "player_id": str(rec["player_id"]), "stat": mkey,
                    "line": k, "line_kind": "model_threshold", "model_prob": round(p if side == "at_least" else 1 - p, 4),
                    "model_number": mean, "support": probs.get("support") or rec.get("support"),
                    "model_version": rec["model_version"], "generated_at": rec["generated_at"], "game_start": rec["game_start"],
                    "inputs_hash": (rec.get("hash") or "")[:16], "params_hash": None, "source_seq": rec.get("seq")})
    return out


# ------------------------------------------------------------------ grading (stored pick + verified result)
def is_cancelled(status: str | None) -> bool:
    s = (status or "").lower()
    return "postpon" in s or "cancel" in s


def grade(pick: dict, status: str | None, final: dict | None, actual: float | None = None, played: bool | None = None) -> str:
    """How a stored pick settled. `final` = {"home": int, "away": int} once the score is verified final;
    `actual` = the player's verified stat; `played` = whether he took part (False: void)."""
    if is_cancelled(status):
        return "cancelled"
    if final is None:
        return "pending"
    m, sel = pick["market"], pick["selection"]
    margin = final["home"] - final["away"]  # from the home side
    if m == "moneyline":
        if margin == 0:
            return "push"
        return "hit" if (margin > 0) == (sel == "home") else "miss"
    if m == "spread":
        v = (margin if sel == "home" else -margin) + pick["line"]  # the selected team's margin plus its own line
        return "push" if v == 0 else ("hit" if v > 0 else "miss")
    if m == "total":
        t = final["home"] + final["away"]
        if t == pick["line"]:
            return "push"
        return "hit" if (t > pick["line"]) == (sel == "over") else "miss"
    if m == "prop":
        if played is False:
            return "void"
        if actual is None:
            return "pending"
        line = pick["line"]
        if sel == "at_least":
            return "hit" if actual >= line else "miss"
        if sel == "below":
            return "hit" if actual < line else "miss"
        if actual == line:  # over / under a market line: landing exactly on it is a push
            return "push"
        return "hit" if (actual > line) == (sel == "over") else "miss"
    raise ValueError(f"unknown market {m!r}")


# ------------------------------------------------------------------ the picks ledger (write once, read forever)
def picks_path(league: str) -> Path:
    return ledger_path(f"picks_{league}")


def prop_picks_path(league: str) -> Path:
    return ledger_path(f"picks_{league}_props")


def read_picks(league: str) -> dict:
    """{pick id: stored pick}. The first line recorded for an id is the pick; nothing ever replaces it."""
    out: dict = {}
    for r in [*ledger.read(picks_path(league)), *ledger.read_series(prop_picks_path(league))]:
        out.setdefault(r["game_id"], r)
    return out


def freeze(league: str, candidates: list[dict], now: datetime, backfilled_before: str | None = None) -> dict:
    """Write picks that are not in the ledger yet. A pick already there is never rewritten, whatever today's data
    would now say. `backfilled_before`: picks for games that started before this instant are marked as reconstructed
    from pre-game records after the fact (the first run of this ledger), so the page can say so."""
    have = read_picks(league)
    stamp = now.isoformat(timespec="seconds")
    new_games, new_props = [], []
    for c in candidates:
        if c["game_id"] in have:
            continue
        row = {**c, "frozen_at": stamp, "backfilled": bool(backfilled_before and c["game_start"] < backfilled_before)}
        (new_props if c["market"] == "prop" else new_games).append(row)
        have[c["game_id"]] = row
    a = ledger.append(picks_path(league), new_games)
    b = ledger.append_weekly(prop_picks_path(league), now, new_props)
    return {"game_picks_added": a.appended, "prop_picks_added": b.appended, "rejected": a.rejected_started + b.rejected_started}


# ------------------------------------------------------------------ the grade log (settlements and corrections)
def _chain_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def grades_files(league: str) -> list[Path]:
    base = ledger_path(f"pick_grades_{league}")
    return sorted(base.parent.glob(f"{base.stem}_week_*.jsonl"))


def read_grades(league: str) -> dict:
    """{pick id: latest grade record}."""
    out: dict = {}
    for f in grades_files(league):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["pick_id"]] = r
    return out


def verify_grades(league: str) -> dict:
    """Check every grade file's hash chain. {file name: lines}."""
    res = {}
    for f in grades_files(league):
        prev, n = ledger.GENESIS, 0
        for i, line in enumerate([x for x in f.read_text(encoding="utf-8").splitlines() if x.strip()], start=1):
            r = json.loads(line)
            body = {k: v for k, v in r.items() if k != "hash"}
            if r.get("seq") != i or r.get("prev_hash") != prev or _chain_hash(body) != r.get("hash"):
                raise ledger.LedgerError(f"{f.name}: grade log broken at line {i}")
            prev, n = r["hash"], i
        res[f.name] = n
    return res


def _describe(evidence: dict | None) -> str:
    if not evidence:
        return "nothing on file"
    if "actual" in evidence:
        return f"stat {evidence['actual']}" if evidence.get("played") is not False else "did not play"
    return f"{evidence.get('away_score')}-{evidence.get('home_score')} (away-home)"


def record_grades(league: str, graded: list[dict], now: datetime) -> dict:
    """Append a line for every pick that has just settled, and a correction line for every settled pick whose result
    has changed since it was last recorded (a corrected score or stat). Earlier lines are never edited, so the log
    shows what the site said at each point and why it changed.

    `graded`: [{"pick_id", "result", "evidence": {...}}]; pending picks are not logged."""
    last = read_grades(league)
    stamp = now.isoformat(timespec="seconds")
    f = ledger.weekly_path(ledger_path(f"pick_grades_{league}"), now)
    existing = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []
    prev = existing[-1]["hash"] if existing else ledger.GENESIS
    seq = existing[-1]["seq"] if existing else 0
    lines, settled, corrected = [], 0, 0
    for g in graded:
        if g["result"] == "pending":
            continue
        old = last.get(g["pick_id"])
        if old and old["result"] == g["result"] and old.get("evidence") == g.get("evidence"):
            continue
        body = {"pick_id": g["pick_id"], "result": g["result"], "evidence": g.get("evidence"), "graded_at": stamp,
                "kind": "correction" if old else "settled"}
        if old:
            body["previous"] = {"result": old["result"], "evidence": old.get("evidence"), "graded_at": old["graded_at"]}
            body["reason"] = f"verified result changed: was {_describe(old.get('evidence'))}, now {_describe(g.get('evidence'))}"
            corrected += 1
        else:
            settled += 1
        seq += 1
        body.update(seq=seq, prev_hash=prev)
        body["hash"] = _chain_hash(body)
        lines.append(json.dumps(body, sort_keys=True, separators=(",", ":")))
        prev = body["hash"]
    if lines:
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
    return {"settled": settled, "corrections": corrected}


# ------------------------------------------------------------------ what the site shows
def record_of(results: list[str]) -> dict:
    c = {k: results.count(k) for k in ("hit", "miss", "push", "void", "cancelled", "pending")}
    decided = c["hit"] + c["miss"]
    return {**c, "graded": decided + c["push"], "hit_rate": round(c["hit"] / decided, 4) if decided else None}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
