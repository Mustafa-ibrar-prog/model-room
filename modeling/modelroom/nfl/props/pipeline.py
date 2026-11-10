"""NFL props production run: projections → (optional) market comparison → ledger → published board.

    python -m modelroom nfl props [--days 10]

Market prices come only from stored snapshots (python -m modelroom markets fetch nfl) and the manual
CSV; this module never calls an exchange. Prices from a provider that isn't cleared for publication
(see modelroom.markets.config) are kept out of the published board and written to a local-only file.
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
from modelroom.markets import compare as C
from modelroom.markets import config as MC
from modelroom.common import grid as G
from modelroom.common import recent
from modelroom.markets import evaluation, manual, matching, snapshots
from modelroom.markets.schema import PropQuote
from modelroom.sources import odds, state

from .. import ingest
from . import features as F
from . import depth as DEPTH
from . import inputs as I
from . import model as M
from .backtest import eligible
import os

from modelroom.injuries import use as U

from .config import (CANDIDATE_FILE, CANDIDATE_VERSION, CONC_FILE, CONC_VERSION, INJURY_FILE, INJURY_VERSION, MARKETS, MODEL_ID, MODEL_VERSION, OPP_FILE, OPP_VERSION,
                     PARAMS_FILE, PropParams)

# Which NFL prop model the board and ledger use: 0.1.0 = params.json (the default everywhere); a candidate
# version only when MODELROOM_NFL_PROPS_VERSION names it (the hosted test site's workflow). Rollback = unset
# it. Every ledger record names the version that made it.
VERSIONS = {MODEL_VERSION: PARAMS_FILE, CANDIDATE_VERSION: CANDIDATE_FILE, OPP_VERSION: OPP_FILE, INJURY_VERSION: INJURY_FILE,
            CONC_VERSION: CONC_FILE}
# Versions that may only ever run as shadows (recorded in the ledger, never published).
SHADOW_ONLY = {CONC_VERSION}


def shadow_versions(active: str) -> list[str]:
    """Versions also run and recorded in the ledger (never published), for side-by-side monitoring."""
    vs = [v.strip() for v in os.environ.get("MODELROOM_NFL_PROPS_SHADOW", "").split(",") if v.strip()]
    for v in vs:
        if v not in VERSIONS:
            raise ValueError(f"MODELROOM_NFL_PROPS_SHADOW: unknown version {v!r}")
    return [v for v in dict.fromkeys(vs) if v != active]


def active_version() -> str:
    v = os.environ.get("MODELROOM_NFL_PROPS_VERSION", "").strip() or MODEL_VERSION
    if v not in VERSIONS:
        raise ValueError(f"MODELROOM_NFL_PROPS_VERSION={v!r}: known versions are {sorted(VERSIONS)}")
    if v in SHADOW_ONLY:
        raise ValueError(f"MODELROOM_NFL_PROPS_VERSION={v!r} is a shadow-only experiment and can't be published; "
                         "list it in MODELROOM_NFL_PROPS_SHADOW instead")
    return v

TEAM_NAMES = {v: k for k, v in odds.NFL_TEAMS.items()}
VARIANT_STAT = {("fantasy_points", "sleeper_ppr"): "fantasy_sleeper", ("fantasy_points", "espn_ppr"): "fantasy_ppr"}
STEP = {"pass_yds": 25, "rush_yds": 5, "rec_yds": 5, "rush_rec_yds": 5, "long_rec": 5, "fantasy_ppr": 1, "fantasy_sleeper": 1}
FIXED = {"td_any": [1], "ints": [1], "pass_td": [1, 2]}


def _none(v):
    """Snapshot rows come back through pandas: missing values are NaN; restore None."""
    return None if isinstance(v, float) and v != v else v


def published_props_path():
    return data_root() / "published" / "nfl_props.json"


def local_compare_path():
    return ensure(output_dir("nfl")) / "props_compare_local.json"


def backtest_summary(version: str = MODEL_VERSION) -> dict | None:
    local = output_dir("nfl") / "props_backtest.json"
    f = None
    if local.exists() and json.loads(local.read_text()).get("model_version") == version:
        f = local
    else:
        c = MODELING_ROOT.parent / "docs" / "models" / "results" / f"nfl-props-backtest-{version}.json"
        f = c if c.exists() else None
    if f is None:
        return None
    r = json.loads(f.read_text())
    t = r["test"]
    return {
        "model_version": r["model_version"], "test_seasons": r["test_seasons"], "thresholds": t["thresholds"],
        "overall": t.get("overall"), "overall_vs_baseline": t.get("overall_vs_baseline"),
        "by_market": {k: {"log_loss": v["model"]["log_loss"], "brier": v["model"]["brier"], "n": v["model"]["n"],
                          "baseline_log_loss": (v.get("baseline_same_rows") or {}).get("baseline", {}).get("log_loss"),
                          "model_log_loss_same_rows": (v.get("baseline_same_rows") or {}).get("model", {}).get("log_loss"),
                          "ece": v.get("ece"),
                         "mean_mae": v["mean_projection"]["model_mae"], "recent_avg_mae": v["mean_projection"]["recent_avg_mae"]}
                      for k, v in t["markets"].items()},
        "calibration": t.get("calibration"), "by_confidence": t.get("by_confidence"), "by_support": t.get("by_support"),
        "notes": r.get("notes", []),
    }


def display_thresholds(x: M.PlayerProjection, stat: str) -> list[float]:
    if stat in FIXED:
        return FIXED[stat]
    sims = x.sims[stat]
    step = STEP.get(stat, 1)
    out = set()
    for q in (0.25, 0.5, 0.75):
        v = float(np.quantile(sims, q))
        k = max(step, round(v / step) * step)
        out.add(float(k))
    return sorted(out)


def _quote_index(quotes: list[PropQuote]) -> dict:
    idx: dict = {}
    for q in quotes:
        if q.player_id and q.game_id:
            idx.setdefault((q.game_id, q.player_id), []).append(q)
    return idx


def player_entry(x: M.PlayerProjection, p: PropParams, quotes: list[PropQuote], now: datetime, reliability: dict) -> dict:
    markets = {}
    for mkey, m in MARKETS.items():
        if x.group not in m["positions"]:
            continue
        stat = m["stat"]
        sims = x.sims[stat]
        support, support_note = x.support(mkey)
        rows = {}
        for k in display_thresholds(x, stat):
            rows[(">=", float(k), None)] = []
        for q in quotes:
            if q.market == mkey:
                rows.setdefault((q.op, float(q.threshold), q.variant), []).append(q)
        th = []
        for (op, k, variant), qs in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2] or "")):
            s = VARIANT_STAT.get((mkey, variant), stat)
            raw = x.prob(s, k, op)
            prob = p.calibrate(mkey, raw)
            views = [C.view(q, prob, now) for q in qs]
            best = C.best(views) if views else None
            th.append({"op": op, "threshold": k, "variant": variant, "model_prob": round(prob, 4), "model_prob_raw": round(raw, 4),
                       "quotes": [asdict(v) for v in views], "best": best,
                       "edge_grade": C.grade(best, support, reliability.get(mkey))})
        markets[mkey] = {"label": m["label"], "mean": round(float(np.mean(sims)), 2), "median": round(float(np.median(sims)), 1),
                         "sd": round(float(np.std(sims)), 2),
                         "range_80": [round(float(np.quantile(sims, 0.1)), 1), round(float(np.quantile(sims, 0.9)), 1)],
                         "support": support, "support_note": support_note, "thresholds": th,
                         "grid": G.build(sims, stat, lambda r, _m=mkey: p.calibrate(_m, r))}
    return {"player_id": x.player_id, "name": x.name, "team": x.team, "opp": x.opp, "position": x.group,
            "game_id": x.game_id, "injury_status": x.inputs.get("injury_status"), "markets": markets, "inputs": x.inputs}


def _attach_availability(projs: list, feed: pd.DataFrame) -> None:
    """Each projection's own injury row and his team's ruled-out skill players / QBs (source, time, confirmed)."""
    me = {str(r.player_id): r for r in feed.itertuples()}
    outs: dict = {}
    for r in feed[feed["status"].isin(["out", "doubtful"]) & feed["position"].isin(["QB", "RB", "WR", "TE", "FB"])].itertuples():
        outs.setdefault(r.team, []).append({"name": r.player, "position": r.position, "status": r.status, "source": r.source,
                                            "long_term": bool(r.long_term)})
    for x in projs:
        r = me.get(str(x.player_id))
        x.inputs["availability"] = None if r is None else {
            "status": r.status, "raw_status": r.raw_status, "source": r.source, "confirmed": r.kind == "official",
            "report_time": None if pd.isna(r.report_time) else pd.Timestamp(r.report_time).isoformat(),
            "comment": r.comment if isinstance(r.comment, str) else None, "conflict": getattr(r, "conflict", None) or None,
            "notes": [x.inputs["qb_note"]] if x.inputs.get("qb_note") else []}
        if r is None and x.inputs.get("qb_note"):
            x.inputs["availability"] = {"status": None, "notes": [x.inputs["qb_note"]]}
        x.inputs["teammates_out_detail"] = [t for t in outs.get(x.team, []) if t["name"] != x.name]


def run(*, days: int = 10, now: datetime | None = None, write_ledger: bool = True, sims: int | None = None) -> dict:
    now = now or B.now_utc()
    version = active_version()
    games_all = ingest.load_games()
    sched = games_all[games_all["status"] == "scheduled"]
    season = int(sched["season"].min()) if len(sched) else int(games_all["season"].max())
    inp = I.load({season})
    gp = inp.games
    upcoming = B.upcoming_window(gp[gp["status"] == "scheduled"], now, days)
    week = int(upcoming["week"].mode().iloc[0]) if len(upcoming) else None
    today = pd.Timestamp(pd.Timestamp(now).tz_convert("America/New_York").date())

    def project(v: str):
        pv = PropParams.load(VERSIONS[v])
        pv = replace(pv, settings=replace(pv.settings, sims=sims or 10000))
        kw = {}
        if pv.settings.share_model == "role" and len(upcoming):  # depth chart as of now: the role each player holds this week
            kw = {"depth_now": DEPTH.ranks(season, int(upcoming["week"].min()), now)}
        ctx = F.build(inp.player_games, inp.passes, inp.rushes, today, season, pv.settings, **kw)
        out: list[M.PlayerProjection] = []
        sd = {}
        for wk, g in upcoming.groupby("week"):
            ro, inj = I.week_slices(inp, season, int(wk))
            sd[int(wk)] = int(season * 100 + wk)
            need = pv.settings.opp_redistribution == "depth" or pv.settings.questionable_model == "split" or pv.settings.share_model == "role"
            dep = DEPTH.ranks(season, int(wk), now) if need else None
            out += M.project_games(ctx, g, ro, inj, pv, seed=sd[int(wk)], depth=dep)
        return pv, [x for x in out if eligible(x)], sd, out

    p, projs, seeds, _ = project(version)
    shadows = {}
    on_board = {(x.game_id, x.player_id) for x in projs}
    for v in shadow_versions(version):
        pv, px, sd, px_all = project(v)
        if v in SHADOW_ONLY:
            # Shadow-only experiments are recorded for exactly the active version's players, so both are graded on the
            # same player-games (an experiment that moves a backup below the eligibility bar would otherwise drop him).
            px = [x for x in px_all if (x.game_id, x.player_id) in on_board]
        shadows[v] = (pv, px, sd)
    feed = U.load("nfl")
    feed_meta = U.live_meta("nfl")
    if p.settings.injury_context and feed is not None:
        _attach_availability(projs, feed)

    # ---------------------------------------------------------------- market quotes
    quotes: list[PropQuote] = []
    provider_info = []
    for prov in MC.PROVIDERS:
        st = MC.status(prov)
        snap = snapshots.latest("nfl", prov) if st.enabled else pd.DataFrame()
        qs = [PropQuote(**{k: _none(v) for k, v in r.items() if k in PropQuote.__dataclass_fields__}) for r in snap.to_dict("records")] if len(snap) else []
        for q in qs:
            q.game_id = q.player_id = q.match_note = None
        provider_info.append({"provider": prov, "enabled": st.enabled, "publishable": st.publishable, "reason": st.reason,
                              "quotes": len(qs), "last_captured_at": max((q.captured_at for q in qs), default=None)})
        quotes += qs
    mq, problems = manual.load("nfl")
    provider_info.append({"provider": "manual", "enabled": True, "publishable": True, "reason": "manual CSV", "quotes": len(mq),
                          "last_captured_at": max((q.captured_at for q in mq), default=None), "rejected_rows": problems})
    quotes += mq
    sched_games = upcoming[["game_id", "game_date", "home_team", "away_team"]].astype({"game_date": str})
    matching.match_games(quotes, sched_games)
    roster_ids = inp.rosters.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")["sportradar_id"]
    plist = pd.DataFrame([{"game_id": x.game_id, "player_id": x.player_id, "name": x.name, "team": x.team,
                           "sportradar_id": roster_ids.get(x.player_id)} for x in projs])
    if len(plist):
        matching.match_players(quotes, plist)
    publishable = {i["provider"] for i in provider_info if i["publishable"]}
    pub_quotes = [q for q in quotes if q.provider.split(":")[0] in publishable or q.provider.startswith("manual:")]
    idx_pub, idx_all = _quote_index(pub_quotes), _quote_index(quotes)

    # ---------------------------------------------------------------- board
    bt = backtest_summary(version)
    reliability = (bt or {}).get("by_market", {})
    by_game: dict = {}
    local_games: dict = {}
    local_only = any(i["enabled"] and not i["publishable"] for i in provider_info)
    for x in projs:
        by_game.setdefault(x.game_id, []).append(player_entry(x, p, idx_pub.get((x.game_id, x.player_id), []), now, reliability))
        if local_only and idx_all.get((x.game_id, x.player_id)):
            local_games.setdefault(x.game_id, []).append(player_entry(x, p, idx_all[(x.game_id, x.player_id)], now, reliability))
    def price(x, q):
        m = MARKETS.get(q.market)
        if m is None or x.group not in m["positions"]:
            return None
        s = VARIANT_STAT.get((q.market, q.variant), m["stat"])
        return p.calibrate(q.market, x.prob(s, float(q.threshold), q.op)), m["stat"]

    starts_iso = {gid: B.iso(t) for gid, t in upcoming.set_index("game_id")["start_time"].items()}
    evaluated = evaluation.log_run("nfl", projs, idx_all, price, lambda x, mk: x.support(mk)[0], reliability, version,
                                   now.isoformat(timespec="seconds"), starts_iso, now)
    games_json = []
    for _, g in upcoming.iterrows():
        players = sorted(by_game.get(g["game_id"], []), key=lambda e: (e["team"], {"QB": 0, "RB": 1, "WR": 2, "TE": 3}.get(e["position"], 9), e["name"]))
        games_json.append({"game_id": g["game_id"], "start_time": B.iso(g["start_time"]), "game_date": str(g["game_date"]), "week": int(g["week"]),
                           "home": {"abbr": g["home_team"], "name": TEAM_NAMES.get(g["home_team"], g["home_team"])},
                           "away": {"abbr": g["away_team"], "name": TEAM_NAMES.get(g["away_team"], g["away_team"])},
                           "players": players})
    unmatched = [{"provider": q.provider, "player": q.player_name, "market": q.market, "threshold": q.threshold, "note": q.match_note}
                 for q in pub_quotes if q.player_id is None and not q.market.startswith("game_")][:200]

    base_hash = hash_frame(inp.player_games[inp.player_games["season"] >= season - 3], ["game_id", "player_id", "targets", "carries", "pass_att"])
    avail_hash = U.availability_hash("nfl")
    # Ledger records hash only their own game's injury picture (feed rows of both teams + projected starting QBs), so a
    # change elsewhere in the league doesn't re-record every player. Projections don't use this; only the ledger does.
    game_avail = U.game_availability_hashes("nfl", upcoming[["game_id", "home_team", "away_team"]])
    generated_at = now.isoformat(timespec="seconds")
    appended = None
    shadow_appended = {}

    def records(version: str, p: PropParams, projs: list, seeds: dict) -> list[dict]:
        # Versions that read the injury context fold the injury feed and projected starters into the inputs
        # hash: a QB change or a new designation is a new snapshot; earlier snapshots stay as recorded.
        inputs_hash = hash_obj({"base": base_hash, "availability": avail_hash}) if p.settings.injury_context else base_hash
        params_hash = hash_obj(p.to_json())
        starts = upcoming.set_index("game_id")["start_time"]
        recs = []
        for x in projs:
            if p.settings.injury_context:
                inputs_hash = hash_obj({"base": base_hash, "game_availability": game_avail.get(str(x.game_id), "")})
            probs = {}
            for mkey, m in MARKETS.items():
                if x.group in m["positions"]:
                    probs[mkey] = {str(k): round(p.calibrate(mkey, x.prob(m["stat"], k)), 4) for k in m["ladder"]}
                    probs[mkey]["mean"] = round(x.mean(m["stat"]), 2)
                    probs[mkey]["sd"] = round(x.sd(m["stat"]), 2)
                    probs[mkey]["support"] = x.support(mkey)[0]
            recs.append({"sport": "nfl", "kind": "player_props", "game_id": f"{x.game_id}|{x.player_id}", "nfl_game_id": x.game_id,
                         "player_id": x.player_id, "player": x.name, "team": x.team, "game_start": B.iso(starts[x.game_id]),
                         "probabilities": probs, "model_id": MODEL_ID, "model_version": version,
                         **({} if version == MODEL_VERSION else {  # extra fields only for non-default versions; 0.1.0 records stay as they were
                             "role_rank": x.inputs.get("role_rank"), "play_chance": x.inputs.get("play_chance"), "depth_rank": x.inputs.get("depth_rank"),
                             "injury_status": x.inputs.get("injury_status"),
                             "opportunity": {"targets": round(x.mean("targets"), 2), "carries": round(x.mean("carries"), 2),
                                             "team_pass_attempts": x.inputs.get("team_pass_attempts"), "team_carries": x.inputs.get("team_carries")}}),
                         **({"starting_qb": x.inputs.get("starting_qb"), "starting_qb_career_attempts": x.inputs.get("starting_qb_career_attempts"),
                             "injury_source": (x.inputs.get("availability") or {}).get("source"),
                             "injury_report_time": (x.inputs.get("availability") or {}).get("report_time"),
                             "teammates_out": x.inputs.get("teammates_out_detail"), "injury_feed_at": (feed_meta or {}).get("generated_at")}
                            if p.settings.injury_context else {}),
                         "params_hash": params_hash,
                         "inputs_hash": inputs_hash, "generated_at": generated_at, "sims": p.settings.sims,
                         "seed": seeds.get(int(upcoming.set_index("game_id").at[x.game_id, "week"]))})
        return recs

    inputs_hash = hash_obj({"base": base_hash, "availability": avail_hash}) if p.settings.injury_context else base_hash
    params_hash = hash_obj(p.to_json())
    if write_ledger and projs:
        # Weekly ledger files (nfl_props_week_<YYYY>-W<ww>.jsonl, each its own hash chain); nfl_props.jsonl keeps every
        # earlier record exactly as written. Duplicates are checked against the whole series.
        appended = ledger.append_weekly(ledger_path("nfl_props"), now, records(version, p, projs, seeds))
        for v, (pv, px, sd) in shadows.items():
            if px:
                if pv.settings.injury_context and feed is not None:
                    _attach_availability(px, feed)
                shadow_appended[v] = ledger.append_weekly(ledger_path("nfl_props"), now, records(v, pv, px, sd)).__dict__

    last_ingest = state.read().get("nflverse_games", {}).get("last_success")
    pgr = inp.player_games.assign(rush_rec_yds=inp.player_games["rush_yds"] + inp.player_games["rec_yds"],
                                  td_any=inp.player_games["rush_td"] + inp.player_games["rec_td"])
    played = (pgr["offense_snaps"].fillna(0) > 0) | (pgr[["pass_att", "targets", "carries"]].sum(axis=1) > 0)
    recent.attach(games_json, pgr, {k: m["stat"] for k, m in MARKETS.items()}, today, played)
    try:
        prev_board = json.loads(published_props_path().read_text())
    except (OSError, ValueError):
        prev_board = None
    explained = U.explain(prev_board, games_json, ("passing_yards", "receiving_yards", "receptions", "rushing_yards", "rushing_attempts"))
    flags = U.game_flags("nfl", list(upcoming["home_team"]) + list(upcoming["away_team"])) if feed is not None else {}
    for gj in games_json:
        gj["injuries"] = {side: flags.get(gj[side]["abbr"], []) for side in ("home", "away")} if flags else None
    board = {
        "league": "nfl", "kind": "player_props", "generated_at": generated_at, "season": season, "week": week,
        "model": {"id": MODEL_ID, "version": version, "default_version": MODEL_VERSION, "params_hash": params_hash, "inputs_hash": inputs_hash,
                  "status": p.provenance.get("status", "provisional"), "fitted_at": p.provenance.get("fitted_at"),
                  "sims": p.settings.sims, "seeds": seeds,
                  "independence": "Uses only player, team and game-engine data. Exchange prices are never an input; they are compared afterwards.",
                  "injury_feed": feed_meta if feed is not None else None, "shadow_versions": sorted(shadows)},
        "data": {"last_ingest": last_ingest, "results_through": str(inp.player_games["game_date"].max()),
                 "markets": [i for i in provider_info if i["publishable"] or i["provider"] == "manual"],
                 "markets_not_published": [{"provider": i["provider"], "reason": i["reason"]} for i in provider_info if not i["publishable"] and i["provider"] != "manual"],
                 "unmatched_quotes": unmatched,
                 "comparison_rules": {"max_age_min": C.MAX_AGE_MIN, "max_spread": C.MAX_SPREAD, "min_size": C.MIN_SIZE, "min_ev": C.MIN_EV}},
        "performance": {"backtest": bt},
        "games": games_json,
    }
    path = write_board(published_props_path(), board)
    if local_games:
        write_board(local_compare_path(), {**board, "games": [{"game_id": k, "players": v} for k, v in local_games.items()],
                                           "note": "Local only. Includes providers not cleared for publication."})
    state.record("nfl_props_run", model_version=version, players=len(projs))
    return {"board": str(path), "games": len(games_json), "players": len(projs), "quotes": len(quotes),
            "quotes_matched": sum(1 for q in quotes if q.player_id), "evaluated_contracts": evaluated,
            "ledger": appended.__dict__ if appended else None, "shadow_ledger": shadow_appended, "explained_changes": explained}
