"""Like collect.py but only the share inputs when fill-in games count for less (feature setting fill_in_weight=W):
target_share_role / carry_share_role per candidate. Research only."""
import sys
from dataclasses import replace
from pathlib import Path
import pandas as pd
from modelroom.nfl.props import backtest as B, inputs as I, model as M
from modelroom.nfl.props.config import PropParams
W = float(sys.argv[1]); seasons = [int(x) for x in sys.argv[2:]]
p = PropParams.load(Path("/home/claude/model-room/modeling/modelroom/nfl/props/params_0.1.1.json"))
s = replace(p.settings, fill_in_weight=W)
inp = I.load(set(range(min(seasons) - 3, max(seasons) + 1)))
run = B.Runner(inp)
rows = []
for season, week, g in B._weeks(inp.games, seasons):
    ctx = run.ctx(pd.Timestamp(g["game_date"].min()), season, s, week)
    P = ctx.players
    for _, gm in g.iterrows():
        for team in (gm["home_team"], gm["away_team"]):
            ids = P.index[P["team_last"] == team]
            for pid in ids:
                rows.append((season, gm["game_id"], pid, P.at[pid, "target_share_role"], P.at[pid, "carry_share_role"]))
    print(season, week, len(rows), flush=True)
pd.DataFrame(rows, columns=["season", "game_id", "player_id", "tsh_fi", "csh_fi"]).drop_duplicates(["game_id", "player_id"]).to_pickle(
    Path(__file__).with_name("data") / f"fillin_{W}_{'_'.join(map(str, seasons))}.pkl")
print("saved")
