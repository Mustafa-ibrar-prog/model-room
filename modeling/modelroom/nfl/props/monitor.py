"""Live monitor for the NFL prop models: stored pre-game predictions vs box scores, by model version.

    python -m modelroom nfl props-monitor     → data/published/props_monitor_nfl.json

Reads the append-only prediction ledger (never changes it). For each player-game it keeps the LAST
prediction recorded before kickoff for each model version, joins the final box score, and reports per
version:
  * opportunity by position and depth-chart rank (RB1..RB4 carries, WR1..WR4 / TE1..TE4 targets): mean
    projected vs actual, bias and MAE. The rank is the depth chart as of kickoff, looked up the same way
    for every version (records written before the ledger stored a rank are ranked too). Targets are only
    in records that store them (0.3.0 on); every version has receptions and rushing attempts.
  * team totals: projected vs actual targets and carries summed over the graded players of each team-game
  * every market: mean bias / MAE, and Over / Under calibration at the stored ladder lines
  * by injury designation (none / Questionable)
Graded only on players who played (exchanges settle props on players who don't play at a fair price).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.paths import data_root, ledger_path

from . import depth as DEPTH
from .config import MARKETS


def _pregame(recs: list[dict]) -> pd.DataFrame:
    rows = []
    for r in recs:
        if r.get("kind") != "player_props":
            continue
        rows.append({"key": r["game_id"], "game_id": str(r["nfl_game_id"]), "player_id": str(r["player_id"]), "team": r.get("team"),
                     "version": r["model_version"], "generated_at": r["generated_at"], "game_start": r["game_start"],
                     "injury_status": r.get("injury_status"), "opportunity": r.get("opportunity") or {}, "probabilities": r["probabilities"]})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d = d[pd.to_datetime(d["generated_at"], utc=True) < pd.to_datetime(d["game_start"], utc=True)]
    return d.sort_values("generated_at").groupby(["key", "version"]).tail(1)


def _err(p: pd.Series, a: pd.Series) -> dict:
    m = p.notna() & a.notna()
    p, a = p[m], a[m]
    if not len(p):
        return {"n": 0}
    e = p - a
    return {"n": int(len(p)), "proj": round(float(p.mean()), 2), "actual": round(float(a.mean()), 2), "bias": round(float(e.mean()), 2),
            "bias_pct": round(float(100 * e.mean() / max(a.mean(), 1e-9)), 1), "mae": round(float(e.abs().mean()), 2)}


def _cal(p: np.ndarray, y: np.ndarray) -> dict:
    if len(p) == 0:
        return {"n": 0}
    idx = np.clip((p * 10).astype(int), 0, 9)
    ece = sum((idx == b).sum() / len(p) * abs(p[idx == b].mean() - y[idx == b].mean()) for b in range(10) if (idx == b).any())
    o, u = p > 0.5, p < 0.5
    side = lambda m, pp, yy: {"n": int(m.sum()), "priced": round(float(pp[m].mean()), 4), "hit": round(float(yy[m].mean()), 4)} if m.any() else {"n": 0}  # noqa: E731
    return {"n": int(len(p)), "ece": round(float(ece), 4), "over_leans": side(o, p, y), "under_leans": side(u, 1 - p, 1 - y)}


def build(pred: pd.DataFrame, box: pd.DataFrame, ranks=None) -> dict:
    """box: game_id, player_id, group (RB/WR/TE/QB), season, week, targets, carries, receptions, rec_yds, rush_yds,
    team_pass_att, team_carries, plus every market stat. ranks(season, week, cutoff) → {player_id: rank}."""
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "versions": {}}
    if pred.empty:
        return out
    ranks = ranks or DEPTH.ranks
    b = box.assign(game_id=box["game_id"].astype(str), player_id=box["player_id"].astype(str)).drop(columns=["team"], errors="ignore")
    d = pred.merge(b, on=["game_id", "player_id"], how="inner")
    if d.empty:
        return out
    cache: dict = {}
    dr = []
    for s, w, gs, pid in d[["season", "week", "game_start", "player_id"]].itertuples(index=False):
        k = (int(s), int(w), gs)
        if k not in cache:
            cache[k] = ranks(int(s), int(w), pd.Timestamp(gs))
        dr.append(cache[k].get(pid))
    d = d.assign(depth=pd.Series(dr, index=d.index).fillna(9).clip(upper=4).astype(int),
                 proj_tg=[o.get("targets") for o in d["opportunity"]], proj_car=[o.get("carries") for o in d["opportunity"]],
                 inj=d["injury_status"].fillna("none"))
    for k, m in MARKETS.items():
        d[f"m_{k}"] = [p.get(k, {}).get("mean") for p in d["probabilities"]]
    for v, g in d.groupby("version"):
        rep = {"player_games": int(len(g)), "games": int(g["game_id"].nunique()), "first_game": str(g["game_start"].min()),
               "last_game": str(g["game_start"].max()), "by_depth": {}, "team": {}, "markets": {}, "by_injury": {}}
        for grp in ("RB", "WR", "TE"):
            x = g[g["group"] == grp]
            for r, y in x.groupby("depth"):
                lab = f"{grp}{r}" if r < 4 else f"{grp}4+"
                rep["by_depth"][lab] = {"carries": _err(y["proj_car"].astype(float), y["carries"]) if grp == "RB" else None,
                                        "rushing_attempts": _err(y["m_rushing_attempts"].astype(float), y["carries"]) if grp == "RB" else None,
                                        "targets": _err(y["proj_tg"].astype(float), y["targets"]),
                                        "receptions": _err(y["m_receptions"].astype(float), y["receptions"])}
        t = g[g["group"].isin(["RB", "WR", "TE"])].groupby(["game_id", "team"]).agg(
            tg_p=("proj_tg", lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1)), tg=("targets", "sum"),
            car_p=("proj_car", lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1)), car=("carries", "sum"),
            rec_p=("m_receptions", lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1)), rec=("receptions", "sum"))
        rep["team"] = {"targets": _err(t["tg_p"], t["tg"]), "carries": _err(t["car_p"], t["car"]), "receptions": _err(t["rec_p"], t["rec"])}
        for mk, m in MARKETS.items():
            st = m["stat"]
            if st not in g.columns:
                continue
            y = g.dropna(subset=[f"m_{mk}"])
            ps, ys = [], []
            for prob, val in zip(y["probabilities"], y[st]):
                for k, pk in prob.get(mk, {}).items():
                    if k in ("mean", "sd", "support"):
                        continue
                    ps.append(float(pk))
                    ys.append(float(val >= float(k)))
            ps, ys = np.asarray(ps), np.asarray(ys)
            keep = (ps >= 0.02) & (ps <= 0.98)
            rep["markets"][mk] = {"mean": _err(y[f"m_{mk}"].astype(float), y[st]), "calibration": _cal(ps[keep], ys[keep])}
        for inj, y in g.groupby("inj"):
            rep["by_injury"][str(inj)] = {"receptions": _err(y["m_receptions"].astype(float), y["receptions"]),
                                          "rushing_attempts": _err(y["m_rushing_attempts"].astype(float), y["carries"])}
        out["versions"][v] = rep
    return out


def run() -> dict:
    from modelroom.nfl import player_data
    from .features import GROUPS

    pred = _pregame(ledger.read_series(ledger_path("nfl_props")))
    pg, _, _ = player_data.load()
    pg = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
    pg = pg.assign(group=pg["position"].map(GROUPS), rush_rec_yds=pg["rush_yds"] + pg["rec_yds"], td_any=pg["rush_td"] + pg["rec_td"])
    box = pg.drop_duplicates(["game_id", "player_id"])
    rep = build(pred, box)
    rep["note"] = ("Last pre-game prediction per player-game and model version, graded on players who played. Depth rank = the "
                   "depth chart as of kickoff, the same lookup for every version. The ledger is append-only: earlier versions' "
                   "predictions stay exactly as recorded.")
    f = data_root() / "published" / "props_monitor_nfl.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rep, indent=2, default=str))
    return {"file": str(f), "versions": {v: {"player_games": r["player_games"], "games": r["games"]} for v, r in rep["versions"].items()}}
