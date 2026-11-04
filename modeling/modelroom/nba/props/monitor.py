"""Live monitor for the NBA prop models: stored pre-game predictions vs what happened, by model version.

    python -m modelroom nba props-monitor     → data/published/props_monitor_nba.json

Reads the append-only prediction ledger (never changes it). For each player-game it takes the LAST
prediction recorded before tip-off for each model version, joins the final box score, and reports, per
version:
  * minutes: projected vs actual, starters and bench separately (starter = started that game)
  * points / PRA (and every other market): mean bias, MAE, RMSE, bench vs starters, with vs without a
    teammate ruled out (the injury adjustment)
  * Over / Under calibration at the stored ladder lines: Over leans (p > 0.5) and Under leans (p < 0.5)
    each compared with how often they hit, plus ECE over all lines
Only players who played are graded (exchanges settle props on inactive players at a fair price).
Versions are reported side by side; a version with no completed games yet shows n = 0.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.paths import data_root, ledger_path

from .config import MARKETS

FOCUS = ("points", "pra")


def _pregame(recs: list[dict]) -> pd.DataFrame:
    rows = []
    for r in recs:
        if r.get("kind") != "player_props":
            continue
        rows.append({"key": r["game_id"], "game_id": str(r["nba_game_id"]), "player_id": str(r["player_id"]), "player": r.get("player"),
                     "team": r.get("team"), "version": r["model_version"], "generated_at": r["generated_at"], "game_start": r["game_start"],
                     "proj_min": r.get("projected_minutes"), "starter_rate": r.get("starter_rate"),
                     "usage_freed": r.get("usage_freed_by_absences"), "probabilities": r["probabilities"]})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d = d[pd.to_datetime(d["generated_at"], utc=True) < pd.to_datetime(d["game_start"], utc=True)]
    return d.sort_values("generated_at").groupby(["key", "version"]).tail(1)


def _cal(p: np.ndarray, y: np.ndarray) -> dict:
    if len(p) == 0:
        return {"n": 0}
    idx = np.clip((p * 10).astype(int), 0, 9)
    ece = sum((idx == b).sum() / len(p) * abs(p[idx == b].mean() - y[idx == b].mean()) for b in range(10) if (idx == b).any())
    o, u = p > 0.5, p < 0.5
    side = lambda m, pp, yy: {"n": int(m.sum()), "priced": round(float(pp[m].mean()), 4), "hit": round(float(yy[m].mean()), 4)} if m.any() else {"n": 0}  # noqa: E731
    return {"n": int(len(p)), "ece": round(float(ece), 4), "over_leans": side(o, p, y), "under_leans": side(u, 1 - p, 1 - y)}


def _err(d: pd.DataFrame, pc: str, ac: str) -> dict:
    if d.empty:
        return {"n": 0}
    e = d[pc] - d[ac]
    return {"n": int(len(d)), "mean_proj": round(float(d[pc].mean()), 2), "mean_actual": round(float(d[ac].mean()), 2),
            "bias": round(float(e.mean()), 2), "bias_pct": round(float(100 * e.mean() / max(d[ac].mean(), 1e-9)), 1),
            "mae": round(float(e.abs().mean()), 2), "rmse": round(float(np.sqrt((e ** 2).mean())), 2)}


def build(pred: pd.DataFrame, box: pd.DataFrame) -> dict:
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "versions": {}}
    if pred.empty:
        return out
    b = box[box["played"]].assign(game_id=lambda x: x["game_id"].astype(str), player_id=lambda x: x["player_id"].astype(str))
    d = pred.merge(b, on=["game_id", "player_id"], how="inner")
    for v, g in d.groupby("version"):
        # Role = whether he started that game (box score), so every version is split the same way, including
        # records written before the ledger stored the model's own starter estimate.
        role = np.where(g["starter"].astype(bool), "starter", "bench") if "starter" in g else np.where(g["starter_rate"].fillna(0) > 0.5, "starter", "bench")
        injury = np.where(g["usage_freed"].isna(), "not recorded", np.where(g["usage_freed"].fillna(0) > 0, "teammate_out", "none"))
        g = g.assign(role=role, injury=injury)
        rep = {"player_games": int(len(g)), "games": int(g["game_id"].nunique()),
               "first_game": str(g["game_start"].min()), "last_game": str(g["game_start"].max()),
               "minutes": {"all": _err(g, "proj_min", "minutes"), **{r: _err(x, "proj_min", "minutes") for r, x in g.groupby("role")}},
               "markets": {}}
        for mk, m in MARKETS.items():
            st = m["stat"]
            g2 = g.assign(mean=[p.get(mk, {}).get("mean") for p in g["probabilities"]]).dropna(subset=["mean"])
            ps, ys = [], []
            for prob, y in zip(g2["probabilities"], g2[st]):
                for k, pk in prob.get(mk, {}).items():
                    if k in ("mean", "sd"):
                        continue
                    ps.append(float(pk))
                    ys.append(float(y >= float(k)))
            ps, ys = np.asarray(ps), np.asarray(ys)
            keep = (ps >= 0.02) & (ps <= 0.98)
            entry = {"all": _err(g2, "mean", st), "calibration": _cal(ps[keep], ys[keep])}
            if mk in FOCUS:
                entry["by_role"] = {r: _err(x, "mean", st) for r, x in g2.groupby("role")}
                entry["by_injury"] = {r: _err(x, "mean", st) for r, x in g2.groupby("injury")}
            rep["markets"][mk] = entry
        out["versions"][v] = rep
    return out


def run() -> dict:
    from . import data

    pred = _pregame(ledger.read(ledger_path("nba_props")))
    box = data.load()
    rep = build(pred, box)
    rep["note"] = ("Last pre-game prediction per player-game and model version, graded on players who played. "
                   "The ledger is append-only: earlier versions' predictions stay exactly as recorded.")
    f = data_root() / "published" / "props_monitor_nba.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rep, indent=2, default=str))
    return {"file": str(f), "versions": {v: {"player_games": r["player_games"], "games": r["games"],
                                             "points_bias_pct": r["markets"]["points"]["all"].get("bias_pct"),
                                             "minutes_bias": r["minutes"]["all"].get("bias")} for v, r in rep["versions"].items()}}
