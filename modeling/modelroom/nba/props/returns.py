"""Minutes in a player's first games back after an absence, measured on box scores.

    python -m modelroom.nba.props.returns      → prints the fit (2016-22) and held-out (2023+) numbers

"Back" = playing after missing 3+ straight team games, for players averaging 20+ minutes over their 10
games before the absence. Measured: minutes in game k back ÷ that pre-absence average, and the spread of
(minutes − average) relative to the same spread in ordinary games. 0.2.1 uses the fit-season values.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_MISSED = 3
GAMES_BACK = 3


def games_back(b: pd.DataFrame) -> pd.DataFrame:
    """One row per played game: player_id, game_id, season, prior (pre-absence 10-game avg), minutes, back (0 = not
    within GAMES_BACK games of a 3+ game absence, else 1..GAMES_BACK)."""
    b = b.sort_values(["player_id", "game_date"])
    rows = []
    for pid, x in b.groupby("player_id"):
        pl, mn, gid, ss = x["played"].to_numpy(bool), x["minutes"].to_numpy(float), x["game_id"].to_numpy(), x["season"].to_numpy()
        run, hist, since = 0, [], 99
        for i in range(len(x)):
            if not pl[i]:
                run += 1
                continue
            since = 1 if run >= MIN_MISSED else since + 1
            if len(hist) >= 5:
                rows.append((pid, gid[i], ss[i], float(np.mean(hist[-10:])), mn[i], since if since <= GAMES_BACK else 0))
            hist.append(mn[i])
            run = 0
    return pd.DataFrame(rows, columns=["player_id", "game_id", "season", "prior", "minutes", "back"])


def current_back(b: pd.DataFrame, player_ids) -> dict:
    """Games already played since each player's last 3+ game absence (0 if none within GAMES_BACK)."""
    out = {}
    b = b[b["player_id"].astype(str).isin({str(p) for p in player_ids})].sort_values(["player_id", "game_date"])
    for pid, x in b.groupby("player_id"):
        pl = x["played"].to_numpy(bool)
        run, since = 0, 99
        for v in pl:
            if not v:
                run += 1
                continue
            since = 1 if run >= MIN_MISSED else since + 1
            run = 0
        out[str(pid)] = since if since < GAMES_BACK else 99
    return out


def measure(b: pd.DataFrame, seasons) -> dict:
    d = games_back(b)
    d = d[d["season"].isin(list(seasons)) & (d["prior"] >= 20)]
    normal = d[d["back"] == 0]
    sd0 = float((normal["minutes"] - normal["prior"]).std())
    ratio0 = float((normal["minutes"] / normal["prior"]).mean())
    out = {"n_normal": len(normal), "normal_ratio": round(ratio0, 3), "normal_sd": round(sd0, 2), "by_game_back": {}}
    for k in range(1, GAMES_BACK + 1):
        x = d[d["back"] == k]
        out["by_game_back"][k] = {"n": len(x), "minutes_ratio": round(float((x["minutes"] / x["prior"]).mean() / ratio0), 3),
                                  "sd_factor": round(float((x["minutes"] - x["prior"]).std()) / sd0, 3)}
    return out


if __name__ == "__main__":
    import json

    from . import data

    b = data.load()
    print(json.dumps({"fit_2016_2022": measure(b, range(2016, 2023)), "test_2023_on": measure(b, range(2023, 2030))}, indent=1))
