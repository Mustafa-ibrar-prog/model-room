"""Shared loading for the allocation research (read-only)."""
from pathlib import Path
import numpy as np, pandas as pd
H = Path(__file__).parent
SK = ["RB", "WR", "TE"]

def load():
    R = pd.concat([pd.read_pickle(H / f"data/rows_{s}.pkl") for s in range(2021, 2026)], ignore_index=True)
    f = H / "data/team_actual.pkl"
    if not f.exists():
        from modelroom.nfl.props import inputs as I
        pg = I.load(set(range(2018, 2026))).player_games
        t = pg.drop_duplicates(["game_id", "team"])[["game_id", "team", "team_pass_att", "team_carries"]]
        t.to_pickle(f)
    t = pd.read_pickle(f)
    R = R.merge(t, on=["game_id", "team"], how="left")
    # Player history features computed from player_games strictly before the game week.
    f2 = H / "data/hist_feats.pkl"
    if f2.exists():
        R = R.merge(pd.read_pickle(f2), on=["game_id", "player_id"], how="left")
    return R
