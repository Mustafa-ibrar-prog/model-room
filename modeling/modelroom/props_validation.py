"""Prop validation by category (P4): how each NBA and NFL prop market has actually performed, active model and shadow
experiments reported separately.

Two kinds of evidence, never mixed:

  historical  the committed walk-forward backtest of a version (held-out test seasons), docs/models/results/
              <league>-props-backtest-<version>.json, exactly as recorded there.
  live        the append-only prediction ledger (read, never changed): each version's LAST record before the game for
              every player-game, graded against the box score, players who played only.

Per market and version (live): player-games, mean absolute error and bias of the projected average; Brier score, log
loss, calibration (10 bins) and calibration error over the stored ladder probabilities P(stat >= k) (rows of one
player-game are correlated, so these are descriptive, not independent samples); and Over/Under: at each player-game's
most balanced ladder line, where the model leaned (more than 3 points from 50%), how often that side happened against how
often the model said it would. Computed for everything graded ("all") and for the 14 days up to the latest graded game
("recent").

Minimum samples. Below them a figure is withheld (null) and the reason is given; nothing is extrapolated:
  MAE / bias                        100 player-games
  Brier / log loss / calibration    300 ladder rows
  a calibration bin                  30 rows
  Over/Under side                    50 player-games
No category is labelled "strong historical support": evidence labels are a separate, unapproved step (P5) and need
out-of-sample calibration evidence that live samples this small can't provide.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.paths import MODELING_ROOT, ledger_path

MIN_PLAYER_GAMES = 100
MIN_LADDER_ROWS = 300
MIN_BIN = 30
MIN_SIDE = 50
LEAN = 0.03
RECENT_DAYS = 14
EPS = 1e-6
SCHEMA = 1


def _ladder(probs: dict) -> list[tuple[float, float]]:
    out = []
    for k, v in (probs or {}).items():
        try:
            out.append((float(k), float(v)))
        except (TypeError, ValueError):
            continue  # "mean", "sd", "support"
    return out


def _pregame(recs: list[dict], id_field: str) -> pd.DataFrame:
    """Each version's last record before the game, per player-game (the ledger keeps every earlier record)."""
    rows = []
    for r in recs:
        if r.get("kind") != "player_props" or not r.get("model_version"):
            continue
        rows.append({"key": r["game_id"], "game_id": str(r.get(id_field)), "player_id": str(r["player_id"]), "version": r["model_version"],
                     "generated_at": r["generated_at"], "game_start": r["game_start"], "probabilities": r.get("probabilities") or {}})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d = d[pd.to_datetime(d["generated_at"], utc=True) < pd.to_datetime(d["game_start"], utc=True)]
    return d.sort_values("generated_at").groupby(["key", "version"]).tail(1)


def _graded(pred: pd.DataFrame, box: pd.DataFrame, markets: dict) -> pd.DataFrame:
    """One row per (version, player-game, market): projected mean, actual, ladder probabilities and outcomes."""
    if pred.empty:
        return pd.DataFrame()
    b = box.assign(game_id=box["game_id"].astype(str), player_id=box["player_id"].astype(str))
    d = pred.merge(b, on=["game_id", "player_id"], how="inner")
    rows = []
    for r in d.itertuples(index=False):
        rr = r._asdict()
        for mk, stat in markets.items():
            pr = r.probabilities.get(mk)
            if not pr or stat not in rr or rr[stat] is None or (isinstance(rr[stat], float) and math.isnan(rr[stat])):
                continue
            y = float(rr[stat])
            lad = _ladder(pr)
            rows.append({"version": r.version, "market": mk, "game_start": r.game_start, "mean": pr.get("mean"), "actual": y,
                         "p": [p for _, p in lad], "y": [float(y >= k) for k, _ in lad]})
    return pd.DataFrame(rows)


def _metrics(g: pd.DataFrame) -> dict:
    n = int(len(g))
    out: dict = {"player_games": n}
    m = g.dropna(subset=["mean"])
    if len(m) >= MIN_PLAYER_GAMES:
        e = m["mean"].astype(float) - m["actual"]
        out.update(mae=round(float(e.abs().mean()), 3), bias=round(float(e.mean()), 3),
                   bias_pct=round(float(100 * e.mean() / max(m["actual"].mean(), 1e-9)), 2),
                   mean_projected=round(float(m["mean"].mean()), 3), mean_actual=round(float(m["actual"].mean()), 3))
    else:
        out.update(mae=None, bias=None, bias_pct=None, withheld_mean=f"fewer than {MIN_PLAYER_GAMES} player-games")
    p = np.array([x for L in g["p"] for x in L], float)
    y = np.array([x for L in g["y"] for x in L], float)
    keep = (p >= 0.02) & (p <= 0.98)  # near-certain rungs say little and dominate counts
    p, y = p[keep], y[keep]
    out["ladder_rows"] = int(len(p))
    if len(p) >= MIN_LADDER_ROWS:
        pc = np.clip(p, EPS, 1 - EPS)
        idx = np.clip((p * 10).astype(int), 0, 9)
        bins = []
        ece = 0.0
        for b in range(10):
            k = idx == b
            if not k.any():
                continue
            ece += k.mean() * abs(p[k].mean() - y[k].mean())
            bins.append({"bin": f"{b / 10:.1f}-{(b + 1) / 10:.1f}", "n": int(k.sum()),
                         "predicted": round(float(p[k].mean()), 4) if k.sum() >= MIN_BIN else None,
                         "actual": round(float(y[k].mean()), 4) if k.sum() >= MIN_BIN else None})
        out.update(brier=round(float(np.mean((p - y) ** 2)), 5), log_loss=round(float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))), 5),
                   calibration_error=round(float(ece), 4), calibration=bins)
    else:
        out.update(brier=None, log_loss=None, calibration_error=None, calibration=None, withheld_ladder=f"fewer than {MIN_LADDER_ROWS} ladder rows")
    # Over/Under: one line per player-game, the ladder rung the model put closest to 50% (its own most balanced line;
    # there are no market lines to grade against). A lean = more than LEAN from 50%.
    mid = [min(zip(P, Y), key=lambda t: abs(t[0] - 0.5)) for P, Y in zip(g["p"], g["y"]) if len(P)]
    mid = [(a, b) for a, b in mid if 0.2 <= a <= 0.8]
    p = np.array([a for a, _ in mid], float)
    y = np.array([b for _, b in mid], float)
    ou = {"line": "the model's ladder rung closest to 50% for each player-game", "n": int(len(p))}
    for side, mask, pp, yy in (("over", p > 0.5 + LEAN, p, y), ("under", p < 0.5 - LEAN, 1 - p, 1 - y)):
        k = int(mask.sum())
        ou[side] = {"n": k, "predicted": round(float(pp[mask].mean()), 4) if k >= MIN_SIDE else None,
                    "hit_rate": round(float(yy[mask].mean()), 4) if k >= MIN_SIDE else None}
    out["over_under"] = ou
    return out


def live(league: str, pred: pd.DataFrame, box: pd.DataFrame, markets: dict) -> tuple[dict, dict]:
    g = _graded(pred, box, markets)
    if g.empty:
        return {}, {}
    starts = pd.to_datetime(g["game_start"], utc=True)
    last = starts.max()
    recent = g[starts >= last - pd.Timedelta(days=RECENT_DAYS)]
    out: dict = {}
    span: dict = {}
    for v, gv in g.groupby("version"):
        sv = pd.to_datetime(gv["game_start"], utc=True)
        span[v] = {"first_game": sv.min().isoformat(), "last_game": sv.max().isoformat()}
        out[v] = {}
        for mk in markets:
            a = gv[gv["market"] == mk]
            if a.empty:
                continue
            rv = recent[(recent["version"] == v) & (recent["market"] == mk)]
            out[v][mk] = {"all": _metrics(a), "recent": _metrics(rv) if len(rv) else {"player_games": 0}}
    return out, {"versions": span, "recent_window": {"days": RECENT_DAYS, "through": last.isoformat()}}


def historical(league: str, version: str) -> dict | None:
    f = MODELING_ROOT.parent / "docs" / "models" / "results" / f"{league}-props-backtest-{version}.json"
    if not f.exists():
        return None
    r = json.loads(f.read_text())
    t = r.get("test") or {}
    mk = {}
    for k, v in (t.get("markets") or {}).items():
        mp = v.get("mean_projection") or {}
        base = (v.get("baseline_same_rows") or {}).get("baseline") or {}
        mk[k] = {"ladder_rows": (v.get("model") or {}).get("n"), "brier": (v.get("model") or {}).get("brier"),
                 "log_loss": (v.get("model") or {}).get("log_loss"), "baseline_log_loss": base.get("log_loss"),
                 "calibration_error": v.get("ece"), "calibration": v.get("calibration"),
                 "player_games": mp.get("n"), "mae": mp.get("model_mae"), "bias": mp.get("model_bias"), "recent_form_mae": mp.get("recent_avg_mae")}
    return {"version": r.get("model_version", version), "test_seasons": r.get("test_seasons"), "generated_at": r.get("generated_at"),
            "source": f"docs/models/results/{f.name}", "markets": mk}


def build(league: str, pred: pd.DataFrame, box: pd.DataFrame, markets: dict, active: str, shadows: list[str],
          labels: dict | None = None, history_for: dict | None = None) -> dict:
    """labels: market key -> display label. history_for: version -> backtest version to show (with a note) when a
    version has no backtest of its own."""
    lv, meta = live(league, pred, box, markets)
    versions = sorted(set(lv) | {active} | set(shadows), key=lambda v: (v != active, v not in shadows, v))
    out = {"schema": SCHEMA, "league": league, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "active": active, "shadows": shadows, "markets": labels or {k: k for k in markets},
           "rules": {"min_player_games": MIN_PLAYER_GAMES, "min_ladder_rows": MIN_LADDER_ROWS, "min_bin": MIN_BIN, "min_side": MIN_SIDE,
                     "lean": LEAN, "recent_days": RECENT_DAYS, "ladder_probability_range": [0.02, 0.98]},
           "evidence_labels": {"strong_historical_support": "not awarded",
                               "note": "Evidence labels on cards (P5) are not approved; no category is labelled strong."},
           "recent_window": meta.get("recent_window"), "versions": {}}
    for v in versions:
        role = "active" if v == active else "shadow" if v in shadows else "previous"
        h = historical(league, v)
        hnote = None
        if h is None and history_for and v in history_for:
            h = historical(league, history_for[v])
            hnote = history_for.get(f"{v}:note")
        out["versions"][v] = {"role": role, "live": lv.get(v, {}), "live_span": (meta.get("versions") or {}).get(v),
                              "historical": h, "historical_note": hnote}
    return out


# ------------------------------------------------------------------ per league
def nba(env=os.environ) -> dict:
    from modelroom.nba.props import data
    from modelroom.nba.props.config import MARKETS

    main = ledger_path("nba_props")
    recs = ledger.read(main) if main.exists() else []
    for f in sorted(main.parent.glob("nba_props_shadow_*.jsonl")):
        recs += ledger.read(f)
    pred = _pregame(recs, "nba_game_id")
    box = data.load()
    box = box[box["played"].astype(bool)] if "played" in box else box
    active = env.get("MODELROOM_NBA_PROPS_VERSION", "").strip() or "0.1.0"
    shadows = [v.strip() for v in env.get("MODELROOM_NBA_PROPS_SHADOW", "").split(",") if v.strip()]
    markets = {k: m["stat"] for k, m in MARKETS.items()}
    labels = {k: m.get("label", k) for k, m in MARKETS.items()}
    return build("nba", pred, box, markets, active, shadows, labels)


def nfl(env=os.environ) -> dict:
    from modelroom.nfl import player_data
    from modelroom.nfl.props.config import MARKETS

    pred = _pregame(ledger.read_series(ledger_path("nfl_props")), "nfl_game_id")
    pg, _, _ = player_data.load()
    pg = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
    pg = pg.assign(rush_rec_yds=pg["rush_yds"] + pg["rec_yds"], td_any=pg["rush_td"] + pg["rec_td"])
    if "fantasy_ppr" not in pg:
        pg = pg.assign(fantasy_ppr=0.04 * pg["pass_yds"] + 4 * pg["pass_td"] - 2 * pg["ints"] + 0.1 * pg["rush_yds"] + 6 * pg["rush_td"]
                       + pg["receptions"] + 0.1 * pg["rec_yds"] + 6 * pg["rec_td"])
    box = pg.drop_duplicates(["game_id", "player_id"])
    active = env.get("MODELROOM_NFL_PROPS_VERSION", "").strip() or "0.1.0"
    shadows = [v.strip() for v in env.get("MODELROOM_NFL_PROPS_SHADOW", "").split(",") if v.strip()]
    markets = {k: m["stat"] for k, m in MARKETS.items()}
    labels = {k: m.get("label", k) for k, m in MARKETS.items()}
    # 0.1.1 / 0.1.3 have no backtest file of their own; 0.1.0's held-out backtest is shown, labelled as 0.1.0's.
    hist = {"0.1.1": "0.1.0", "0.1.1:note": "0.1.0's backtest: 0.1.1 is 0.1.0's share and efficiency model and calibration plus the live "
            "injury feed and the inexperienced-QB factor, which the backtest does not include.",
            "0.1.3": "0.1.0", "0.1.3:note": "0.1.0's backtest, for reference: 0.1.3 (0.1.1 + RB/TE share concentration) is a shadow experiment "
            "evaluated in the research replay, not this backtest."}
    return build("nfl", pred, box, markets, active, shadows, labels, hist)


def attach(league: str, report: dict) -> dict:
    """Adds the validation report to a props-monitor report (published with it). A failure is recorded, never raised:
    the monitor and the refresh never depend on it."""
    try:
        report["validation"] = nba() if league == "nba" else nfl()
    except Exception as e:  # noqa: BLE001
        report["validation"] = {"schema": SCHEMA, "league": league, "error": f"{type(e).__name__}: {e}"[:300]}
    return report
