"""Evidence builder (TEST, Moose 2026-11-28): defense vs position ranks, last 15, splits, strict JSON."""
import json

import numpy as np
import pandas as pd

from modelroom import evidence as E


def _pg():
    rows = []
    for t, base in (("AAA", 10), ("BBB", 14), ("CCC", 12)):
        for g in range(8):
            for grp, mult in (("G", 1), ("C", 2)):
                rows.append({"game_id": f"{t}{g}", "opp": t, "team": "X", "group": grp, "reb": base * mult / 2, "pts": 20.0})
    return pd.DataFrame(rows)


def test_defense_ranks_most_allowed_first_and_needs_enough_games():
    d = E.defense(_pg(), {"rebounds": "reb"}, "group", ("G", "C"), "team", "opp")
    assert d["BBB"]["C"]["rebounds"]["rank"] == 1 and d["AAA"]["C"]["rebounds"]["rank"] == 3
    assert d["BBB"]["C"]["rebounds"]["allowed"] == 14.0 and d["BBB"]["C"]["rebounds"]["games"] == 8
    few = _pg()[lambda x: ~x["game_id"].isin([f"CCC{i}" for i in range(4)])]
    assert "CCC" not in E.defense(few, {"rebounds": "reb"}, "group", ("G",), "team", "opp")


def test_player_block_last15_splits_and_usage():
    n = 20
    h = pd.DataFrame({"game_date": pd.date_range("2026-10-01", periods=n), "opp": "Z", "is_home": [i % 2 == 0 for i in range(n)],
                      "pts": np.arange(n, dtype=float), "minutes": np.r_[np.full(15, 30.0), np.full(5, 36.0)]})
    b = E.player_block(h, {"points": "pts"}, {"minutes": "minutes"}, "is_home")
    assert len(b["values"]["points"]) == 15 and b["values"]["points"][0] == 19.0      # newest first
    assert b["splits"]["home_games"] == 10 and b["splits"]["points"]["home"] == 9.0
    assert b["usage"]["minutes"]["last5"] == 36.0 and b["usage"]["minutes"]["season"] == 31.5


def test_no_split_on_small_samples_and_strict_json():
    h = pd.DataFrame({"game_date": pd.date_range("2026-10-01", periods=6), "opp": "Z", "is_home": [True] * 5 + [False], "pts": [1.0, np.nan, 3, 4, 5, 6]})
    b = E.player_block(h, {"points": "pts"}, {}, "is_home")
    assert b["splits"] is None
    s = E.dumps({"x": b, "y": float("nan"), "z": np.int64(3)})
    assert "NaN" not in s and json.loads(s)["z"] == 3
