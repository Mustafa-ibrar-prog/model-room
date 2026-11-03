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
from modelroom.common import recent
from modelroom.markets import evaluation, manual, matching, snapshots
from modelroom.markets.schema import PropQuote
from modelroom.sources import odds, state

from .. import ingest
from . import features as F
from . import inputs as I
from . import model as M
from .backtest import eligible
from .config import MARKETS, MODEL_ID, MODEL_VERSION, PropParams

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


def backtest_summary() -> dict | None:
    local = output_dir("nfl") / "props_backtest.json"
    f = None
    if local.exists() and json.loads(local.read_text()).get("model_version") == MODEL_VERSION:
        f = local
    else:
        c = MODELING_ROOT.parent / "docs" / "models" / "results" / f"nfl-props-backtest-{MODEL_VERSION}.json"
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
                         "support": support, "support_note": support_note, "thresholds": th}
    return {"player_id": x.player_id, "name": x.name, "team": x.team, "opp": x.opp, "position": x.group,
            "game_id": x.game_id, "injury_status": x.inputs.get("injury_status"), "markets": markets, "inputs": x.inputs}


def run(*, days: int = 10, now: datetime | None = None, write_ledger: bool = True, sims: int | None = None) -> dict:
    now = now or B.now_utc()
    p = PropParams.load()
    p = replace(p, settings=replace(p.settings, sims=sims or 10000))
    games_all = ingest.load_games()
    sched = games_all[games_all["status"] == "scheduled"]
    season = int(sched["season"].min()) if len(sched) else int(games_all["season"].max())
    inp = I.load({season})
    gp = inp.games
    upcoming = B.upcoming_window(gp[gp["status"] == "scheduled"], now, days)
    week = int(upcoming["week"].mode().iloc[0]) if len(upcoming) else None
    today = pd.Timestamp(pd.Timestamp(now).tz_convert("America/New_York").date())
    ctx = F.build(inp.player_games, inp.passes, inp.rushes, today, season, p.settings)
    projs: list[M.PlayerProjection] = []
    seeds = {}
    for wk, g in upcoming.groupby("week"):
        ro, inj = I.week_slices(inp, season, int(wk))
        seeds[int(wk)] = int(season * 100 + wk)
        projs += M.project_games(ctx, g, ro, inj, p, seed=seeds[int(wk)])
    projs = [x for x in projs if eligible(x)]

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
    bt = backtest_summary()
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
    evaluated = evaluation.log_run("nfl", projs, idx_all, price, lambda x, mk: x.support(mk)[0], reliability, MODEL_VERSION,
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

    inputs_hash = hash_frame(inp.player_games[inp.player_games["season"] >= season - 3], ["game_id", "player_id", "targets", "carries", "pass_att"])
    params_hash = hash_obj(p.to_json())
    generated_at = now.isoformat(timespec="seconds")
    appended = None
    if write_ledger and projs:
        starts = upcoming.set_index("game_id")["start_time"]
        recs = []
        for x in projs:
            probs = {}
            for mkey, m in MARKETS.items():
                if x.group in m["positions"]:
                    probs[mkey] = {str(k): round(p.calibrate(mkey, x.prob(m["stat"], k)), 4) for k in m["ladder"]}
                    probs[mkey]["mean"] = round(x.mean(m["stat"]), 2)
                    probs[mkey]["sd"] = round(x.sd(m["stat"]), 2)
                    probs[mkey]["support"] = x.support(mkey)[0]
            recs.append({"sport": "nfl", "kind": "player_props", "game_id": f"{x.game_id}|{x.player_id}", "nfl_game_id": x.game_id,
                         "player_id": x.player_id, "player": x.name, "team": x.team, "game_start": B.iso(starts[x.game_id]),
                         "probabilities": probs, "model_id": MODEL_ID, "model_version": MODEL_VERSION, "params_hash": params_hash,
                         "inputs_hash": inputs_hash, "generated_at": generated_at, "sims": p.settings.sims,
                         "seed": seeds.get(int(upcoming.set_index("game_id").at[x.game_id, "week"]))})
        appended = ledger.append(ledger_path("nfl_props"), recs)

    last_ingest = state.read().get("nflverse_games", {}).get("last_success")
    pgr = inp.player_games.assign(rush_rec_yds=inp.player_games["rush_yds"] + inp.player_games["rec_yds"],
                                  td_any=inp.player_games["rush_td"] + inp.player_games["rec_td"])
    played = (pgr["offense_snaps"].fillna(0) > 0) | (pgr[["pass_att", "targets", "carries"]].sum(axis=1) > 0)
    recent.attach(games_json, pgr, {k: m["stat"] for k, m in MARKETS.items()}, today, played)
    board = {
        "league": "nfl", "kind": "player_props", "generated_at": generated_at, "season": season, "week": week,
        "model": {"id": MODEL_ID, "version": MODEL_VERSION, "params_hash": params_hash, "inputs_hash": inputs_hash,
                  "status": p.provenance.get("status", "provisional"), "fitted_at": p.provenance.get("fitted_at"),
                  "sims": p.settings.sims, "seeds": seeds,
                  "independence": "Uses only player, team and game-engine data. Exchange prices are never an input; they are compared afterwards."},
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
    state.record("nfl_props_run", model_version=MODEL_VERSION, players=len(projs))
    return {"board": str(path), "games": len(games_json), "players": len(projs), "quotes": len(quotes),
            "quotes_matched": sum(1 for q in quotes if q.player_id), "evaluated_contracts": evaluated,
            "ledger": appended.__dict__ if appended else None}
