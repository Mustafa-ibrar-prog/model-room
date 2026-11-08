"""How the engines read the injury feed, and the explanations the site shows when a projection moves.

  load(league)                 current, non-stale feed rows (None when no feed was fetched this run)
  availability_hash(league)    folded into each engine's inputs hash, so a changed injury picture writes a NEW
                               ledger snapshot (older snapshots stay exactly as recorded)
  nba_availability(...)        {(game_id, team): availability} for the NBA prop model (0.2.1)
  game_flags(...)              the designated players per team-game, for the game boards
  explain(prev, new, ...)      "what changed and why" per player, versus the previous published board
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from modelroom.common.paths import data_root, processed_dir

FLAG_STATUSES = ("out", "doubtful", "questionable", "probable")


def load(league: str) -> pd.DataFrame | None:
    f = processed_dir(league) / "injury_feed.parquet"
    if not f.exists():
        return None
    d = pd.read_parquet(f)
    return d[d["current"].astype(bool) & ~d["stale"].astype(bool)].copy()


def live_meta(league: str) -> dict | None:
    f = data_root() / "published" / f"injuries_live_{league}.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text())
    except ValueError:
        return None
    return {"generated_at": d.get("generated_at"), "sources": d.get("sources"), "filings": d.get("filings") or [], "conflicts": d.get("conflicts")}


def availability_hash(league: str) -> str:
    d = load(league)
    parts = [] if d is None else sorted(f"{r.player_id}|{r.status}|{r.restriction_minutes}" for r in d.itertuples())
    s = processed_dir(league) / ("starters_live.parquet" if league == "nba" else "starters.parquet")
    if s.exists():
        x = pd.read_parquet(s)
        if league == "nfl":
            x = x[x["status"] == "scheduled"]
            parts += sorted(f"{r.game_id}|{r.team}|{r.qb_id}" for r in x.itertuples())
        elif {"espn_event", "source_player_id", "starter"} <= set(x.columns):
            parts += sorted(f"{r.espn_event}|{r.source_player_id}|{r.starter}" for r in x.itertuples())
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def game_availability_hashes(league: str, games: pd.DataFrame) -> dict:
    """{game_id: hash} of ONE game's injury picture: the same ingredients as availability_hash() (feed statuses and
    restrictions, projected NFL starting QBs), limited to that game's two teams. games: game_id, home_team, away_team."""
    d = load(league)
    s = processed_dir(league) / ("starters_live.parquet" if league == "nba" else "starters.parquet")
    st = pd.read_parquet(s) if s.exists() else None
    out = {}
    for g in games.itertuples():
        teams = {g.home_team, g.away_team}
        parts = [] if d is None else sorted(f"{r.player_id}|{r.status}|{r.restriction_minutes}" for r in d.itertuples() if r.team in teams)
        if st is not None and league == "nfl" and {"game_id", "team", "qb_id"} <= set(st.columns):
            x = st[(st["game_id"].astype(str) == str(g.game_id))]
            parts += sorted(f"{r.game_id}|{r.team}|{r.qb_id}" for r in x.itertuples())
        out[str(g.game_id)] = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return out


def nba_availability(upcoming: pd.DataFrame, player_games: pd.DataFrame) -> dict:
    from modelroom.nba.props import model as M
    from modelroom.nba.props import returns

    d = load("nba")
    if d is None:
        return {}
    meta = live_meta("nba") or {}
    submitted = {(f["game_date"], f["team"]) for f in meta.get("filings", []) if f.get("submitted")}
    st_f = processed_dir("nba") / "starters_live.parquet"
    st = pd.read_parquet(st_f) if st_f.exists() else pd.DataFrame()
    for c in ("espn_event", "team", "source_player_id", "starter"):
        if c not in st:
            st[c] = pd.Series(dtype=object)
    back = returns.current_back(player_games, d["player_id"].astype(str).tolist() + player_games.loc[player_games["season"] == player_games["season"].max(), "player_id"].astype(str).unique().tolist())
    out = {}
    for g in upcoming.itertuples():
        gd = str(pd.Timestamp(g.start_time).tz_convert("America/New_York").date())
        for team in (g.home_abbr, g.away_abbr):
            rows = d[d["team"] == team]
            starters = st[(st["espn_event"].astype(str) == str(g.game_id)) & (st["team"] == team) & st["starter"].astype(bool)]
            out[(str(g.game_id), team)] = M.availability(rows, back, (gd, team) in submitted, set(starters["source_player_id"].astype(str)) or None)
    return out


def _stamp(r) -> str | None:
    return None if pd.isna(r.report_time) else pd.Timestamp(r.report_time).isoformat()


def game_flags(league: str, teams: list[str]) -> dict:
    """{team: [{player, position, status, raw_status, source, confirmed, report_time, detail, late_scratch, conflict}]}"""
    d = load(league)
    if d is None:
        return {}
    d = d[d["team"].isin(teams) & d["status"].isin(FLAG_STATUSES)]
    order = {"out": 0, "doubtful": 1, "questionable": 2, "probable": 3}
    out: dict = {}
    for r in d.sort_values("status", key=lambda s: s.map(order)).itertuples():
        out.setdefault(r.team, []).append({"player": r.player, "player_id": str(r.player_id), "position": r.position, "status": r.status,
                                           "raw_status": r.raw_status, "source": r.source, "confirmed": r.kind == "official",
                                           "report_time": _stamp(r), "detail": r.detail if isinstance(r.detail, str) else None,
                                           "long_term": bool(r.long_term), "late_scratch": bool(getattr(r, "late_scratch", False)),
                                           "restriction": bool(r.restriction), "conflict": getattr(r, "conflict", None) or None})
    return out


def context(entry: dict) -> dict:
    """The injury picture behind one published player entry (what explain() compares)."""
    i = entry.get("inputs") or {}
    a = i.get("availability") or {}
    if i.get("teammates_out_detail") is not None:
        mates = tuple(sorted(t["name"] for t in i["teammates_out_detail"]))
    else:
        mates = tuple(sorted(x for x in (i.get("teammates_out") or "").split(", ") if x))
    return {"own": a.get("status") or entry.get("injury_status"), "notes": tuple(a.get("notes") or ()), "teammates_out": mates,
            "qb": i.get("starting_qb")}


def explain(prev_board: dict | None, games: list[dict], markets: tuple[str, ...], min_rel: float = 0.05, min_abs: float = 0.5) -> int:
    """Adds entry["changes"] = [{market, from, to, reasons, previous_at}] where a projection moved since the previous
    published board AND the player's injury picture changed. Returns how many players got an explanation."""
    if not prev_board:
        return 0
    prev = {(g["game_id"], str(p["player_id"])): p for g in prev_board.get("games", []) for p in g.get("players", [])}
    at = prev_board.get("generated_at")
    n = 0
    for g in games:
        for e in g.get("players", []):
            old = prev.get((g["game_id"], str(e["player_id"])))
            if not old:
                continue
            c0, c1 = context(old), context(e)
            reasons = []
            if c0["own"] != c1["own"]:
                reasons.append(f"his status: {c0['own'] or 'not listed'} → {c1['own'] or 'not listed'}")
            for t in sorted(set(c1["teammates_out"]) - set(c0["teammates_out"])):
                if t:
                    reasons.append(f"teammate out: {t}")
            for t in sorted(set(c0["teammates_out"]) - set(c1["teammates_out"])):
                if t:
                    reasons.append(f"teammate back: {t}")
            if c0["qb"] != c1["qb"] and c1["qb"]:
                reasons.append(f"starting QB: {c0['qb'] or 'unknown'} → {c1['qb']}")
            reasons += [x for x in c1["notes"] if x not in c0["notes"]]
            if not reasons:
                continue
            ch = []
            for mk in markets:
                a, b = (old.get("markets") or {}).get(mk, {}).get("mean"), (e.get("markets") or {}).get(mk, {}).get("mean")
                if a is None or b is None:
                    continue
                if abs(b - a) >= max(min_abs, min_rel * max(abs(a), 1e-9)):
                    ch.append({"market": mk, "label": e["markets"][mk].get("label", mk), "from": a, "to": b})
            if ch:
                e["changes"] = {"previous_at": at, "reasons": reasons, "markets": ch}
                n += 1
    return n


def attach_game_flags(league: str, games: list[dict]) -> None:
    """games[i]["availability"] = designated players per side + feed time/sources (None when no feed this run)."""
    meta = live_meta(league)
    if load(league) is None or meta is None:
        for g in games:
            g["availability"] = None
        return
    flags = game_flags(league, [g["home"]["abbr"] for g in games] + [g["away"]["abbr"] for g in games])
    srcs = sorted(k for k, v in (meta.get("sources") or {}).items() if v.get("ok"))
    for g in games:
        g["availability"] = {"home": flags.get(g["home"]["abbr"], []), "away": flags.get(g["away"]["abbr"], []),
                             "updated_at": meta.get("generated_at"), "sources": srcs}


def explain_games(prev_board: dict | None, games: list[dict], min_points: float = 0.5) -> int:
    """game["changes"] when the projected margin or total moved since the previous board and the starting QBs or
    the designated players changed. Reasons name what changed; nothing is attributed when nothing did."""
    if not prev_board:
        return 0
    prev = {g["game_id"]: g for g in prev_board.get("upcoming", [])}
    n = 0
    for g in games:
        o = prev.get(g["game_id"])
        if not o:
            continue
        reasons = []
        for side in ("home", "away"):
            q0, q1 = (o.get("quarterbacks") or {}).get(side), (g.get("quarterbacks") or {}).get(side)
            if q1 and q0 != q1:
                reasons.append(f"{g[side]['abbr']} starting QB: {q0 or 'unknown'} → {q1}")
            a0 = {(x["player"], x["status"]) for x in ((o.get("availability") or {}).get(side) or [])}
            a1 = {(x["player"], x["status"]) for x in ((g.get("availability") or {}).get(side) or [])}
            for pl, stt in sorted(a1 - a0):
                if stt in ("out", "doubtful"):
                    reasons.append(f"{g[side]['abbr']}: {pl} now {stt}")
            for pl, stt in sorted(a0 - a1):
                if stt in ("out", "doubtful") and (pl, stt) not in a1 and not any(p == pl for p, _ in a1):
                    reasons.append(f"{g[side]['abbr']}: {pl} no longer listed {stt}")
        if not reasons:
            continue
        p0, p1 = o.get("projection") or {}, g.get("projection") or {}
        moved = {k: {"from": p0.get(k), "to": p1.get(k)} for k in ("margin", "total", "home_win_prob")
                 if p0.get(k) is not None and p1.get(k) is not None and abs(p1[k] - p0[k]) >= (0.01 if k == "home_win_prob" else min_points)}
        if moved:
            g["changes"] = {"previous_at": prev_board.get("generated_at"), "reasons": reasons, "moved": moved}
            n += 1
    return n
