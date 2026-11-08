"""Lookahead / timing checks for the historical-report replay."""
import json, pandas as pd
from pathlib import Path
from modelroom.nba.props import inputs as I
from modelroom.audit import hist_reports as H
inp = I.load()
P = Path("/tmp/claude-0/s/probe")
R, F = H.load([P / "hist", P / "hist2", P / "hist3"])
g = inp.games[(inp.games.status == "final") & inp.games.season.isin([2024, 2025, 2026])].copy()
g["slot"] = g.start_time.map(H.slot_of)
g["tip"] = pd.to_datetime(g.start_time, utc=True)
out = {}
# 1. every report row used: its publication time vs that game's tip
R["rt"] = pd.to_datetime(R.report_time, utc=True)
m = R.merge(g[["game_id", "season", "game_date", "home_abbr", "away_abbr", "slot", "tip"]].melt(id_vars=["game_id", "season", "game_date", "slot", "tip"], value_name="team").drop(columns="variable").assign(game_date=lambda d: d.game_date.astype(str)),
            left_on=["target_slot", "game_date", "team"], right_on=["slot", "game_date", "team"], how="inner")
lead = (m.tip - m.rt).dt.total_seconds() / 60
out["rows_used"] = int(len(m))
out["rows_published_after_tip_minus_30"] = int((lead < 30).sum())
out["minutes_before_tip"] = {"min": round(float(lead.min()), 1), "p10": round(float(lead.quantile(.1)), 1), "median": round(float(lead.median()), 1), "p90": round(float(lead.quantile(.9)), 1)}
out["slot_fallbacks_used"] = {"same_slot": int((m.rt == pd.to_datetime(m.target_slot, utc=True)).sum()), "earlier_slot": int((m.rt < pd.to_datetime(m.target_slot, utc=True)).sum()),
                              "later_than_slot": int((m.rt > pd.to_datetime(m.target_slot, utc=True)).sum())}
# 2. rows whose stated game date isn't the game's date can't be matched (date is part of the key) -> count rows of the slot for other dates
out["report_rows_for_other_dates_ignored"] = int((~R.set_index(["target_slot", "game_date", "team"]).index.isin(m.set_index(["target_slot", "game_date", "team"]).index)).sum())
# 3. coverage by season
cov = {}
for s, d in g.groupby("season"):
    keys = {(r.slot, str(r.game_date), t) for r in d.itertuples() for t in (r.home_abbr, r.away_abbr)}
    fk = set(zip(F.target_slot, F.game_date.astype(str), F.team))
    cov[int(s)] = {"team_games": len(keys), "with_report": len(keys & fk), "share": round(len(keys & fk) / len(keys), 4)}
out["coverage"] = cov
# 4. spot check: a known case printed for eyeballing
ex = m.sort_values("rt").groupby("season").head(2)[["season", "game_date", "team", "player", "status", "report_time", "tip"]]
out["examples"] = ex.astype(str).to_dict("records")
print(json.dumps(out, indent=1)); json.dump(out, open("/tmp/claude-0/s/audit/timing_check.json", "w"), indent=1)
