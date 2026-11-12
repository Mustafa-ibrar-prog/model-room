"""P4: per-category validation. SYNTHETIC ledger records and box scores."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modelroom import props_validation as V


def _recs(n: int, version: str, start: str = "2030-01-01", mean: float = 10.0, game_offset: int = 0):
    out = []
    for i in range(n):
        gs = (pd.Timestamp(start, tz="UTC") + pd.Timedelta(hours=i)).isoformat()
        gid = f"g{i + game_offset}"
        probs = {"points": {"5": 0.9, "10": 0.5, "15": 0.1, "mean": mean, "sd": 3.0}}
        # an earlier record and the pre-game one: only the last before the game counts
        out.append({"kind": "player_props", "game_id": f"{gid}|p", "nba_game_id": gid, "player_id": "p", "model_version": version,
                    "generated_at": (pd.Timestamp(gs) - pd.Timedelta(hours=5)).isoformat(), "game_start": gs,
                    "probabilities": {"points": {"5": 0.1, "10": 0.1, "15": 0.1, "mean": 99.0}}})
        out.append({"kind": "player_props", "game_id": f"{gid}|p", "nba_game_id": gid, "player_id": "p", "model_version": version,
                    "generated_at": (pd.Timestamp(gs) - pd.Timedelta(hours=1)).isoformat(), "game_start": gs, "probabilities": probs})
        # recorded after the game started: never graded
        out.append({"kind": "player_props", "game_id": f"{gid}|p", "nba_game_id": gid, "player_id": "p", "model_version": version,
                    "generated_at": (pd.Timestamp(gs) + pd.Timedelta(hours=1)).isoformat(), "game_start": gs,
                    "probabilities": {"points": {"5": 0.0, "10": 0.0, "15": 0.0, "mean": 0.0}}})
    return out


def _box(n: int, offset: int = 0):
    rng = np.random.default_rng(0)
    return pd.DataFrame({"game_id": [f"g{i + offset}" for i in range(n)], "player_id": "p", "pts": rng.integers(4, 17, n).astype(float)})


def test_uses_the_last_pregame_record_and_reports_versions_separately():
    pred = V._pregame(_recs(150, "1.0") + _recs(20, "2.0"), "nba_game_id")
    rep = V.build("nba", pred, _box(150), {"points": "pts"}, active="1.0", shadows=["2.0"])
    a = rep["versions"]["1.0"]["live"]["points"]["all"]
    assert rep["versions"]["1.0"]["role"] == "active" and rep["versions"]["2.0"]["role"] == "shadow"
    assert a["player_games"] == 150
    box = _box(150)
    assert a["bias"] == round(float(10.0 - box["pts"].mean()), 3)  # the pre-game mean (10), not 99 or 0
    assert a["mae"] is not None and a["log_loss"] is not None and a["calibration"]
    # the shadow has 20 player-games: figures withheld, with the reason
    s = rep["versions"]["2.0"]["live"]["points"]["all"]
    assert s["player_games"] == 20 and s["mae"] is None and "fewer than 100" in s["withheld_mean"]
    assert s["log_loss"] is None and s["withheld_ladder"]


def test_over_under_at_the_balanced_line_and_no_strong_label():
    pred = V._pregame(_recs(150, "1.0"), "nba_game_id")
    rep = V.build("nba", pred, _box(150), {"points": "pts"}, active="1.0", shadows=[])
    ou = rep["versions"]["1.0"]["live"]["points"]["all"]["over_under"]
    # every player-game's most balanced rung is 10 at exactly 50%: no lean either way
    assert ou["n"] == 150 and ou["over"]["n"] == 0 and ou["under"]["n"] == 0
    assert rep["evidence_labels"]["strong_historical_support"] == "not awarded"


def test_recent_window_and_missing_backtest():
    pred = V._pregame(_recs(150, "1.0", start="2030-01-01") + _recs(150, "1.0", start="2030-03-01", game_offset=1000), "nba_game_id")
    box = pd.concat([_box(150), _box(150, offset=1000)])
    rep = V.build("nba", pred, box, {"points": "pts"}, active="1.0", shadows=[])
    v = rep["versions"]["1.0"]
    assert v["live"]["points"]["all"]["player_games"] == 300
    assert v["live"]["points"]["recent"]["player_games"] == 150  # 14 days up to the latest graded game
    assert v["historical"] is None  # no backtest file for a made-up version


def test_historical_reads_the_committed_backtest():
    h = V.historical("nba", "0.2.0")
    assert h is not None and h["version"] == "0.2.0" and "points" in h["markets"]
    assert h["markets"]["points"]["player_games"] > 1000
