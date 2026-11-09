"""Per player-game history features known before kickoff: last-3 and season-to-date shares (games played),
games missed of the team's last 4, first-team-game flag. Strictly prior games only."""
import numpy as np, pandas as pd
from modelroom.nfl.props import inputs as I
from common import H
pg = I.load(set(range(2018, 2026))).player_games
pg = pg[pg.season >= 2020].copy()
pg["gd"] = pd.to_datetime(pg.game_date)
pg = pg.sort_values("gd")
pg["tsh"] = pg.targets / pg.team_pass_att.replace(0, np.nan)
pg["csh"] = pg.carries / pg.team_carries.replace(0, np.nan)
pg["played"] = (pg.offense_snaps.fillna(0) > 0) | (pg.targets + pg.carries > 0)
P = pg[pg.played]
g = P.groupby("player_id")
out = []
for k in (3,):
    for c in ("tsh", "csh", "offense_pct"):
        P[f"{c}_l{k}"] = g[c].transform(lambda s: s.shift(1).rolling(k, min_periods=1).mean())
P["tsh_szn"] = P.groupby(["player_id", "season"])["tsh"].transform(lambda s: s.shift(1).expanding().mean())
P["csh_szn"] = P.groupby(["player_id", "season"])["csh"].transform(lambda s: s.shift(1).expanding().mean())
P["n_szn"] = P.groupby(["player_id", "season"]).cumcount()
P["last_gd"] = g["gd"].shift(1)
feat = P[["player_id", "gd", "tsh_l3", "csh_l3", "offense_pct_l3", "tsh_szn", "csh_szn", "n_szn", "last_gd", "tsh", "csh", "offense_pct", "game_id", "season"]]
# For each candidate row we need the features as of the candidate's game: latest prior played game's rolling values
# INCLUDING that game -> recompute "as of after game" then asof-merge strictly before the target game date.
P["tsh_l3a"] = g["tsh"].transform(lambda s: s.rolling(3, min_periods=1).mean())
P["csh_l3a"] = g["csh"].transform(lambda s: s.rolling(3, min_periods=1).mean())
P["snap_l3a"] = g["offense_pct"].transform(lambda s: s.rolling(3, min_periods=1).mean())
P["tsh_szna"] = P.groupby(["player_id", "season"])["tsh"].transform(lambda s: s.expanding().mean())
P["csh_szna"] = P.groupby(["player_id", "season"])["csh"].transform(lambda s: s.expanding().mean())
P["n_szna"] = P.groupby(["player_id", "season"]).cumcount() + 1
A = P[["player_id", "gd", "season", "tsh_l3a", "csh_l3a", "snap_l3a", "tsh_szna", "csh_szna", "n_szna"]].rename(columns={"season": "h_season"}).sort_values("gd")
R = pd.concat([pd.read_pickle(H / f"data/rows_{s}.pkl") for s in range(2021, 2026)], ignore_index=True)[["game_id", "player_id", "season"]]
gdate = pg.drop_duplicates("game_id").set_index("game_id")["gd"]
R["gd"] = R.game_id.map(gdate)
R = R.dropna(subset=["gd"]).sort_values("gd")
M = pd.merge_asof(R, A, on="gd", by="player_id", allow_exact_matches=False, direction="backward")
same = M.h_season == M.season
for c in ("tsh_szna", "csh_szna"):
    M[c] = M[c].where(same)
M["n_szna"] = M.n_szna.where(same, 0)
M["days_since"] = (M.gd - M.groupby("player_id")["gd"].shift(0)).dt.days  # placeholder (0)
M[["game_id", "player_id", "tsh_l3a", "csh_l3a", "snap_l3a", "tsh_szna", "csh_szna", "n_szna"]].rename(
    columns={"tsh_l3a": "tsh_l3", "csh_l3a": "csh_l3", "snap_l3a": "snap_l3", "tsh_szna": "tsh_szn", "csh_szna": "csh_szn", "n_szna": "n_szn"}).to_pickle(H / "data/hist_feats.pkl")
print(M.notna().mean().round(3))
