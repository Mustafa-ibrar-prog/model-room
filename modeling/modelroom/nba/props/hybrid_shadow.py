"""Forward shadow record for the NBA props hybrid (TEST, Moose 2026-11-28). Never published, never read by the site.

At each refresh, for every player and stat on the published NBA props board (active 0.2.0): the ORIGINAL probability
at K = ceil(median of his last 10) read from the board's own calibrated grid, the same pre-game evidence numbers the
historical evaluation uses (hybrid_eval.features), and, when a fitted coefficient file exists, the HYBRID probability.
Both go to preview-ledger/nba_props_hybrid_shadow_<week>.jsonl (hash-chained, append-only) so the two can be graded
against box scores on identical player-games, chronologically. Without coefficients only the original and the
evidence are recorded (p_hybrid null). Nothing here changes a prediction anyone sees.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.paths import ledger_path

from . import hybrid_eval as H
from .config import MARKETS

ROOT = Path(__file__).resolve().parents[3]
COEF = Path(__file__).resolve().parent / "hybrid_coef.json"
VERSION = "hybrid-shadow-1"


def grid_p(m: dict, k: float) -> float | None:
    g = m.get("grid")
    if not g or not g.get("p"):
        return None
    i = (k - g["k0"]) / g["step"]
    if abs(i - round(i)) > 1e-9 or not 0 <= round(i) < len(g["p"]):
        return None
    return float(g["p"][int(round(i))])


def run(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    board = json.loads((ROOT / "data" / "published" / "nba_props.json").read_text())
    coef = json.loads(COEF.read_text()) if COEF.exists() else None
    beta = np.array(coef["beta"]) if coef else None
    coef_hash = hashlib.sha256(json.dumps(coef, sort_keys=True).encode()).hexdigest()[:16] if coef else None
    pg = pd.read_parquet(ROOT / "data" / "processed" / "nba" / "prop_player_games.parquet")
    pg = pg[pg["played"].astype(bool)].copy()
    pg["player_id"] = pg["player_id"].astype(str)
    pg["gd"] = pd.to_datetime(pg["game_date"])
    pg["is_home"] = pg["is_home"].astype(bool)
    season = int(board["season"])
    this = pg[pg["season"] == season]
    dz = H.defense_table(this)
    gm = pd.read_parquet(ROOT / "data" / "processed" / "nba" / "games.parquet") if (ROOT / "data" / "processed" / "nba" / "games.parquet").exists() else None
    gi = gm.assign(game_id=gm["game_id"].astype(str)).set_index("game_id") if gm is not None else None
    recs = []
    for g in board["games"]:
        start = g.get("start_time")
        if not start or pd.Timestamp(start) <= pd.Timestamp(now):
            continue
        row = gi.loc[str(g["game_id"])] if gi is not None and str(g["game_id"]) in gi.index else None
        for pl in g["players"]:
            h = pg[pg["player_id"] == str(pl["player_id"])].sort_values("gd", ascending=False)
            if len(h) < 5:
                continue
            home = pl["team"] == g["home"]["abbr"]
            b2b = bool(row["home_b2b" if home else "away_b2b"]) if row is not None and "home_b2b" in row else False
            margin = float(row["proj_margin"]) if row is not None and "proj_margin" in row and pd.notna(row["proj_margin"]) else 0.0
            grp = (pl.get("position") or "?")[0]
            for mk, m in pl["markets"].items():
                st = MARKETS.get(mk, {}).get("stat")
                if not st or st not in h:
                    continue
                K = float(max(1, math.ceil(float(np.median(h.head(10)[st])))))
                p = grid_p(m, K)
                if p is None or not 0.03 <= p <= 0.97:
                    continue
                f = H.features(h, h[h["season"] == season], K, st, p, home, b2b, margin, dz.get((pl["opp"], grp)))
                ph = float(H.adjust(np.array([p]), np.array([[f[k] for k in H.FEATURES]]), beta)[0]) if beta is not None else None
                body = {"K": K, "p": round(p, 4), "features": {k: round(v, 4) for k, v in f.items()}, "coef": coef_hash}
                recs.append({"game_id": f"{g['game_id']}|{pl['player_id']}|{mk}", "model_version": VERSION,
                             "inputs_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16], "params_hash": coef_hash,
                             "generated_at": now.isoformat(timespec="seconds"), "game_start": pd.Timestamp(start).isoformat(),
                             "nba_game_id": str(g["game_id"]), "player_id": str(pl["player_id"]), "market": mk, "active_version": board.get("model", {}).get("version"),
                             "board_generated_at": board.get("generated_at"), "p_original": round(p, 4),
                             "p_hybrid": None if ph is None else round(ph, 4), **body})
    res = ledger.append_weekly(ledger_path("nba_props_hybrid_shadow"), now, recs)
    return {"candidates": len(recs), "appended": res.appended, "duplicates": res.skipped_duplicate, "coefficients": bool(coef)}


if __name__ == "__main__":
    print(json.dumps(run()))
