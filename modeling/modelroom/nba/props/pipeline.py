"""NBA props production run: projections → (optional) stored market prices → ledger → published board.

    python -m modelroom nba props [--days 3]
"""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime

import numpy as np
import pandas as pd

from modelroom.common import board as B
from modelroom.common import ledger
from modelroom.common.hashing import hash_frame, hash_obj
from modelroom.common.paths import MODELING_ROOT, data_root, ensure, ledger_path, output_dir
from modelroom.common.publish import write_board
from modelroom.common import grid as G
from modelroom.common import recent
from modelroom.markets import compare as C
from modelroom.markets import evaluation, prices
from modelroom.markets.teams import NBA_TEAMS
from modelroom.sources import state

from . import inputs as I
from . import model as M
from .backtest import eligible
import os

from modelroom.injuries import use as U

from .config import CANDIDATE_FILE, CANDIDATE_VERSION, INJURY_FILE, INJURY_VERSION, MARKETS, MODEL_ID, MODEL_VERSION, PARAMS_FILE, SHADOW_FILES, PropParams

# Which prop model the board and ledger use. 0.1.0 = params.json (the default everywhere); 0.2.0 =
# params_0.2.0.json, switched on for the hosted test site only by its workflow
# (MODELROOM_NBA_PROPS_VERSION=0.2.0). Rollback = unset the variable (or set 0.1.0): both parameter files
# stay in the repo, and every ledger record names the version that made it.
VERSIONS = {MODEL_VERSION: PARAMS_FILE, CANDIDATE_VERSION: CANDIDATE_FILE, INJURY_VERSION: INJURY_FILE}
SHADOW_ONLY = dict(SHADOW_FILES)   # 0.2.3a / 0.2.3: may run as shadows; refused as the published version


def _params_file(v: str):
    return VERSIONS.get(v) or SHADOW_ONLY[v]


def shadow_versions(active: str) -> list[str]:
    """Versions also run and recorded in the ledger (never published), for side-by-side monitoring."""
    vs = [v.strip() for v in os.environ.get("MODELROOM_NBA_PROPS_SHADOW", "").split(",") if v.strip()]
    for v in vs:
        if v not in VERSIONS and v not in SHADOW_ONLY:
            raise ValueError(f"MODELROOM_NBA_PROPS_SHADOW: unknown version {v!r}")
    return [v for v in dict.fromkeys(vs) if v != active]


def shadow_ledger_path(v: str, now) -> "Path":
    """Shadow records live in their own append-only, hash-chained files, one per version per ISO week (the active
    version's ledger stays nba_props.jsonl), so no single ledger file outgrows GitHub's 100 MB limit."""
    y, w, _ = pd.Timestamp(now).isocalendar()
    return ledger_path(f"nba_props_shadow_{v}_{y}-W{w:02d}")


def active_version() -> str:
    v = os.environ.get("MODELROOM_NBA_PROPS_VERSION", "").strip() or MODEL_VERSION
    if v not in VERSIONS:
        raise ValueError(f"MODELROOM_NBA_PROPS_VERSION={v!r}: known versions are {sorted(VERSIONS)}")
    return v

TEAM_NAMES = {}
for _name, _code in NBA_TEAMS.items():
    TEAM_NAMES.setdefault(_code, _name)
STEP = {"pts": 5, "pra": 5}


def published_path():
    return data_root() / "published" / "nba_props.json"


def backtest_summary(version: str = MODEL_VERSION) -> dict | None:
    local = output_dir("nba") / "props_backtest.json"
    f = local if local.exists() and json.loads(local.read_text()).get("model_version") == version else None
    if f is None:
        c = MODELING_ROOT.parent / "docs" / "models" / "results" / f"nba-props-backtest-{version}.json"
        f = c if c.exists() else None
    if f is None:
        return None
    r = json.loads(f.read_text())
    t = r["test"]
    return {
        "model_version": r["model_version"], "test_seasons": r["test_seasons"], "thresholds": t["thresholds"],
        "overall": t.get("overall"), "overall_vs_baseline": t.get("overall_vs_baseline"),
        "by_market": {k: {"log_loss": v["model"]["log_loss"], "brier": v["model"]["brier"], "n": v["model"]["n"], "ece": v.get("ece"),
                          "baseline_log_loss": (v.get("baseline_same_rows") or {}).get("baseline", {}).get("log_loss"),
                          "model_log_loss_same_rows": (v.get("baseline_same_rows") or {}).get("model", {}).get("log_loss"),
                          "mean_mae": v["mean_projection"]["model_mae"], "recent_avg_mae": v["mean_projection"]["recent_avg_mae"]}
                      for k, v in t["markets"].items()},
        "calibration": t.get("calibration"), "by_confidence": t.get("by_confidence"), "by_support": t.get("by_support"),
        "notes": r.get("notes", []),
    }


def display_thresholds(x: M.PlayerProjection, stat: str) -> list[float]:
    sims = x.sims[stat]
    step = STEP.get(stat, 1)
    out = set()
    for q in (0.25, 0.5, 0.75):
        out.add(float(max(step, round(float(np.quantile(sims, q)) / step) * step)))
    return sorted(out)


def player_entry(x: M.PlayerProjection, p: PropParams, quotes: list, now: datetime, reliability: dict) -> dict:
    support, note = x.support()
    markets = {}
    for mkey, m in MARKETS.items():
        stat = m["stat"]
        sims = x.sims[stat]
        rows = {(">=", k, None): [] for k in display_thresholds(x, stat)}
        for q in quotes:
            if q.market == mkey:
                rows.setdefault((q.op, float(q.threshold), q.variant), []).append(q)
        th = []
        for (op, k, variant), qs in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2] or "")):
            raw = x.prob(stat, k, op)
            prob = p.calibrate(mkey, raw)
            views = [C.view(q, prob, now) for q in qs]
            best = C.best(views) if views else None
            th.append({"op": op, "threshold": k, "variant": variant, "model_prob": round(prob, 4), "model_prob_raw": round(raw, 4),
                       "quotes": [asdict(v) for v in views], "best": best, "edge_grade": C.grade(best, support, reliability.get(mkey))})
        markets[mkey] = {"label": m["label"], "mean": round(float(np.mean(sims)), 2), "median": round(float(np.median(sims)), 1),
                         "sd": round(float(np.std(sims)), 2),
                         "range_80": [round(float(np.quantile(sims, 0.1)), 1), round(float(np.quantile(sims, 0.9)), 1)],
                         "support": support, "support_note": note, "thresholds": th,
                         "grid": G.build(sims, stat, lambda r, _m=mkey: p.calibrate(_m, r))}
    return {"player_id": x.player_id, "name": x.name, "team": x.team, "opp": x.opp, "position": x.group, "game_id": x.game_id,
            "injury_status": (x.inputs.get("availability") or {}).get("status"), "markets": markets,
            "inputs": {k: v for k, v in x.inputs.items() if k != "sample"}}


def run(*, days: int = 3, now: datetime | None = None, write_ledger: bool = True, sims: int | None = None) -> dict:
    now = now or B.now_utc()
    version = active_version()
    inp = I.load()
    gp = inp.games
    upcoming = B.upcoming_window(gp[gp["status"] == "scheduled"], now, days)
    season = int(upcoming["season"].max()) if len(upcoming) else int(gp["season"].max())
    today = pd.Timestamp(pd.Timestamp(now).tz_convert("America/New_York").date())
    avail = U.nba_availability(upcoming, inp.player_games)
    feed = U.live_meta("nba")

    def project(v: str):
        pv = PropParams.load(_params_file(v))
        pv = replace(pv, settings=replace(pv.settings, sims=sims or 10000))
        ctx = M.build(inp.player_games, inp.pace, today, season, pv.settings)
        out, sd = [], {}
        for day, g in upcoming.groupby("game_date"):
            sd[str(day)] = int(str(day).replace("-", ""))
            out += M.project_games(ctx, g, pv, seed=sd[str(day)], avail=avail if pv.settings.injury_feed else None)
        return pv, [x for x in out if eligible(x)], sd

    p, projs, seeds = project(version)
    # Shadows never affect the published board: a failing shadow is skipped and logged, the active version publishes.
    shadows, shadow_errors = {}, {}
    for v in shadow_versions(version):
        try:
            shadows[v] = project(v)
        except Exception as e:  # noqa: BLE001
            shadow_errors[v] = f"{type(e).__name__}: {e}"[:300]
            print(f"::warning::NBA props shadow {v} failed: {shadow_errors[v]}", flush=True)

    games_df = upcoming.rename(columns={"home_abbr": "home_team", "away_abbr": "away_team"})[["game_id", "game_date", "home_team", "away_team"]]
    plist = pd.DataFrame([{"game_id": x.game_id, "player_id": x.player_id, "name": x.name, "team": x.team, "sportradar_id": None} for x in projs])
    idx_pub, idx_all, info, unmatched = prices.load("nba", games_df, plist)

    bt = backtest_summary(version)
    reliability = (bt or {}).get("by_market", {})
    by_game, local_games = {}, {}
    local_only = any(i["enabled"] and not i["publishable"] for i in info)
    for x in projs:
        by_game.setdefault(x.game_id, []).append(player_entry(x, p, idx_pub.get((x.game_id, x.player_id), []), now, reliability))
        if local_only and idx_all.get((x.game_id, x.player_id)):
            local_games.setdefault(x.game_id, []).append(player_entry(x, p, idx_all[(x.game_id, x.player_id)], now, reliability))
    def price(x, q):
        m = MARKETS.get(q.market)
        if m is None:
            return None
        return p.calibrate(q.market, x.prob(m["stat"], float(q.threshold), q.op)), m["stat"]

    starts_iso = {gid: B.iso(t) for gid, t in upcoming.set_index("game_id")["start_time"].items()}
    evaluated = evaluation.log_run("nba", projs, idx_all, price, lambda x, mk: x.support()[0], reliability, version,
                                   now.isoformat(timespec="seconds"), starts_iso, now)
    games_json = []
    for _, g in upcoming.iterrows():
        players = sorted(by_game.get(g["game_id"], []), key=lambda e: (e["team"], -e["markets"]["points"]["mean"]))
        games_json.append({"game_id": g["game_id"], "start_time": B.iso(g["start_time"]), "game_date": str(g["game_date"]), "week": None,
                           "home": {"abbr": g["home_abbr"], "name": TEAM_NAMES.get(g["home_abbr"], g["home_abbr"])},
                           "away": {"abbr": g["away_abbr"], "name": TEAM_NAMES.get(g["away_abbr"], g["away_abbr"])},
                           "players": players})

    pg = inp.player_games
    base_hash = hash_frame(pg[pg["season"] >= season - 2], ["game_id", "player_id", "minutes", "pts"])
    avail_hash = U.availability_hash("nba")
    generated_at = now.isoformat(timespec="seconds")
    appended = None
    shadow_appended = {}

    def game_avail_hash(gid: str) -> str:
        """The injury picture of ONE game (both teams: statuses, restrictions, filed or not, confirmed starters)."""
        parts = []
        for (g, team), a in (avail or {}).items():
            if g != gid:
                continue
            parts.append(f"{team}|submitted={bool(a.get('submitted'))}|starters={sorted(a.get('starters') or [])}")
            parts += sorted(f"{team}|{pid}|{r.get('status')}|{r.get('restriction_minutes')}" for pid, r in (a.get("players") or {}).items())
        return hash_obj(sorted(parts))

    def records(v: str, pv: PropParams, px: list, sd: dict, per_game: bool = False) -> list[dict]:
        # Versions that read the injury feed fold its state into the inputs hash: a changed injury picture is a
        # new snapshot in the append-only ledger; the earlier ones stay as recorded. Shadows (per_game) hash only
        # their own game's injury picture, so a change elsewhere in the league doesn't re-record every player.
        ih = hash_obj({"base": base_hash, "injuries": avail_hash}) if pv.settings.injury_feed else base_hash
        ph = hash_obj(pv.to_json())
        starts = upcoming.set_index("game_id")["start_time"]
        dates = upcoming.set_index("game_id")["game_date"].astype(str)
        recs = []
        for x in px:
            if per_game and pv.settings.injury_feed:
                ih = hash_obj({"base": base_hash, "game_injuries": game_avail_hash(str(x.game_id))})
            probs = {mkey: {**{str(k): round(pv.calibrate(mkey, x.prob(m["stat"], k)), 4) for k in m["ladder"]},
                            "mean": round(x.mean(m["stat"]), 2), "sd": round(x.sd(m["stat"]), 2)} for mkey, m in MARKETS.items()}
            a = x.inputs.get("availability") or {}
            recs.append({"sport": "nba", "kind": "player_props", "game_id": f"{x.game_id}|{x.player_id}", "nba_game_id": x.game_id,
                         "player_id": x.player_id, "player": x.name, "team": x.team, "game_start": B.iso(starts[x.game_id]),
                         "probabilities": probs, "support": x.support()[0], "projected_minutes": x.inputs["projected_minutes"],
                         "starter_rate": x.inputs.get("starter_rate"), "usage_freed_by_absences": x.inputs.get("usage_freed_by_absences"),
                         **({"injury_status": a.get("status"), "injury_source": a.get("source"), "injury_report_time": a.get("report_time"),
                             "injury_raw_status": a.get("raw_status"), "injury_conflict": a.get("conflict"),
                             "injury_confirmed": a.get("confirmed"), "injury_late_scratch": a.get("late_scratch"),
                             "injury_notes": a.get("notes") or None, "teammates_out": x.inputs.get("teammates_out_detail"),
                             "injury_feed_at": (feed or {}).get("generated_at")} if pv.settings.injury_feed else {}),
                         "model_id": MODEL_ID, "model_version": v, "params_hash": ph, "inputs_hash": ih,
                         "generated_at": generated_at, "sims": pv.settings.sims, "seed": sd.get(dates[x.game_id])})
        return recs

    inputs_hash = hash_obj({"base": base_hash, "injuries": avail_hash}) if p.settings.injury_feed else base_hash
    params_hash = hash_obj(p.to_json())
    if write_ledger and projs:
        appended = ledger.append(ledger_path("nba_props"), records(version, p, projs, seeds))
        for v, (pv, px, sd) in shadows.items():
            if px:
                try:
                    shadow_appended[v] = ledger.append(shadow_ledger_path(v, now), records(v, pv, px, sd, per_game=True)).__dict__
                except Exception as e:  # noqa: BLE001
                    shadow_errors[v] = f"ledger: {type(e).__name__}: {e}"[:300]
                    print(f"::warning::NBA props shadow {v} not recorded: {shadow_errors[v]}", flush=True)

    recent.attach(games_json, inp.player_games, {k: m["stat"] for k, m in MARKETS.items()}, today, inp.player_games["played"].astype(bool))
    try:
        prev_board = json.loads(published_path().read_text())
    except (OSError, ValueError):
        prev_board = None
    explained = U.explain(prev_board, games_json, ("points", "rebounds", "assists", "pra", "threes"))
    flags = U.game_flags("nba", list(upcoming["home_abbr"]) + list(upcoming["away_abbr"])) if p.settings.injury_feed else {}
    for gj in games_json:
        gj["injuries"] = {side: flags.get(gj[side]["abbr"], []) for side in ("home", "away")} if flags else None
    board = {
        "league": "nba", "kind": "player_props", "generated_at": generated_at, "season": season, "week": None,
        "model": {"id": MODEL_ID, "version": version, "default_version": MODEL_VERSION, "params_hash": params_hash, "inputs_hash": inputs_hash,
                  "status": p.provenance.get("status", "provisional"), "fitted_at": p.provenance.get("fitted_at"),
                  "sims": p.settings.sims, "seeds": seeds,
                  "independence": "Uses only box scores, minutes, pace and the game engine. Exchange prices are never an input; they are compared afterwards.",
                  "injuries": (f"Injury feed: the NBA's official injury report and ESPN's injury reports (test site; refreshed {feed['generated_at']}). "
                               "Out / Doubtful players are removed and their usage freed (Doubtful at 75%); returning players' minutes follow measured "
                               "first-games-back patterns; a player with no current report falls back to the missed-games rule.")
                              if p.settings.injury_feed and feed else
                              "No NBA injury feed is used by this version. A rotation player who missed his team's last two games is treated as out; anyone else is assumed available.",
                  "injury_feed": feed if p.settings.injury_feed else None, "shadow_versions": sorted(shadows)},
        "data": {"last_ingest": state.read().get("hoopr_schedule", {}).get("last_success"),
                 "results_through": str(pg.loc[pg["played"], "game_date"].max()),
                 "markets": [i for i in info if i["publishable"] or i["provider"] == "manual"],
                 "markets_not_published": [{"provider": i["provider"], "reason": i["reason"]} for i in info if not i["publishable"] and i["provider"] != "manual"],
                 "unmatched_quotes": unmatched,
                 "comparison_rules": {"max_age_min": C.MAX_AGE_MIN, "max_spread": C.MAX_SPREAD, "min_size": C.MIN_SIZE, "min_ev": C.MIN_EV}},
        "performance": {"backtest": bt},
        "games": games_json,
    }
    path = write_board(published_path(), board)
    if local_games:
        write_board(ensure(output_dir("nba")) / "props_compare_local.json",
                    {**board, "games": [{"game_id": k, "players": v} for k, v in local_games.items()], "note": "Local only."})
    state.record("nba_props_run", model_version=version, players=len(projs))
    return {"board": str(path), "games": len(games_json), "players": len(projs),
            "quotes_matched": sum(len(v) for v in idx_all.values()), "evaluated_contracts": evaluated, "ledger": appended.__dict__ if appended else None,
            "shadow_ledger": shadow_appended, "shadow_errors": shadow_errors or None, "explained_changes": explained}
