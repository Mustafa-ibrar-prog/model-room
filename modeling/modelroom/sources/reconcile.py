"""Cross-source reconciliation.

Conflicts are reported, never silently overwritten. When a conflict needs a
decision, the registry priority applies (official league records first, then
the lower priority number). A confirmed correction goes in
data/corrections/<league>_scores.csv with the source that justifies it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from modelroom.common.paths import ensure, output_dir, processed_dir

from . import land_of_basketball

# hoopR (ESPN) display name -> Land of Basketball name, where they differ.
NBA_NAME_ALIASES = {"LA Clippers": "Los Angeles Clippers"}


def nba_scores() -> dict:
    games = pd.read_parquet(processed_dir("nba") / "games.parquet")
    lob = land_of_basketball.load_snapshots()
    if lob.empty:
        return {"compared": 0, "note": "No Land of Basketball snapshots. Run: python -m modelroom nba crosscheck"}

    hoopr = games[games["has_box"]].copy()
    hoopr["home_key"] = hoopr["home_name"].replace(NBA_NAME_ALIASES)
    hoopr["away_key"] = hoopr["away_name"].replace(NBA_NAME_ALIASES)
    in_range = hoopr[(hoopr["game_date"] >= lob["game_date"].min()) & (hoopr["game_date"] <= lob["game_date"].max())]

    m = in_range.merge(
        lob, left_on=["game_date", "home_key", "away_key"], right_on=["game_date", "home_team", "away_team"],
        how="outer", indicator=True, suffixes=("_hoopr", "_lob"),
    )
    both = m[m["_merge"] == "both"]
    diff = both[(both["home_score_hoopr"] != both["home_score_lob"]) | (both["away_score_hoopr"] != both["away_score_lob"])]
    ot_hoopr = both["periods"] > 4
    ot_lob = both["overtime"].notna()
    ot_diff = both[ot_hoopr != ot_lob]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": ["hoopr_schedule", "land_of_basketball"],
        "date_range": [str(lob["game_date"].min()), str(lob["game_date"].max())],
        "compared": int(len(both)),
        "score_mismatches": diff[["game_id", "game_date", "away_key", "home_key", "away_score_hoopr", "home_score_hoopr",
                                  "away_score_lob", "home_score_lob"]].astype(str).to_dict("records"),
        "overtime_mismatches": int(len(ot_diff)),
        "only_in_hoopr": m.loc[m["_merge"] == "left_only", ["game_id", "game_date", "away_key", "home_key"]].astype(str).to_dict("records"),
        "only_in_land_of_basketball": m.loc[m["_merge"] == "right_only", ["game_date", "away_team", "home_team"]].astype(str).to_dict("records"),
    }
    report["ok"] = not report["score_mismatches"] and not report["only_in_hoopr"] and not report["only_in_land_of_basketball"] and report["overtime_mismatches"] == 0
    out = ensure(output_dir("validation"))
    (out / "reconcile_nba_scores.json").write_text(json.dumps(report, indent=2))
    return report
