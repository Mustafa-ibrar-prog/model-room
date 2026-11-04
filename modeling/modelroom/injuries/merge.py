"""Combine the injury sources into one availability table the engines read.

    python -m modelroom injuries nba|nfl      → data/processed/<lg>/injury_feed.parquet (+ depth / starters)
                                                 data/published/injuries_live_<lg>.json (site)
                                                 preview-ledger/injury_snapshots_<lg>.jsonl (append-only)

Per player, one current status, chosen by these rules (each row records which applied):
  1. Identity: every source row is mapped to the engine's player id (ESPN id = NBA box-score id; NFL via
     nflverse's espn_id → gsis map). Official NBA rows are matched by name within the team.
  2. Staleness (a stale row is shown but never used as current):
       - a game designation (questionable / doubtful / probable) set before the team's previous game;
       - "out" reported before the player's most recent appearance (he has played since);
       - an official NBA row for a game date that has passed.
  3. Precedence: NBA: the league's official report for the team's next game wins over ESPN; a submitted
     team report that doesn't list a player means he is available. NFL: the most recent current row wins
     (ESPN usually carries the official Wed-Sat designations within minutes; nflverse's copy lags).
  4. Conflicts: when current rows from two sources disagree, the winner is used and the conflict is kept
     on the row and listed on the site.
  5. Missing data is never "healthy": a team whose official report is "not yet submitted", or a player
     with no current row, is left to the engine's own availability rule and flagged as unconfirmed.
  6. Late scratch: a player newly ruled out / doubtful within 3 hours of his game, versus the previous
     snapshot, is flagged.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from modelroom.common.paths import data_root, ledger_path, processed_dir

from . import schema as S

LATE_SCRATCH_HOURS = 3.0


def schedule(league: str, now: pd.Timestamp) -> pd.DataFrame:
    """team, prev_start, next_start, next_game_id, next_game_date (US Eastern date)."""
    g = pd.read_parquet(processed_dir(league) / "games.parquet")
    h, a = ("home_abbr", "away_abbr") if league == "nba" else ("home_team", "away_team")
    g = g.assign(start=pd.to_datetime(g["start_time"], utc=True))
    long = pd.concat([g[[h, "start", "game_id"]].rename(columns={h: "team"}), g[[a, "start", "game_id"]].rename(columns={a: "team"})])
    rows = []
    for t, x in long.groupby("team"):
        past, fut = x[x["start"] <= now], x[x["start"] > now - pd.Timedelta(hours=4)]
        nxt = fut.sort_values("start").iloc[0] if len(fut) else None
        rows.append({"team": t, "prev_start": past["start"].max() if len(past) else pd.NaT,
                     "next_start": nxt["start"] if nxt is not None else pd.NaT, "next_game_id": nxt["game_id"] if nxt is not None else None,
                     "next_game_date": str(nxt["start"].tz_convert("America/New_York").date()) if nxt is not None else None})
    return pd.DataFrame(rows)


def _id_maps(league: str) -> tuple[dict, dict]:
    """(espn id → engine id, engine id → last appearance start)."""
    if league == "nba":
        from modelroom.nba.props import data

        b = data.load()
        b = b[b["played"].astype(bool)]
        last = pd.to_datetime(b["game_date"]).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
        return {}, b.assign(t=last).groupby(b["player_id"].astype(str))["t"].max().to_dict()
    from modelroom.nfl import player_data

    ro = player_data.rosters(sorted(pd.read_parquet(processed_dir("nfl") / "games.parquet")["season"].unique().tolist())[-3:])
    m = ro.dropna(subset=["espn_id", "gsis_id"]).assign(espn_id=lambda x: x["espn_id"].astype(str).str.replace(r"\.0$", "", regex=True))
    pg, _, _ = player_data.load()
    pg = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].fillna(0).sum(axis=1) > 0)]
    last = pd.to_datetime(pg["game_date"]).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    return m.drop_duplicates("espn_id", keep="last").set_index("espn_id")["gsis_id"].to_dict(), pg.assign(t=last).groupby("player_id")["t"].max().to_dict()


def combine(league: str, espn: dict | None, official: dict | None, nflverse: pd.DataFrame | None, sched: pd.DataFrame,
            id_map: dict, last_played: dict, previous: pd.DataFrame | None, now: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    """The rules above, on already-fetched data (pure: tests call this directly)."""
    roster = espn["roster"] if espn else pd.DataFrame(columns=["team", "source_player_id", "player", "position", "experience_years"])
    roster = roster.assign(key=roster["player"].map(S.norm_name))
    by_team_name = {(r.team, r.key): r for r in roster.itertuples()}
    by_name: dict = {}
    for r in roster.itertuples():
        by_name.setdefault(r.key, []).append(r)

    parts = []
    if espn is not None and len(espn["rows"]):
        parts.append(espn["rows"])
    if official is not None and len(official["rows"]):
        o = official["rows"].copy()
        sid, team, pos = [], [], []
        for r in o.itertuples():
            k = S.norm_name(r.player)
            hit = by_team_name.get((r.team, k)) or (by_name[k][0] if len(by_name.get(k, [])) == 1 else None)
            sid.append(hit.source_player_id if hit else None)
            team.append(hit.team if hit else r.team)
            pos.append(hit.position if hit else None)
        o["source_player_id"], o["team"], o["position"] = sid, team, pos
        o["player"] = [(hit.player if (hit := by_team_name.get((t, S.norm_name(p)))) else p) for t, p in zip(o["team"], o["player"])]
        parts.append(o[S.COLUMNS])
    if nflverse is not None and len(nflverse):
        parts.append(nflverse[S.COLUMNS])
    rows = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=S.COLUMNS)
    if rows.empty:
        return rows.assign(current=[], stale=[], stale_reason=[], conflict=[], confirmed=[], late_scratch=[]), {"filings": []}

    if league == "nba":
        rows["player_id"] = rows["player_id"].where(rows["player_id"].notna(), rows["source_player_id"])
    else:
        rows["player_id"] = rows["player_id"].where(rows["player_id"].notna(), rows["source_player_id"].map(id_map))
    rows["player_id"] = rows["player_id"].astype(object).where(rows["player_id"].notna(), "espn:" + rows["source_player_id"].astype(str))
    rows = rows.merge(sched, on="team", how="left")
    rt = pd.to_datetime(rows["report_time"], utc=True)
    last = pd.to_datetime(rows["player_id"].astype(str).map(last_played), utc=True)

    stale = pd.Series("", index=rows.index)
    desig = rows["status"].isin(["questionable", "doubtful", "probable"])
    stale[desig & rows["prev_start"].notna() & (rt < rows["prev_start"]) & (rows["kind"] != "official")] = "designation was for an earlier game"
    stale[(rows["status"] == "out") & last.notna() & (rt < last) & ~rows["long_term"].astype(bool)] = "has played since this report"
    off = rows["kind"] == "official"
    stale[off & rows["game_date"].notna() & rows["next_game_date"].notna() & (rows["game_date"] < rows["next_game_date"])] = "report was for a past game"
    rows["stale"] = stale != ""
    rows["stale_reason"] = stale.where(rows["stale"], None)

    filings = official["filings"] if official else []
    submitted = {(f["game_date"], f["team"]) for f in filings if f["submitted"]}
    pending = {(f["game_date"], f["team"]) for f in filings if not f["submitted"]}

    pick, conflicts = [], {}
    for pid, x in rows[~rows["stale"]].groupby("player_id"):
        if league == "nba":
            offc = x[(x["kind"] == "official") & (x["game_date"] == x["next_game_date"])]
            best = offc.sort_values("report_time").iloc[-1] if len(offc) else x.sort_values("report_time").iloc[-1]
        else:
            best = x.sort_values("report_time").iloc[-1]
        cur = set(x["status"]) - {"unknown"}
        if len(cur) > 1:
            conflicts[pid] = "; ".join(f"{r.source}: {r.raw_status} ({pd.Timestamp(r.report_time):%b %d %H:%M} UTC)" for r in x.itertuples() if pd.notna(r.report_time))
        pick.append(best.name)
    cur = rows.loc[pick].copy()
    # NBA: a submitted official report that doesn't list a player → available for that game.
    if league == "nba" and submitted:
        listed = {(r.next_game_date, r.team, str(r.player_id)) for r in rows[off & ~rows["stale"]].itertuples()}
        for i, r in cur.iterrows():
            if r["kind"] != "official" and (r["next_game_date"], r["team"]) in submitted and (r["next_game_date"], r["team"], str(r["player_id"])) not in listed \
                    and r["status"] in ("out", "doubtful", "questionable", "probable") and not r["long_term"]:
                conflicts[r["player_id"]] = f"ESPN: {r['raw_status']}; official report for {r['next_game_date']}: not listed (available)"
                cur.loc[i, ["status", "raw_status", "source", "kind"]] = ["available", "Not on official report", "nba_official", "official"]
    cur["conflict"] = cur["player_id"].map(conflicts)
    cur["confirmed"] = cur["kind"] == "official"
    cur["team_report"] = [("submitted" if (r.next_game_date, r.team) in submitted else "not yet submitted" if (r.next_game_date, r.team) in pending else "none")
                          for r in cur.itertuples()]
    cur["late_scratch"] = False
    if previous is not None and len(previous):
        prev = previous.set_index("player_id")["status"].to_dict()
        soon = pd.to_datetime(cur["next_start"], utc=True) - now <= pd.Timedelta(hours=LATE_SCRATCH_HOURS)
        newly = cur["status"].isin(["out", "doubtful"]) & cur["player_id"].map(lambda p: prev.get(p) not in ("out", "doubtful"))
        cur["late_scratch"] = (soon & newly).fillna(False)
    stale_rows = rows[rows["stale"]]
    out = pd.concat([cur.assign(current=True), stale_rows[~stale_rows["player_id"].isin(cur["player_id"])].assign(current=False)], ignore_index=True)
    meta = {"filings": filings, "conflicts": len(conflicts)}
    return out, meta


def live_depth_path(season: int):
    from modelroom.common.paths import raw_dir

    return raw_dir("nfl") / f"depth_charts_live_{season}.parquet"


def write_live_depth(dep: pd.DataFrame, id_map: dict, now: pd.Timestamp) -> None:
    """ESPN's current depth chart in nflverse's depth_charts format (same source, fresher), so the starter
    rule and the prop depth ranks read it exactly like the nflverse snapshots."""
    g = pd.read_parquet(processed_dir("nfl") / "games.parquet")
    season = int(g.loc[g["status"] == "scheduled", "season"].min()) if (g["status"] == "scheduled").any() else int(g["season"].max())
    d = dep[dep["chart"].fillna("").str.contains("WR|TE|RB", regex=True) | (dep["pos"] == "QB")]
    out = pd.DataFrame({"dt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "team": d["team"], "player_name": d["player"], "espn_id": d["source_player_id"],
                        "gsis_id": d["source_player_id"].map(id_map), "pos_abb": d["pos"], "pos_slot": d["slot"], "pos_rank": d["rank"]})
    out = out.drop_duplicates(["team", "gsis_id", "pos_abb", "pos_slot"]).dropna(subset=["gsis_id"])
    f = live_depth_path(season)
    prev = pd.read_parquet(f) if f.exists() else None
    pd.concat([prev, out], ignore_index=True).to_parquet(f, index=False)


def _nflverse_rows(now: pd.Timestamp) -> pd.DataFrame:
    from modelroom.nfl.props import inputs as PI

    inj = PI.injuries()
    if inj.empty:
        return pd.DataFrame(columns=S.COLUMNS)
    season = int(inj["season"].max())
    inj = inj[inj["season"] == season]
    inj = inj[inj["week"] == inj["week"].max()]
    t = pd.to_datetime(inj.get("date_modified"), utc=True, errors="coerce") if "date_modified" in inj else pd.NaT
    return pd.DataFrame({"league": "nfl", "source": "nflverse", "kind": "official", "team": inj["team"], "player_id": inj["gsis_id"],
                         "player": inj["full_name"], "position": None, "source_player_id": None, "status": inj["report_status"].map(S.canonical),
                         "raw_status": inj["report_status"], "detail": None, "comment": None, "report_time": t, "fetched_at": now,
                         "game_date": None, "restriction": False, "restriction_minutes": None, "returning": False, "long_term": False})[S.COLUMNS]


def _jsonable(df: pd.DataFrame) -> list[dict]:
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].map(lambda v: None if pd.isna(v) else pd.Timestamp(v).isoformat())
    return json.loads(d.replace({np.nan: None}).to_json(orient="records", date_format="iso"))


def run(league: str, now: datetime | None = None) -> dict:
    """Fetch every source for the league, combine, write the feed, publish, and snapshot (append-only)."""
    from . import espn as E
    from . import nba_official as N

    now = pd.Timestamp(now or datetime.now(UTC))
    log: dict = {"league": league, "fetched_at": now.isoformat(), "sources": {}}
    espn = official = None
    try:
        espn = E.fetch(league, now=now)
        log["sources"]["espn"] = {"ok": True, "rows": len(espn["rows"]), "errors": espn["errors"][:5]}
    except Exception as e:  # noqa: BLE001
        log["sources"]["espn"] = {"ok": False, "error": str(e)[:300]}
    if league == "nba":
        try:
            official = N.fetch(now)
            log["sources"]["nba_official"] = {"ok": True, "rows": len(official["rows"]), "url": official["url"],
                                              "report_time": official["report_time"].isoformat()}
        except Exception as e:  # noqa: BLE001
            log["sources"]["nba_official"] = {"ok": False, "error": str(e)[:300]}
    nflv = _nflverse_rows(now) if league == "nfl" else None
    if league == "nfl":
        log["sources"]["nflverse"] = {"ok": True, "rows": len(nflv)}
    pub = data_root() / "published" / f"injuries_live_{league}.json"
    previous = None
    if pub.exists():
        try:
            previous = pd.DataFrame(json.loads(pub.read_text()).get("players") or [])
        except ValueError:
            previous = None
    if espn is None and official is None:
        log["status"] = "failed"
        _append(league, log)
        raise RuntimeError(f"injuries {league}: every source failed: {log['sources']}")
    id_map, last_played = _id_maps(league)
    feed, meta = combine(league, espn, official, nflv, schedule(league, now), id_map, last_played,
                         previous[previous.get("current", True) == True] if previous is not None and len(previous) else None, now)
    out = processed_dir(league)
    feed.to_parquet(out / "injury_feed.parquet", index=False)
    if espn is not None:
        espn["roster"].assign(player_id=lambda r: r["source_player_id"].map(id_map) if league == "nfl" else r["source_player_id"]).to_parquet(out / "espn_roster.parquet", index=False)
        if league == "nfl" and len(espn["depth"]):
            write_live_depth(espn["depth"], id_map, now)
        if league == "nba":
            espn["starters"].to_parquet(out / "starters_live.parquet", index=False)
    cur = feed[feed["current"]]
    payload = {"league": league, "generated_at": now.isoformat(), "sources": log["sources"], "filings": meta["filings"],
               "counts": cur["status"].value_counts().to_dict(), "conflicts": int(meta["conflicts"]),
               "players": _jsonable(feed.drop(columns=[c for c in ("prev_start",) if c in feed]))}
    pub.parent.mkdir(parents=True, exist_ok=True)
    pub.write_text(json.dumps(payload, default=str))
    h = hashlib.sha256(json.dumps(sorted((str(r.player_id), r.status, str(r.report_time)) for r in cur.itertuples())).encode()).hexdigest()[:16]
    log.update(status="success", rows=len(cur), hash=h, conflicts=int(meta["conflicts"]), late_scratches=int(cur["late_scratch"].sum()))
    _append(league, log, cur if _last_hash(league) != h else None)
    return {k: v for k, v in log.items() if k != "sources"} | {"sources": {k: v.get("ok") for k, v in log["sources"].items()}}


def _snap_path(league: str):
    return ledger_path(f"injury_snapshots_{league}")


def _last_hash(league: str) -> str | None:
    f = _snap_path(league)
    if not f.exists():
        return None
    for line in reversed(f.read_text().splitlines()):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("hash"):
            return r["hash"]
    return None


def _append(league: str, log: dict, cur: pd.DataFrame | None = None) -> None:
    """Append-only: every fetch logs its sources; the full current table is stored only when it changed."""
    f = _snap_path(league)
    f.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(log)
    if cur is not None:
        rec["players"] = _jsonable(cur[["team", "player_id", "player", "position", "status", "raw_status", "source", "kind", "report_time",
                                        "restriction", "restriction_minutes", "returning", "long_term", "conflict", "late_scratch"]])
    with f.open("a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
