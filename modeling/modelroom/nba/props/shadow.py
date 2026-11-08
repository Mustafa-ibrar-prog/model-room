"""NBA shadow evaluation (test site): the active version against shadow candidates on IDENTICAL player-games.

    python -m modelroom nba props-shadow      → preview-ledger/reports/nba_props_shadow.json

Reads the append-only prediction ledger (never changes it). For every player-game it takes each version's LAST
record before tip-off and keeps the player-game only if every compared version has one from the SAME refresh
(same generated_at), i.e. the same games and the same pregame information. Graded on players who played.

Breakdowns use one definition for every version (taken from the shadow candidate's record, which carries the
injury feed, or from the box score): prop category, role (started / bench, and minutes band from prior games),
the player's own injury status and its source, number of teammates listed Out/Doubtful, Questionable players,
and whether any teammate was ruled out by ESPN alone (not on the official report). Watch-items from the
approval: bench over-projection, blocks bias, Questionable players, Over/Under calibration.

Over/Under: line = ceil(median of his last 10 games) (as in the accuracy audit); P(over) is read off the stored
ladder by interpolation in logit space (the same approximation for every version).
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.paths import ledger_path

from .config import MARKETS

ACTIVE = "0.2.0"
SHADOWS = ("0.2.3a", "0.2.3")
EPS = 1e-6


def _load(recs: list[dict], versions: tuple) -> pd.DataFrame:
    rows = []
    for r in recs:
        if r.get("kind") != "player_props" or r.get("model_version") not in versions:
            continue
        tm = r.get("teammates_out") or []
        rows.append({"key": r["game_id"], "game_id": str(r["nba_game_id"]), "player_id": str(r["player_id"]), "player": r.get("player"),
                     "team": r.get("team"), "version": r["model_version"], "generated_at": r["generated_at"], "game_start": r["game_start"],
                     "proj_min": r.get("projected_minutes"), "probabilities": r["probabilities"],
                     "status": r.get("injury_status"), "source": r.get("injury_source"), "conflict": r.get("injury_conflict"),
                     "n_out": sum(1 for t in tm if (t.get("status") in ("out", "doubtful"))),
                     "espn_only_out": any(t.get("source") == "espn" and t.get("status") in ("out", "doubtful") for t in tm),
                     "teammates_out": tm})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d = d[pd.to_datetime(d["generated_at"], utc=True) < pd.to_datetime(d["game_start"], utc=True)]
    return d.sort_values("generated_at").groupby(["key", "version"]).tail(1)


def _p_at(ladder: dict, line: float) -> float | None:
    pts = sorted((float(k), float(v)) for k, v in ladder.items() if k not in ("mean", "sd"))
    if not pts:
        return None
    lg = lambda p: math.log(min(max(p, EPS), 1 - EPS) / (1 - min(max(p, EPS), 1 - EPS)))  # noqa: E731
    if line <= pts[0][0]:
        return pts[0][1] if line == pts[0][0] else None
    if line >= pts[-1][0]:
        return pts[-1][1] if line == pts[-1][0] else None
    for (k0, p0), (k1, p1) in zip(pts, pts[1:]):
        if k0 <= line <= k1:
            z = lg(p0) + (lg(p1) - lg(p0)) * (line - k0) / (k1 - k0)
            return 1 / (1 + math.exp(-z))
    return None


def _ece(p, y, b=10) -> float:
    if len(p) == 0:
        return float("nan")
    i = np.clip((p * b).astype(int), 0, b - 1)
    return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))


def _ll(p, y) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(p) else float("nan")


def _metrics(g: pd.DataFrame) -> dict:
    """g: one version's graded rows (one per player-game-market)."""
    if g.empty:
        return {"n": 0}
    e = g["mean"] - g["actual"]
    o = {"n": int(len(g)), "bias_pct": round(float(100 * e.mean() / max(g["actual"].mean(), 1e-9)), 2), "mae": round(float(e.abs().mean()), 3),
         "rmse": round(float(np.sqrt((e ** 2).mean())), 3)}
    lp = np.array([pp for L in g["lad_p"] for pp in L]); ly = np.array([yy for L in g["lad_y"] for yy in L])
    k = (lp >= 0.02) & (lp <= 0.98)
    if k.any():
        o.update(ladder_ll=round(_ll(lp[k], ly[k]), 5), ladder_brier=round(float(np.mean((lp[k] - ly[k]) ** 2)), 5), ladder_ece=round(_ece(lp[k], ly[k]), 4))
    q = g.dropna(subset=["p_over"])
    if len(q):
        p, y = q["p_over"].to_numpy(float), q["y_over"].to_numpy(float)
        o.update(ou_n=int(len(q)), ou_ll=round(_ll(p, y), 5), ou_brier=round(float(np.mean((p - y) ** 2)), 5), ou_ece=round(_ece(p, y), 4),
                 pred_over=round(float(p.mean()), 4), actual_over=round(float(y.mean()), 4))
    m = g[g["market"] == "points"].dropna(subset=["proj_min"])
    if len(m):
        me = m["proj_min"] - m["minutes"]
        o.update(minutes_mae=round(float(me.abs().mean()), 3), minutes_bias=round(float(me.mean()), 3))
    return o


def build(pred: pd.DataFrame, box: pd.DataFrame, versions: tuple) -> dict:
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "versions": list(versions)}
    if pred.empty:
        return {**out, "player_games": 0}
    # identical games and pregame information: every version present, all from the same refresh
    w = pred.pivot_table(index="key", columns="version", values="generated_at", aggfunc="first")
    have = w.dropna(subset=[v for v in versions if v in w.columns]) if all(v in w.columns for v in versions) else w.iloc[0:0]
    same = have[have.nunique(axis=1) == 1].index
    out["coverage"] = {"player_games_any_version": int(len(w)), "all_versions_present": int(len(have)), "same_refresh": int(len(same))}
    d = pred[pred["key"].isin(same)]
    b = box.assign(game_id=lambda x: x["game_id"].astype(str), player_id=lambda x: x["player_id"].astype(str), game_date=lambda x: pd.to_datetime(x["game_date"]))
    b = b.sort_values("game_date")
    played = b[b["played"]]
    d = d.merge(played[["game_id", "player_id", "game_date", "minutes", "starter"] + sorted({m["stat"] for m in MARKETS.values()})], on=["game_id", "player_id"], how="inner")
    if d.empty:
        return {**out, "player_games": 0}
    # prior-only history per player: minutes band and the last-10 median line
    hist = {pid: g for pid, g in played.groupby("player_id")}
    # injury context from the first shadow candidate's record, applied to every version
    ref = d[d["version"] == versions[1]].set_index("key")[["status", "source", "conflict", "n_out", "espn_only_out"]] if len(versions) > 1 else None
    rows = []
    for r in d.itertuples():
        h = hist.get(r.player_id)
        prior = h[h["game_date"] < r.game_date] if h is not None else None
        m10 = float(prior["minutes"].tail(10).mean()) if prior is not None and len(prior) else np.nan
        cx = ref.loc[r.key] if ref is not None and r.key in ref.index else None
        for mk, m in MARKETS.items():
            pr = r.probabilities.get(mk) or {}
            if "mean" not in pr:
                continue
            y = float(getattr(r, m["stat"]))
            lad = [(float(k), float(v)) for k, v in pr.items() if k not in ("mean", "sd")]
            line = None
            if prior is not None and len(prior) >= 5:
                line = float(max(1, math.ceil(float(np.median(prior[m["stat"]].tail(10))))))
            p_over = _p_at(pr, line) if line is not None else None
            rows.append({"version": r.version, "key": r.key, "game_date": r.game_date, "market": mk, "mean": float(pr["mean"]), "actual": y,
                         "lad_p": [v for _, v in lad], "lad_y": [float(y >= k) for k, _ in lad], "p_over": p_over,
                         "y_over": float(y >= line) if line is not None else None, "proj_min": r.proj_min, "minutes": r.minutes,
                         "role": "starter" if bool(r.starter) else "bench",
                         "minutes_band": "<16" if not (m10 >= 16) else ("16-24" if m10 < 24 else ("24-30" if m10 < 30 else "30+")),
                         "status": (cx["status"] if cx is not None else None) or "not listed",
                         "status_source": (cx["source"] if cx is not None else None) or "none",
                         "n_out": "0" if cx is None or cx["n_out"] == 0 else ("1" if cx["n_out"] == 1 else "2+"),
                         "espn_only_teammate_out": bool(cx["espn_only_out"]) if cx is not None else False,
                         "conflict": bool(cx["conflict"]) if cx is not None else False})
    G = pd.DataFrame(rows)
    G["week"] = G["game_date"].dt.to_period("W-SUN").astype(str)
    out["player_games"] = int(G["key"].nunique())
    out["games"] = int(d["game_id"].nunique())
    out["first_game"], out["last_game"] = str(G["game_date"].min().date()), str(G["game_date"].max().date())

    def by(col=None, sub=None):
        S = G if sub is None else G[sub]
        if col is None:
            return {v: _metrics(S[S["version"] == v]) for v in versions}
        return {str(k): {v: _metrics(x[x["version"] == v]) for v in versions} for k, x in S.groupby(col) if len(x) >= len(versions) * 20}

    out["overall"] = by()
    out["by_week"] = by("week")
    out["by_market"] = by("market")
    out["by_role"] = by("role")
    out["by_minutes_band"] = by("minutes_band")
    out["by_injury_status"] = by("status")
    out["by_status_source"] = by("status_source")
    out["by_teammates_out"] = by("n_out")
    out["by_espn_only_teammate_out"] = by("espn_only_teammate_out")
    out["watch"] = {"bench_all_markets": by(None, G["role"] == "bench"), "blocks": by(None, G["market"] == "blocks"),
                    "questionable": by(None, G["status"] == "questionable"),
                    "over_under_by_market": {mk: {v: {kk: vv for kk, vv in _metrics(G[(G["market"] == mk) & (G["version"] == v)]).items() if kk.startswith(("ou_", "pred_", "actual_"))}
                                                  for v in versions} for mk in MARKETS}}
    # official report vs ESPN: how often a teammate ruled out by each source actually sat
    lab = []
    first = d[d["version"] == versions[1]] if len(versions) > 1 else d
    for r in first.drop_duplicates(["game_id", "team"]).itertuples():
        tb = b[(b["game_id"] == r.game_id) & (b["team"] == r.team)]
        names = {str(n).lower(): bool(p) for n, p in zip(tb["name"], tb["played"])}
        for t in r.teammates_out or []:
            if t.get("status") in ("out", "doubtful"):
                lab.append({"source": t.get("source") or "unknown", "played": names.get(str(t.get("name", "")).lower())})
    L = pd.DataFrame(lab)
    if len(L):
        out["teammate_out_accuracy_by_source"] = {s: {"listed_out": int(len(x)), "matched_in_box": int(x["played"].notna().sum()),
                                                      "played_anyway": int((x["played"] == True).sum())}  # noqa: E712
                                                  for s, x in L.groupby("source")}
    st = d[d["version"] == versions[1]] if len(versions) > 1 else d
    out["own_status_sources"] = {"official": int((st["source"] == "nba_official").sum()), "espn": int((st["source"] == "espn").sum()),
                                 "none": int(st["source"].isna().sum()), "conflicts": int(st["conflict"].notna().sum())}
    return out


def run() -> dict:
    from . import data

    versions = tuple(v.strip() for v in os.environ.get("MODELROOM_NBA_SHADOW_REPORT", ",".join((ACTIVE,) + SHADOWS)).split(",") if v.strip())
    pred = _load(ledger.read(ledger_path("nba_props")), versions)
    rep = build(pred, data.load(), versions)
    rep["note"] = ("Shadow evaluation on the test site: identical player-games, last pre-game record per version from the same refresh, "
                   "players who played. Nothing here is published to users; the ledger is read, never changed.")
    f = ledger_path("nba_props").parent / "reports" / "nba_props_shadow.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rep, indent=2, default=str))
    ov = rep.get("overall", {})
    return {"file": str(f), "player_games": rep.get("player_games", 0), "coverage": rep.get("coverage"),
            "overall": {v: {k: ov.get(v, {}).get(k) for k in ("bias_pct", "minutes_mae", "ladder_ll", "ladder_ece", "ou_ece")} for v in versions}}
