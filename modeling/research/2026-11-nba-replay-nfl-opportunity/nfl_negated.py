"""Do targets wiped out by penalties (no_play rows; nflfastR clears the player ids) carry usage signal?
Recover them from the play description, then compare prior-8-game target share with vs without them as a
predictor of next-game official target share (walk-forward by season; prior games only)."""
import re, json, numpy as np, pandas as pd
D = "/home/claude/model-room/modeling/data/"
cols = ["game_id", "play_id", "season", "week", "season_type", "posteam", "play_type", "desc", "receiver_player_id", "receiver_player_name", "pass_attempt", "sack", "two_point_attempt"]
P = pd.concat([pd.read_parquet(D + f"raw/nfl/play_by_play_{s}.parquet", columns=cols) for s in range(2021, 2026)], ignore_index=True)
P = P[P.season_type == "REG"]
off = P[(P.play_type == "pass") & P.receiver_player_id.notna() & (P.two_point_attempt != 1)]
name_id = off.groupby(["season", "posteam", "receiver_player_name"])["receiver_player_id"].agg(lambda s: s.mode().iat[0]).to_dict()
neg = P[(P.play_type == "no_play") & P.desc.str.contains(r"\bpass\b", na=False) & ~P.desc.str.contains("Two-Point|TWO-POINT", case=False, na=False)].copy()
m = neg.desc.str.extract(r"\bpass (?:incomplete )?(?:short|deep)? ?(?:left|right|middle)? ?(?:to|intended for) \d+-([A-Z][A-Za-z'\-]*\.[A-Za-z'\-\.]+?)(?=[\s\.,(]|$)")
neg["rname"] = m[0].str.strip()
neg["rid"] = [name_id.get((s, t, n)) for s, t, n in zip(neg.season, neg.posteam, neg.rname)]
print("no_play pass rows", len(neg), "receiver recovered", int(neg.rid.notna().sum()))
o = off.groupby(["season", "week", "game_id", "posteam", "receiver_player_id"]).size().rename("tgt").reset_index()
n = neg.dropna(subset=["rid"]).groupby(["season", "week", "game_id", "posteam", "rid"]).size().rename("ntgt").reset_index().rename(columns={"rid": "receiver_player_id"})
team = off.groupby(["game_id", "posteam"]).size().rename("team_tgt").reset_index()
tneg = neg.groupby(["game_id", "posteam"]).size().rename("team_ntgt").reset_index()
g = o.merge(n, how="outer", on=["season", "week", "game_id", "posteam", "receiver_player_id"]).merge(team, on=["game_id", "posteam"], how="left").merge(tneg, on=["game_id", "posteam"], how="left").fillna({"tgt": 0, "ntgt": 0, "team_ntgt": 0})
g = g.dropna(subset=["team_tgt"]).sort_values(["season", "week"])
gg = g.groupby(["receiver_player_id"])
for c in ("tgt", "ntgt", "team_tgt", "team_ntgt"):
    g["p_" + c] = gg[c].transform(lambda s: s.shift(1).rolling(8, min_periods=3).sum())
g = g.dropna(subset=["p_tgt"])
g["sh_off"] = g.p_tgt / g.p_team_tgt
g["sh_all"] = (g.p_tgt + g.p_ntgt) / (g.p_team_tgt + g.p_team_ntgt)
# level-matched: rescale so the average share equals the official share's average (removes the denominator artefact)
g["sh_all"] = g["sh_all"] * (g["sh_off"].mean() / g["sh_all"].mean())
g["act_sh"] = g.tgt / g.team_tgt
out = {}
for s in (2023, 2024, 2025):
    t = g[g.season == s]
    e1 = (t.sh_off - t.act_sh) * t.team_tgt; e2 = (t.sh_all - t.act_sh) * t.team_tgt
    out[s] = {"n": int(len(t)), "mae_official": round(float(e1.abs().mean()), 4), "mae_with_negated": round(float(e2.abs().mean()), 4),
              "rmse_official": round(float(np.sqrt((e1 ** 2).mean())), 4), "rmse_with_negated": round(float(np.sqrt((e2 ** 2).mean())), 4)}
out["negated_targets_per_team_season"] = round(float(neg.groupby(["season", "posteam"]).size().mean()), 1)
print(json.dumps(out, indent=1)); json.dump(out, open("/tmp/claude-0/s/audit/nfl_negated.json", "w"), indent=1)
