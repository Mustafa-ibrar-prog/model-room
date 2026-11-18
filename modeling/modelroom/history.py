"""Results history for the website: what the model said before each game, and what happened.

    python -m modelroom history            (run after the projection commands)

Projections come only from the prediction ledgers, which are written before kickoff and never edited.
Nothing here re-projects a past game. Dates before the ledger began show results only.

Writes (data/published/history/<league>/):
  index.json        dates available, with counts
  <YYYY-MM-DD>.json  that day's games (final score, recorded pre-game projection, error) and recorded
                    prop projections (mean, sd, threshold probabilities) with the actual stat and Hit/Miss
and data/published/performance_<league>.json: graded accuracy of everything recorded so far.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom import picks as P
from modelroom import published as PUB
from modelroom.common import ledger
from modelroom.common.paths import data_root, ensure, ledger_path
from modelroom.common.publish import write_board

SEASONS_BACK = 1  # results-only dates: the current season and the one before
PICK_FREEZE_WINDOW_H = 48  # after the first run, a missed pick is only written within this long of its game starting
PICK_FREEZE_LEAD_MIN = 75  # picks are written at the last refresh before a game (the pre-game slot runs 30 minutes out)


def _out(league: str):
    return ensure(data_root() / "published" / "history" / league)


def _pregame(records: list[dict], start_key: str = "game_start") -> dict:
    """Latest record per key made before its game started (the ledger only accepts pre-game records)."""
    best: dict = {}
    for r in records:
        k = r["game_id"]
        if r["generated_at"] >= r[start_key]:
            continue
        if k not in best or r["generated_at"] > best[k]["generated_at"]:
            best[k] = r
    return best


def _games_table(league: str) -> pd.DataFrame:
    if league == "nfl":
        from modelroom.nfl.ingest import load_games

        g = load_games()
        g = g[g["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])]
        return pd.DataFrame({"game_id": g["game_id"].astype(str), "season": g["season"], "game_date": g["game_date"].astype(str),
                             "start_time": g["start_time"], "home": g["home_team"], "away": g["away_team"],
                             "home_score": g["home_score"], "away_score": g["away_score"], "status": g["status"]})
    from modelroom.nba import ingest

    g, _ = ingest.load()
    return pd.DataFrame({"game_id": g["game_id"].astype(str), "season": g["season"], "game_date": g["game_date"].astype(str),
                         "start_time": g["start_time"], "home": g["home_abbr"], "away": g["away_abbr"],
                         "home_score": g["home_score"], "away_score": g["away_score"],
                         "status": g["status"].replace({"final_no_box": "final"})})


def _player_stats(league: str) -> dict:
    """(game_id, player_id) → {stat: value} for players who played."""
    if league == "nfl":
        from modelroom.nfl import player_data

        pg, _, _ = player_data.load()
        pg = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
        pg = pg.assign(rush_rec_yds=pg["rush_yds"] + pg["rec_yds"], td_any=pg["rush_td"] + pg["rec_td"])
        from modelroom.nfl.props.config import MARKETS
    else:
        from modelroom.nba.props import data

        pg = data.load()
        pg = pg[pg["played"]]
        from modelroom.nba.props.config import MARKETS
    stats = {m["stat"] for m in MARKETS.values()}
    cols = [c for c in stats if c in pg.columns]
    out = {}
    for row in pg[["game_id", "player_id", *cols]].itertuples(index=False):
        out[(str(row[0]), str(row[1]))] = dict(zip(cols, row[2:]))
    return out, {k: m["stat"] for k, m in MARKETS.items()}, {k: m["label"] for k, m in MARKETS.items()}


def _market(league: str) -> dict:
    """{game_id: market dict} as the site had it before each game: Odds API / manual snapshots captured
    before kickoff, else (NFL) nflverse's published line. Each keeps its source."""
    from modelroom.common import board as B
    from modelroom.common.paths import processed_dir
    from modelroom.sources import odds

    out: dict = {}
    f = processed_dir(league) / "market_snapshots.parquet"
    if f.exists():
        snaps = pd.read_parquet(f)
        if len(snaps):
            ts = pd.to_datetime(snaps["captured_at"], utc=True, errors="coerce")
            st = pd.to_datetime(snaps["commence_time"], utc=True, errors="coerce")
            snaps = snaps[ts < st]
            if len(snaps):
                out = B.market_by_game(odds.consensus(snaps), snaps)
    if league == "nfl" and (processed_dir("nfl") / "market_lines.parquet").exists():
        from modelroom.nfl.pipeline import _markets

        for gid, m in _markets(pd.DataFrame()).items():
            out.setdefault(gid, m)
    return out


def _sigmas(league: str) -> tuple[float | None, float | None]:
    try:
        u = json.loads((data_root() / "published" / f"{league}.json").read_text())["model"]["uncertainty"]
        return float(u["margin_sigma"]), float(u["total_sigma"])
    except Exception:  # noqa: BLE001
        return None, None


def _grade_side(won: bool | None, push: bool) -> str:
    return "push" if push else ("win" if won else "loss")


def market_picks(pre: dict, market: dict | None, final: dict | None, sig: tuple) -> dict | None:
    """The model's side at the market's spread and total (the side its own distribution gives the higher
    chance), its probability, and how that side settled. Projection error is graded elsewhere."""
    from modelroom.common import oddsmath as O

    if not market or not pre:
        return None
    ms, ts = sig
    out = {"source": ",".join(market.get("sources") or []) or None, "captured_at": market.get("captured_at"), "spread": None, "total": None,
           "implied_scores": None}
    sp, tot = market.get("spread"), market.get("total")
    if sp is not None and tot is not None:
        out["implied_scores"] = {"home": round((tot - sp) / 2, 1), "away": round((tot + sp) / 2, 1)}
    if sp is not None and ms:
        c = O.cover_probs(pre["pred_margin"], ms, sp)
        side = "home" if c["home"] >= c["away"] else "away"
        row = {"line": sp, "pick": side, "model_prob": round(c[side], 4), "push_prob": round(c["push"], 4), "result": None}
        if final:
            m = final["home"] - final["away"]
            v = m + sp
            row["result"] = _grade_side((v > 0) == (side == "home"), v == 0)
        out["spread"] = row
    if tot is not None and ts:
        o = O.over_probs(pre["pred_total"], ts, tot)
        side = "over" if o["over"] >= o["under"] else "under"
        row = {"line": tot, "pick": side, "model_prob": round(o[side], 4), "push_prob": round(o["push"], 4), "result": None}
        if final:
            t = final["home"] + final["away"]
            row["result"] = _grade_side((t > tot) == (side == "over"), t == tot)
        out["total"] = row
    return out


def _f(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def build(league: str) -> dict:
    games = _games_table(league)
    season_now = int(games.loc[games["status"].isin(["final", "scheduled"]), "season"].max())
    games = games[games["season"] >= season_now - SEASONS_BACK]
    game_recs = _pregame(ledger.read(ledger_path(league)))
    # Only the version that was published when each record was made: shadow versions share these ledgers and must
    # never become a pick or a shown result (see modelroom/published.py).
    prop_recs = _pregame([r for r in ledger.read_series(ledger_path(f"{league}_props")) if PUB.is_published(league, r)])
    env_v = PUB.current_env_version(league)
    if env_v and env_v != PUB.published_version(league, datetime.now(timezone.utc)):
        print(f"WARNING: MODELROOM_{league.upper()}_PROPS_VERSION={env_v} but modelroom/published.py says "
              f"{PUB.published_version(league, datetime.now(timezone.utc))}: add the switch to the timeline")
    stats, stat_of, label_of = _player_stats(league)
    markets, sig = _market(league), _sigmas(league)
    gid_key = "nfl_game_id" if league == "nfl" else "nba_game_id"
    props_by_game: dict = {}
    for r in prop_recs.values():
        props_by_game.setdefault(str(r[gid_key]), []).append(r)

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    out = _out(league)
    index, grades_games, grades_props = [], [], []
    first_run = not P.picks_path(league).exists()
    fresh_after = (now - pd.Timedelta(hours=PICK_FREEZE_WINDOW_H)).isoformat()
    candidates, day_ctx = [], {}
    stat_games = {k[0] for k in stats}
    days_out: dict = {}
    for day, g in games.groupby("game_date"):
        if day > today:
            continue
        day_games, day_props = [], []
        for _, x in g.sort_values("start_time").iterrows():
            final = x["status"] == "final" and pd.notna(x["home_score"])
            rec = game_recs.get(x["game_id"])
            pre = None
            if rec:
                pre = {k: rec.get(k) for k in ("generated_at", "model_version", "pred_home_score", "pred_away_score", "pred_margin", "pred_total", "home_win_prob")}
            err = None
            if final and pre:
                margin = float(x["home_score"] - x["away_score"])
                total = float(x["home_score"] + x["away_score"])
                err = {"margin_error": round(pre["pred_margin"] - margin, 1), "total_error": round(pre["pred_total"] - total, 1),
                       "winner_correct": None if margin == 0 else bool((pre["home_win_prob"] > 0.5) == (margin > 0))}
                grades_games.append({"date": day, "p": pre["home_win_prob"], "y": float(margin > 0), "margin_err": abs(err["margin_error"]),
                                     "total_err": abs(err["total_error"]), "correct": err["winner_correct"]})
            fin = {"home": int(x["home_score"]), "away": int(x["away_score"])} if final else None
            # Picks are frozen once a game has started, from its last pre-game record. After the first run a pick
            # is only ever created close to its game's start, never for an old game.
            start_iso = None if pd.isna(x["start_time"]) else pd.Timestamp(x["start_time"]).isoformat()
            gctx = {"game_id": x["game_id"], "date": day, "home": x["home"], "away": x["away"]}
            if rec:
                starts = pd.Timestamp(rec["game_start"])
                before = now < starts
                soon = before and starts - now <= pd.Timedelta(minutes=PICK_FREEZE_LEAD_MIN)
                recent = (not before) and (first_run or rec["game_start"] >= fresh_after)
                if soon or recent:
                    # A spread or total pick needs a side AND a line, and the line is not in the model's own record,
                    # so it only exists if it is written here before the game starts. The winner (the recorded win
                    # probability) and player thresholds (recorded with their probabilities) are in the prediction
                    # ledger already, so those can still be written from it after the start.
                    cands = P.game_picks(league, gctx, rec, markets.get(x["game_id"]) if before else None)
                    for r in props_by_game.get(x["game_id"], []):
                        cands += P.prop_picks(league, gctx, r, label_of)
                    for c in cands:
                        c["frozen_before_start"] = bool(before)
                    candidates += cands
            day_ctx.setdefault(day, []).append({"game_id": x["game_id"], "status": x["status"], "final": fin, "start_time": start_iso,
                                                "home": x["home"], "away": x["away"]})
            picks = market_picks(pre, markets.get(x["game_id"]), fin, sig)
            day_games.append({"game_id": x["game_id"], "start_time": None if pd.isna(x["start_time"]) else pd.Timestamp(x["start_time"]).isoformat(),
                              "home": x["home"], "away": x["away"], "status": x["status"],
                              "final": fin, "pregame": pre, "result": err, "market": picks})
            for r in props_by_game.get(x["game_id"], []):
                actual = stats.get((x["game_id"], str(r["player_id"]))) if final else None
                pm = {}  # NOT `markets`: that name is the pre-game market table used for every later game
                for mkey, probs in r["probabilities"].items():
                    stat = stat_of.get(mkey)
                    a = _f(actual.get(stat)) if actual and stat in actual else None
                    th = []
                    for k, p in probs.items():
                        if k in ("mean", "sd", "support"):
                            continue
                        hit = None if a is None else bool(a >= float(k))
                        th.append({"k": float(k), "p": p, "hit": hit})
                        if hit is not None:
                            grades_props.append({"date": day, "market": mkey, "player": r["player"], "player_id": str(r["player_id"]),
                                                 "p": p, "y": float(hit)})
                    pm[mkey] = {"label": label_of.get(mkey, mkey), "mean": probs.get("mean"), "sd": probs.get("sd"),
                                     "support": probs.get("support") or r.get("support"), "actual": a,
                                     "thresholds": sorted(th, key=lambda t: t["k"])}
                day_props.append({"game_id": x["game_id"], "player_id": str(r["player_id"]), "player": r["player"], "team": r["team"],
                                  "generated_at": r["generated_at"], "model_version": r["model_version"],
                                  "played": actual is not None if final else None, "markets": pm})
        days_out[day] = {"league": league, "kind": "history", "date": day, "games": day_games, "props": day_props}
        index.append({"date": day, "games": len(day_games), "with_projection": sum(1 for x in day_games if x["pregame"]),
                      "props": len(day_props)})
    pick_info = _settle_picks(league, candidates, day_ctx, days_out, stats, stat_of, stat_games, now, first_run, label_of)
    for day, body in days_out.items():
        write_board(out / f"{day}.json", body)
    first = min((r["generated_at"][:10] for r in game_recs.values()), default=None)
    write_board(out / "index.json", {"league": league, "kind": "history_index", "first_recorded": first,
                                     "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dates": index})
    perf = performance(league, grades_games, grades_props)
    write_board(data_root() / "published" / f"performance_{league}.json", perf)
    return {"dates": len(index), "graded_games": len(grades_games), "graded_thresholds": len(grades_props), "picks": pick_info}


def _settle_picks(league: str, candidates: list[dict], day_ctx: dict, days_out: dict, stats: dict, stat_of: dict,
                  stat_games: set, now: datetime, first_run: bool, labels: dict) -> dict:
    """Freeze new picks, grade every stored pick against the verified result, log settlements and corrections, and
    attach the graded picks to each day's file. Reads picks back from the ledger: what is graded is what was stored."""
    froze = P.freeze(league, candidates, now, backfilled_before=now.isoformat() if first_run else None)
    by_game: dict = {}
    for pk in P.read_picks(league).values():
        by_game.setdefault(pk["league_game_id"], []).append(pk)
    order = {"moneyline": 0, "spread": 1, "total": 2, "prop": 3}
    graded, by_date, all_results = [], [], {"moneyline": [], "spread": [], "total": [], "prop": []}
    # How each stored pick came to exist: written before its game started, or written afterwards from the
    # projection that was recorded before it. The page labels the two apart; neither is ever relabelled.
    provenance = {k: {"pre_game": 0, "reconstructed": 0} for k in all_results}
    # A stored player pick counts toward the official record only if it came from the version that was published when
    # its prediction was made. Picks taken from shadow versions before 2026-11-18 stay in the ledger, keep their grade and
    # are listed (labelled) for audit; they are left out of every official total. Nothing stored is changed.
    excluded: list[dict] = []
    for day in sorted(day_ctx):
        rows = []
        for g in day_ctx[day]:
            fin = g["final"]
            for pk in sorted(by_game.get(g["game_id"], []), key=lambda r: (order[r["market"]], r.get("player") or "", r.get("stat") or "")):
                actual = played = None
                if pk["market"] == "prop":
                    if fin and g["game_id"] in stat_games:  # a final game with no box score at all is pending, not void
                        st = stats.get((g["game_id"], pk["player_id"]))
                        played = st is not None
                        col = stat_of.get(pk["stat"])
                        actual = _f(st.get(col)) if st and col in st else None
                    evidence = {"actual": actual, "played": played}
                else:
                    evidence = {"home_score": fin["home"], "away_score": fin["away"]} if fin else None
                res = P.grade(pk, g["status"], fin, actual, played)
                if res == "cancelled":
                    evidence = {"status": g["status"]}
                graded.append({"pick_id": pk["game_id"], "result": res, "evidence": evidence})
                official = pk["market"] != "prop" or PUB.is_published(league, pk)
                if official:
                    all_results[pk["market"]].append(res)
                    provenance[pk["market"]]["pre_game" if pk.get("frozen_before_start") else "reconstructed"] += 1
                row = {"id": pk["game_id"], "game_id": g["game_id"], "market": pk["market"], "selection": pk["selection"], "team": pk.get("team"),
                       "line": pk.get("line"), "model_number": pk.get("model_number"), "model_prob": pk.get("model_prob"),
                       "model_version": pk["model_version"], "recorded_at": pk["generated_at"], "backfilled": pk.get("backfilled", False),
                       "frozen_before_start": pk.get("frozen_before_start", False),
                       "result": res}
                if pk["market"] == "prop":
                    row.update(player=pk["player"], player_id=pk["player_id"], stat=pk["stat"], stat_label=labels.get(pk["stat"], pk["stat"]),
                               line_kind=pk.get("line_kind"), support=pk.get("support"), actual=actual, played=played)
                else:
                    row.update(line_source=pk.get("line_source"), line_books=pk.get("line_books"))
                if not official:
                    row.update(excluded="unpublished_version", published_version=PUB.published_version(league, pk["generated_at"]))
                    excluded.append({"date": day, **{k: row.get(k) for k in ("id", "game_id", "player", "stat", "stat_label", "selection", "line",
                                                                              "model_version", "published_version", "recorded_at",
                                                                              "frozen_before_start", "result")}})
                rows.append(row)
        if day in days_out:
            days_out[day]["picks"] = rows
        off = [r for r in rows if not r.get("excluded")]
        if off:
            by_date.append({"date": day, "games": P.record_of([r["result"] for r in off if r["market"] != "prop"]),
                            "props": P.record_of([r["result"] for r in off if r["market"] == "prop"]),
                            # winner, spread and total are different bets: each keeps its own record for the day
                            **{k: P.record_of([r["result"] for r in off if r["market"] == k]) for k in ("moneyline", "spread", "total")}})
    log = P.record_grades(league, graded, now)
    game_results = all_results["moneyline"] + all_results["spread"] + all_results["total"]
    summary = {"league": league, "kind": "picks_summary", "generated_at": now.isoformat(timespec="seconds"),
               "note": "Picks are frozen from the last projection recorded before each game and graded on the selected side. "
                       "Only hits, misses and pushes count as graded; the hit rate is hits / (hits + misses).",
               "overall": {"games": P.record_of(game_results), "props": P.record_of(all_results["prop"]),
                           **{k: P.record_of(v) for k, v in all_results.items()}},
               "by_date": by_date,
               "provenance": provenance,
               "excluded": {"total": len(excluded),
                            "rule": "Player picks whose prediction came from a model version that was not the published one when it was made "
                                    "(shadow versions read by mistake before 2026-11-18). Kept in the ledger with their grade; not counted.",
                            "record": P.record_of([e["result"] for e in excluded]),
                            "by_version": {v: sum(1 for e in excluded if e["model_version"] == v) for v in sorted({e["model_version"] for e in excluded})},
                            "picks": excluded},
               "backfilled_picks": sum(1 for v in by_game.values() for pk in v if pk.get("backfilled"))}
    write_board(_out(league) / "picks_summary.json", summary)
    return {**froze, **log, "graded": summary["overall"]["games"]["graded"] + summary["overall"]["props"]["graded"]}


def _prob_block(d: pd.DataFrame) -> dict:
    p = np.clip(d["p"].to_numpy(float), 1e-4, 1 - 1e-4)
    y = d["y"].to_numpy(float)
    return {"n": int(len(d)), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
            "avg_predicted": round(float(p.mean()), 3), "hit_rate": round(float(y.mean()), 3)}


def _calibration(d: pd.DataFrame) -> list[dict]:
    edges = np.linspace(0, 1, 11)
    b = pd.cut(d["p"], edges, include_lowest=True)
    return [{"bin": f"{iv.left:.1f}-{iv.right:.1f}", "n": int(len(g)), "predicted": round(float(g["p"].mean()), 3), "actual": round(float(g["y"].mean()), 3)}
            for iv, g in d.groupby(b, observed=True)]


def performance(league: str, games: list[dict], props: list[dict]) -> dict:
    out = {"league": league, "kind": "performance", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": "Graded from projections recorded before each game (prediction ledger). Small samples are noisy; see n."}
    g = pd.DataFrame(games)
    if len(g):
        out["games"] = {"n": int(len(g)), "margin_mae": round(float(g["margin_err"].mean()), 2), "total_mae": round(float(g["total_err"].mean()), 2),
                        "winner_correct": round(float(g["correct"].dropna().mean()), 3) if g["correct"].notna().any() else None,
                        "win_prob": _prob_block(g), "by_date": [{"date": d, **_prob_block(x), "margin_mae": round(float(x["margin_err"].mean()), 2)}
                                                               for d, x in g.groupby("date")]}
    p = pd.DataFrame(props)
    if len(p):
        top = p.groupby("player_id").size().sort_values(ascending=False).head(60).index
        out["props"] = {
            "overall": _prob_block(p), "calibration": _calibration(p),
            "by_market": {k: _prob_block(x) for k, x in p.groupby("market")},
            "by_date": [{"date": d, **_prob_block(x)} for d, x in p.groupby("date")],
            "by_player": sorted([{"player": x["player"].iloc[0], **_prob_block(x)} for pid, x in p[p["player_id"].isin(top)].groupby("player_id")],
                                key=lambda r: -r["n"]),
        }
    return out


def run(leagues: tuple = ("nfl", "nba")) -> dict:
    return {lg: build(lg) for lg in leagues}
