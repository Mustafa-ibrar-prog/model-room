"""Player-level NFL data for the prop engine.

Built alongside the team data in ingest.py and never modifies it.

Raw (unchanged, data/raw/nfl/)
  snap_counts_<season>.parquet       nflverse (Pro Football Reference snap counts)
  roster_weekly_<season>.parquet     nflverse weekly rosters (positions, IDs incl. Sportradar)
  ftn_charting_<season>.parquet      FTN charting via nflverse, 2022+ (blitzers, pass rushers, play action)
  pbp_participation_<season>.parquet nflverse participation (man/zone coverage, pressure), through last season
  injuries_<season>.parquet          injury reports (older seasons added for the prop backtest)
  depth_charts_<season>.parquet      depth charts: weekly through 2024, timestamped (ESPN) snapshots from 2025

Processed (data/processed/nfl/)
  player_games.parquet   one row per player per game with box-score stats, shares and snaps
  pass_plays.parquet     one row per pass attempt with receiver, coverage, blitz, pressure context
  rush_plays.parquet     one row per designed run / scramble
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modelroom.common.download import DownloadError, fetch
from modelroom.common.paths import ensure, processed_dir, raw_dir
from modelroom.sources import state

from .ingest import FRANCHISE, RELEASE, available_pbp_seasons

FTN_FIRST_SEASON = 2022
PARTICIPATION_FIRST_SEASON = 2016
SKILL = ("QB", "RB", "FB", "WR", "TE")

RAW_PBP_COLUMNS = [
    "game_id", "play_id", "old_game_id", "season", "week", "season_type", "game_date", "posteam", "defteam",
    "home_team", "away_team", "play_type", "two_point_attempt", "two_point_conv_result",
    "complete_pass", "incomplete_pass", "interception", "sack", "qb_dropback", "qb_scramble", "qb_hit",
    "rush_attempt", "pass_attempt", "passing_yards", "receiving_yards", "rushing_yards", "air_yards",
    "yards_after_catch", "passer_player_id", "passer_player_name", "receiver_player_id", "receiver_player_name",
    "rusher_player_id", "rusher_player_name", "td_player_id", "touchdown", "pass_touchdown", "rush_touchdown",
    "fumble_lost", "fumbled_1_player_id", "fumbled_2_player_id", "yardline_100", "down", "wp", "epa",
    "pass_location", "score_differential", "game_seconds_remaining",
]


# ------------------------------------------------------------------ downloads
def _release(kind: str, name: str) -> str:
    return f"{RELEASE}/{kind}/{name}"


def download(seasons: list[int], current: int) -> dict:
    """Fetch the extra nflverse files. A missing current-season file is noted, not fatal."""
    out = ensure(raw_dir("nfl"))
    got: dict[str, list[str]] = {}
    missing: list[str] = []
    plan = []
    for s in seasons:
        plan += [("snap_counts", f"snap_counts_{s}.parquet", s), ("weekly_rosters", f"roster_weekly_{s}.parquet", s),
                 ("injuries", f"injuries_{s}.parquet", s), ("depth_charts", f"depth_charts_{s}.parquet", s)]
        if s >= FTN_FIRST_SEASON:
            plan.append(("ftn_charting", f"ftn_charting_{s}.parquet", s))
        if s >= PARTICIPATION_FIRST_SEASON:
            plan.append(("pbp_participation", f"pbp_participation_{s}.parquet", s))
    for kind, name, s in plan:
        dest = out / name
        # Completed seasons don't change; re-download only the current season.
        if dest.exists() and s < current:
            got.setdefault(kind, []).append(name)
            continue
        try:
            fetch(_release(kind, name), dest)
            got.setdefault(kind, []).append(name)
        except DownloadError:
            if dest.exists():
                got.setdefault(kind, []).append(name)  # keep the copy we have
            else:
                missing.append(name)
    for kind, sid in (("snap_counts", "nflverse_snap_counts"), ("weekly_rosters", "nflverse_rosters"),
                      ("ftn_charting", "ftn_charting"), ("pbp_participation", "nflverse_participation"),
                      ("depth_charts", "nflverse_depth_charts")):
        if got.get(kind):
            state.record(sid, files=got[kind])
    return {"files": {k: len(v) for k, v in got.items()}, "not_published": missing}


# ---------------------------------------------------------------- loaders
def _concat(prefix: str, seasons: list[int], columns: list[str] | None = None) -> pd.DataFrame:
    parts = []
    for s in seasons:
        f = raw_dir("nfl") / f"{prefix}_{s}.parquet"
        if f.exists():
            df = pd.read_parquet(f)
            if columns:
                df = df[[c for c in columns if c in df.columns]]
            parts.append(df.assign(season=s) if "season" not in df.columns else df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns or [])


def raw_pbp(seasons: list[int]) -> pd.DataFrame:
    df = _concat("play_by_play", seasons, RAW_PBP_COLUMNS)
    for c in ("posteam", "defteam", "home_team", "away_team"):
        df[c] = df[c].replace(FRANCHISE)
    return df


def rosters(seasons: list[int]) -> pd.DataFrame:
    cols = ["season", "week", "game_type", "team", "position", "depth_chart_position", "full_name", "gsis_id",
            "pfr_id", "sportradar_id", "espn_id", "status", "jersey_number"]
    r = _concat("roster_weekly", seasons, cols)
    r = r[r["gsis_id"].notna() & (r["gsis_id"] != "")]
    r["team"] = r["team"].replace(FRANCHISE)
    return r


# ---------------------------------------------------------- play tables
def _f(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def build_play_tables(pbp: pd.DataFrame, seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Official-stat plays: no nullified plays, no two-point tries."""
    p = pbp[(pbp["play_type"] != "no_play") & (_f(pbp["two_point_attempt"]) == 0) & pbp["posteam"].notna()].copy()
    att = (_f(p["complete_pass"]) + _f(p["incomplete_pass"]) + _f(p["interception"])) > 0
    passes = p[att & (_f(p["sack"]) == 0)].copy()
    passes["complete"] = _f(passes["complete_pass"])
    passes["yards"] = np.where(passes["complete"] == 1, _f(passes["receiving_yards"]), 0.0)
    passes["pass_yards"] = np.where(passes["complete"] == 1, _f(passes["passing_yards"]), 0.0)
    passes["int"] = _f(passes["interception"])
    passes["pass_td"] = _f(passes["pass_touchdown"])
    passes["qb_hit"] = _f(passes["qb_hit"])

    rushes = p[(_f(p["rush_attempt"]) == 1) & p["rusher_player_id"].notna()].copy()
    rushes["yards"] = _f(rushes["rushing_yards"])
    rushes["rush_td"] = _f(rushes["rush_touchdown"])
    rushes["scramble"] = _f(rushes["qb_scramble"])

    # Context: FTN (blitz, pass rushers) and participation (coverage, pressure).
    ftn = _concat("ftn_charting", [s for s in seasons if s >= FTN_FIRST_SEASON],
                  ["nflverse_game_id", "nflverse_play_id", "n_blitzers", "n_pass_rushers", "is_play_action",
                   "is_screen_pass"])
    if len(ftn):
        ftn = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
        ftn["play_id"] = pd.to_numeric(ftn["play_id"], errors="coerce")
        ftn = ftn.drop_duplicates(["game_id", "play_id"])
        passes = passes.merge(ftn, on=["game_id", "play_id"], how="left")
    else:
        for c in ("n_blitzers", "n_pass_rushers", "is_play_action", "is_screen_pass"):
            passes[c] = np.nan
    part = _concat("pbp_participation", [s for s in seasons if s >= PARTICIPATION_FIRST_SEASON],
                   ["nflverse_game_id", "play_id", "defense_man_zone_type", "defense_coverage_type", "was_pressure",
                    "number_of_pass_rushers", "defenders_in_box", "route"])
    if len(part):
        part = part.rename(columns={"nflverse_game_id": "game_id"})
        part["play_id"] = pd.to_numeric(part["play_id"], errors="coerce")
        part = part.drop_duplicates(["game_id", "play_id"])
        passes = passes.merge(part.drop(columns=["defenders_in_box"]), on=["game_id", "play_id"], how="left")
        rushes = rushes.merge(part[["game_id", "play_id", "defenders_in_box"]], on=["game_id", "play_id"], how="left")
    else:
        for c in ("defense_man_zone_type", "defense_coverage_type", "was_pressure", "number_of_pass_rushers", "route"):
            passes[c] = np.nan
        rushes["defenders_in_box"] = np.nan
    passes["blitz"] = np.where(passes["n_blitzers"].notna(), (pd.to_numeric(passes["n_blitzers"], errors="coerce") > 0).astype(float), np.nan)
    mz = passes["defense_man_zone_type"].astype("string")
    passes["man"] = np.where(mz.str.contains("MAN", na=False), 1.0, np.where(mz.str.contains("ZONE", na=False), 0.0, np.nan))
    pr = passes["was_pressure"]
    passes["pressure"] = np.where(pr.notna(), pr.astype(float, errors="ignore") if pr.dtype != object else pr.map({True: 1.0, False: 0.0, "TRUE": 1.0, "FALSE": 0.0}), np.nan)
    keep_p = ["game_id", "play_id", "season", "week", "season_type", "game_date", "posteam", "defteam",
              "passer_player_id", "receiver_player_id", "complete", "yards", "pass_yards", "air_yards", "int",
              "pass_td", "qb_hit", "blitz", "man", "pressure", "yardline_100", "epa", "wp", "pass_location",
              "is_play_action", "is_screen_pass"]
    keep_r = ["game_id", "play_id", "season", "week", "season_type", "game_date", "posteam", "defteam",
              "rusher_player_id", "yards", "rush_td", "scramble", "yardline_100", "epa", "wp", "defenders_in_box"]
    passes["pressure"] = pd.to_numeric(passes["pressure"], errors="coerce")
    return passes[keep_p].reset_index(drop=True), rushes[keep_r].reset_index(drop=True)


# ------------------------------------------------------------ player games
def build_player_games(pbp: pd.DataFrame, passes: pd.DataFrame, rushes: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    p = pbp[(pbp["play_type"] != "no_play") & pbp["posteam"].notna()]
    key = ["game_id", "team", "player_id"]

    qb = passes.groupby(["game_id", "posteam", "passer_player_id"]).agg(
        pass_att=("complete", "size"), pass_cmp=("complete", "sum"), pass_yds=("pass_yards", "sum"),
        pass_td=("pass_td", "sum"), ints=("int", "sum")).reset_index()
    qb.columns = key + list(qb.columns[3:])
    sacks = p[_f(p["sack"]) == 1].groupby(["game_id", "posteam", "passer_player_id"]).size().rename("sacks").reset_index()
    sacks.columns = key + ["sacks"]

    rec_src = passes[passes["receiver_player_id"].notna()]
    rec = rec_src.groupby(["game_id", "posteam", "receiver_player_id"]).agg(
        targets=("complete", "size"), receptions=("complete", "sum"), rec_yds=("yards", "sum"),
        rec_td=("pass_td", "sum"), air_yds=("air_yards", lambda s: float(np.nansum(s)))).reset_index()
    rec.columns = key + list(rec.columns[3:])
    longest = rec_src[rec_src["complete"] == 1].groupby(["game_id", "posteam", "receiver_player_id"])["yards"].max().rename("long_rec").reset_index()
    longest.columns = key + ["long_rec"]

    ru = rushes.groupby(["game_id", "posteam", "rusher_player_id"]).agg(
        carries=("yards", "size"), rush_yds=("yards", "sum"), rush_td=("rush_td", "sum"),
        scrambles=("scramble", "sum"), long_rush=("yards", "max")).reset_index()
    ru.columns = key + list(ru.columns[3:])

    # Any touchdown scored by the player (rushing, receiving, returns, recoveries): "anytime TD".
    tds = p[(_f(p["touchdown"]) == 1) & p["td_player_id"].notna()]
    anytd = tds.groupby(["game_id", "td_player_id"]).size().rename("td_scored").reset_index().rename(columns={"td_player_id": "player_id"})

    fl = []
    for c in ("fumbled_1_player_id", "fumbled_2_player_id"):
        x = p[(_f(p["fumble_lost"]) == 1) & p[c].notna()].groupby(["game_id", c]).size().rename("fum_lost").reset_index()
        fl.append(x.rename(columns={c: "player_id"}))
    fum = pd.concat(fl).groupby(["game_id", "player_id"], as_index=False)["fum_lost"].sum() if fl else pd.DataFrame(columns=["game_id", "player_id", "fum_lost"])

    two = pbp[(_f(pbp["two_point_attempt"]) == 1) & (pbp["two_point_conv_result"] == "success")]
    tp = []
    for c in ("passer_player_id", "receiver_player_id", "rusher_player_id"):
        tp.append(two[two[c].notna()].groupby(["game_id", c]).size().rename("two_pt").reset_index().rename(columns={c: "player_id"}))
    twopt = pd.concat(tp).groupby(["game_id", "player_id"], as_index=False)["two_pt"].sum()

    pg = qb.merge(rec, on=key, how="outer").merge(ru, on=key, how="outer").merge(sacks, on=key, how="left").merge(longest, on=key, how="left")
    pg = pg.merge(anytd, on=["game_id", "player_id"], how="left").merge(fum, on=["game_id", "player_id"], how="left").merge(twopt, on=["game_id", "player_id"], how="left")
    num = [c for c in pg.columns if c not in key]
    pg[num] = pg[num].fillna(0.0)
    pg["long_rec"] = np.where(pg["receptions"] > 0, pg["long_rec"], 0.0)
    pg["fantasy_ppr"] = (0.04 * pg["pass_yds"] + 4 * pg["pass_td"] - 2 * pg["ints"] + 0.1 * pg["rush_yds"]
                         + 6 * pg["rush_td"] + pg["receptions"] + 0.1 * pg["rec_yds"] + 6 * pg["rec_td"]
                         - 2 * pg["fum_lost"] + 2 * pg["two_pt"])
    # Non-offensive TDs (returns) also score 6 in standard PPR.
    pg["fantasy_ppr"] += 6 * np.clip(pg["td_scored"] - pg["rush_td"] - pg["rec_td"], 0, None)

    # Team context per game.
    team = passes.groupby(["game_id", "posteam"]).agg(team_pass_att=("complete", "size"), team_air=("air_yards", lambda s: float(np.nansum(s))))
    team = team.join(rushes.groupby(["game_id", "posteam"]).agg(team_carries=("yards", "size"),
                                                                 team_designed=("scramble", lambda s: float((s == 0).sum()))))
    team = team.join(p[_f(p["sack"]) == 1].groupby(["game_id", "posteam"]).size().rename("team_sacks")).fillna(0.0).reset_index()
    team = team.rename(columns={"posteam": "team"})
    pg = pg.merge(team, on=["game_id", "team"], how="left")

    meta = pbp.drop_duplicates("game_id").set_index("game_id")[["season", "week", "season_type", "game_date", "home_team", "away_team"]]
    pg = pg.join(meta, on="game_id")
    pg["opp"] = np.where(pg["team"] == pg["home_team"], pg["away_team"], pg["home_team"])

    # Positions, names and IDs from weekly rosters (season-week), falling back to the season's most common entry.
    r = rosters(seasons)
    if len(r):
        r = r.sort_values(["season", "week"])
        wk = r.drop_duplicates(["season", "week", "gsis_id"], keep="last")[["season", "week", "gsis_id", "position", "full_name", "pfr_id", "sportradar_id"]]
        pg = pg.merge(wk.rename(columns={"gsis_id": "player_id"}), on=["season", "week", "player_id"], how="left")
        season_pos = r.groupby(["season", "gsis_id"]).agg(pos2=("position", lambda s: s.mode().iat[0]), name2=("full_name", "last"),
                                                          pfr2=("pfr_id", "last"), sr2=("sportradar_id", "last")).reset_index()
        pg = pg.merge(season_pos.rename(columns={"gsis_id": "player_id"}), on=["season", "player_id"], how="left")
        for a, b in (("position", "pos2"), ("full_name", "name2"), ("pfr_id", "pfr2"), ("sportradar_id", "sr2")):
            pg[a] = pg[a].fillna(pg[b])
        pg = pg.drop(columns=["pos2", "name2", "pfr2", "sr2"])
    else:
        for c in ("position", "full_name", "pfr_id", "sportradar_id"):
            pg[c] = None
    # Names from play-by-play when the roster lacks the player.
    names = pd.concat([
        pbp[["passer_player_id", "passer_player_name"]].dropna().set_axis(["player_id", "n"], axis=1),
        pbp[["receiver_player_id", "receiver_player_name"]].dropna().set_axis(["player_id", "n"], axis=1),
        pbp[["rusher_player_id", "rusher_player_name"]].dropna().set_axis(["player_id", "n"], axis=1),
    ]).drop_duplicates("player_id", keep="last").set_index("player_id")["n"]
    pg["full_name"] = pg["full_name"].fillna(pg["player_id"].map(names))
    pg["position"] = pg["position"].replace({"FB": "RB", "HB": "RB"})

    # Snap counts (PFR ids).
    sc = _concat("snap_counts", seasons, ["game_id", "pfr_player_id", "team", "offense_snaps", "offense_pct", "position"])
    if len(sc):
        sc = sc.drop_duplicates(["game_id", "pfr_player_id"]).rename(columns={"pfr_player_id": "pfr_id", "position": "snap_pos", "team": "snap_team"})
        pg = pg.merge(sc[["game_id", "pfr_id", "offense_snaps", "offense_pct"]], on=["game_id", "pfr_id"], how="left")
    else:
        pg["offense_snaps"] = np.nan
        pg["offense_pct"] = np.nan

    pg["game_date"] = pd.to_datetime(pg["game_date"]).dt.date
    return pg.sort_values(["game_date", "game_id", "team", "player_id"]).reset_index(drop=True)


def snap_only_rows(pg: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    """Players who took offensive snaps but recorded no stat (needed so zero games count in the history)."""
    sc = _concat("snap_counts", seasons, ["game_id", "pfr_player_id", "team", "offense_snaps", "offense_pct", "position", "season", "week"])
    r = rosters(seasons)
    if not len(sc) or not len(r):
        return pg.iloc[0:0]
    sc = sc[(sc["offense_snaps"] > 0) & sc["position"].isin(SKILL)].rename(columns={"pfr_player_id": "pfr_id"})
    ids = r.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id", keep="last")[["pfr_id", "gsis_id", "full_name", "sportradar_id"]]
    sc = sc.merge(ids, on="pfr_id", how="inner").rename(columns={"gsis_id": "player_id"})
    sc["team"] = sc["team"].replace(FRANCHISE)
    have = set(zip(pg["game_id"], pg["player_id"]))
    extra = sc[[(g, p) not in have for g, p in zip(sc["game_id"], sc["player_id"])]]
    if not len(extra):
        return pg.iloc[0:0]
    meta = pg.drop_duplicates(["game_id", "team"]).set_index(["game_id", "team"])
    ctx_cols = ["team_pass_att", "team_air", "team_carries", "team_designed", "team_sacks", "season", "week",
                "season_type", "game_date", "home_team", "away_team", "opp"]
    extra = extra.join(meta[ctx_cols].drop(columns=["season", "week"]), on=["game_id", "team"], how="inner")
    out = pd.DataFrame({c: extra[c] if c in extra.columns else 0.0 for c in pg.columns})
    out["position"] = extra["position"].replace({"FB": "RB"})
    return out


def run(seasons: list[int] | None = None, *, download_current: int | None = None) -> dict:
    seasons = seasons or available_pbp_seasons()
    summary: dict = {}
    if download_current is not None:
        summary["download"] = download(seasons, download_current)
    pbp = raw_pbp(seasons)
    passes, rushes = build_play_tables(pbp, seasons)
    pg = build_player_games(pbp, passes, rushes, seasons)
    zero = snap_only_rows(pg, seasons)
    if len(zero):
        pg = pd.concat([pg, zero], ignore_index=True).sort_values(["game_date", "game_id", "team", "player_id"]).reset_index(drop=True)
    out = ensure(processed_dir("nfl"))
    pg.to_parquet(out / "player_games.parquet", index=False)
    passes.to_parquet(out / "pass_plays.parquet", index=False)
    rushes.to_parquet(out / "rush_plays.parquet", index=False)
    summary.update({
        "player_games": int(len(pg)), "pass_plays": int(len(passes)), "rush_plays": int(len(rushes)),
        "with_snaps": round(float(pg["offense_snaps"].notna().mean()), 3),
        "with_position": round(float(pg["position"].notna().mean()), 3),
        "blitz_coverage": round(float(passes["blitz"].notna().mean()), 3),
        "man_zone_coverage": round(float(passes["man"].notna().mean()), 3),
        "seasons": seasons,
    })
    return summary


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = processed_dir("nfl")
    f = d / "player_games.parquet"
    if not f.exists():
        raise FileNotFoundError("No NFL player data yet. Run: python -m modelroom nfl ingest")
    return pd.read_parquet(f), pd.read_parquet(d / "pass_plays.parquet"), pd.read_parquet(d / "rush_plays.parquet")
