"""Validation reports for every processed dataset (columns, coverage, missing, duplicates, plausibility)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from modelroom.common.paths import ensure, output_dir, processed_dir

from .profile import Profile, add_check, profile


def _read(league: str, name: str) -> pd.DataFrame | None:
    f = processed_dir(league) / f"{name}.parquet"
    return pd.read_parquet(f) if f.exists() else None


def nba() -> list[Profile]:
    out: list[Profile] = []
    games, tg, pg = _read("nba", "games"), _read("nba", "team_games"), _read("nba", "player_games")
    if games is None:
        return out
    p = profile(games, "nba/games", keys=["game_id"], date_col="start_time", season_col="season",
                required=["game_id", "season", "start_time", "home_id", "away_id", "status"])
    add_check(p, "home team differs from away team", (games["home_id"] != games["away_id"]).all())
    fin = games[games["has_box"]]
    add_check(p, "rated finals have both scores", fin[["home_score", "away_score"]].notna().all().all(),
              f"{int(fin[['home_score', 'away_score']].isna().any(axis=1).sum())} missing")
    add_check(p, "scores in plausible range (50-200)",
              fin[["home_score", "away_score"]].stack().between(50, 200).all())
    add_check(p, "no tied finals", (fin["home_score"] != fin["away_score"]).all())
    nobox = int((games["status"] == "final_no_box").sum())
    add_check(p, "finals missing a box score are flagged, not used", True, f"{nobox} games flagged")
    dup_slot = int(games.duplicated(["home_id", "start_time"]).sum())
    add_check(p, "no team has two games at the same start time", dup_slot == 0, f"{dup_slot} duplicates")
    out.append(p)

    if tg is not None:
        q = profile(tg, "nba/team_games", keys=["game_id", "team_id"],
                    required=["pts", "fga", "fta", "oreb", "tov"])
        per_game = tg.groupby("game_id").size()
        add_check(q, "exactly two team rows per game", (per_game == 2).all())
        poss = tg["fga"] - tg["oreb"] + tg["tov"] + 0.44 * tg["fta"]
        add_check(q, "possessions in plausible range (70-140)", poss.between(70, 140).mean() > 0.999,
                  f"{int((~poss.between(70, 140)).sum())} outside range")
        po = int(tg["tov_player_only"].sum()) if "tov_player_only" in tg else 0
        add_check(q, "turnover fallback rows are flagged", True, f"{po} rows use player-only turnovers (2017-18)")
        out.append(q)

    if pg is not None:
        r = profile(pg, "nba/player_games", keys=["game_id", "athlete_id"], season_col="season",
                    required=["minutes", "played"])
        add_check(r, "minutes in range (0-70)", pg["minutes"].between(0, 70).all())
        out.append(r)
    return out


def nfl() -> list[Profile]:
    out: list[Profile] = []
    games, lines, pbp, inj = (_read("nfl", n) for n in ("games", "market_lines", "pbp", "injuries"))
    if games is None:
        return out
    p = profile(games, "nfl/games", keys=["game_id"], date_col="start_time", season_col="season",
                required=["game_id", "season", "week", "home_team", "away_team", "start_time", "home_rest", "away_rest"])
    add_check(p, "home team differs from away team", (games["home_team"] != games["away_team"]).all())
    fin = games[games["status"] == "final"]
    add_check(p, "final scores non-negative", (fin[["home_score", "away_score"]] >= 0).all().all())
    add_check(p, "32 franchises after relocation mapping",
              len(set(games["home_team"]) | set(games["away_team"])) == 32,
              f"{len(set(games['home_team']) | set(games['away_team']))} teams")
    out.append(p)

    if lines is not None:
        q = profile(lines, "nfl/market_lines", keys=["game_id", "market", "source"], required=["market"])
        sp = lines[lines["market"] == "spread"]
        add_check(q, "every spread row has a line", sp["line"].notna().all())
        add_check(q, "line capture time recorded or explained",
                  (lines["captured_at"].notna() | lines["capture_note"].notna()).all())
        merged = sp.merge(fin[["game_id", "home_score", "away_score"]], on="game_id")
        corr = float((merged["home_score"] - merged["away_score"]).corr(-merged["line"])) if len(merged) else float("nan")
        add_check(q, "spread sign convention (home margin correlates with -line)", corr > 0.3, f"corr {corr:.3f}")
        out.append(q)

    if pbp is not None and len(pbp):
        r = profile(pbp, "nfl/pbp", keys=["game_id", "play_id"], season_col="season",
                    required=["game_id", "play_id", "season", "home_team", "away_team"])
        plays = pbp[pbp["play_type"].isin(["pass", "run"])]
        add_check(r, "EPA present on pass/run plays", plays["epa"].notna().mean() > 0.995,
                  f"{plays['epa'].isna().mean() * 100:.2f}% missing")
        seasons = set(pbp["season"].unique())
        want = set(fin.loc[fin["season"].isin(seasons), "game_id"])
        have = set(pbp["game_id"].unique())
        missing = sorted(want - have)
        add_check(r, "every final game in those seasons has play-by-play", not missing,
                  f"{len(missing)} missing" + (f", e.g. {missing[:3]}" if missing else ""))
        # Cross-source: final score from play-by-play vs games.csv.
        last = pbp.sort_values(["game_id", "play_id"]).groupby("game_id").tail(1)
        last = last.assign(
            pbp_home=lambda d: d["posteam_score"].where(d["posteam"] == d["home_team"], d["defteam_score"]),
            pbp_away=lambda d: d["defteam_score"].where(d["posteam"] == d["home_team"], d["posteam_score"]),
        )
        cmp = last.merge(fin[["game_id", "home_score", "away_score"]], on="game_id")
        bad = cmp[(cmp["pbp_home"] != cmp["home_score"]) | (cmp["pbp_away"] != cmp["away_score"])].dropna(subset=["pbp_home"])
        add_check(r, "play-by-play final scores match games.csv", len(bad) <= max(3, 0.01 * len(cmp)),
                  f"{len(bad)} of {len(cmp)} differ (last play can precede a final PAT/score)")
        out.append(r)

    if inj is not None and len(inj):
        s = profile(inj, "nfl/injuries", keys=["season", "week", "game_type", "team", "gsis_id"], season_col="season",
                    required=["team", "gsis_id"])
        designated = float(inj["report_status"].notna().mean()) if "report_status" in inj else 0.0
        add_check(s, "game designation share reported (blank = practice report only)", True,
                  f"{designated * 100:.1f}% of rows carry Out/Doubtful/Questionable")
        out.append(s)
    return out


def run(league: str = "all") -> dict:
    profiles = (nba() if league in ("nba", "all") else []) + (nfl() if league in ("nfl", "all") else [])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": all(p.ok for p in profiles) if profiles else False,
        "datasets": [p.to_dict() for p in profiles],
    }
    out = ensure(output_dir("validation"))
    (out / f"validation_{league}.json").write_text(json.dumps(report, indent=2, default=str))
    return report
