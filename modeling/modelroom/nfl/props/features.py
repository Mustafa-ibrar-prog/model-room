"""As-of-cutoff features for the NFL prop model. Every value uses games before the cutoff only.

Player usage   target share, carry share, snap share (recent vs longer run)
Player skill   catch rate, yards per reception / carry, TD rates, QB completion %, INT and TD rates,
               receiver yards per target vs man and vs zone, QB yards per attempt vs blitz / no blitz
Defense        allowed catch rate, yards per reception and target share by position group (WR / TE / RB),
               yards per carry, TD rates, completion %, INT rate, pressure rate, blitz rate, man-coverage rate,
               pass attempts and carries faced
Team volume    pass attempts and carries per game
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import HISTORY_SEASONS, PropSettings

GROUPS = {"WR": "WR", "TE": "TE", "RB": "RB", "FB": "RB", "QB": "QB"}


_PROMOTED: dict = {}


@dataclass
class Context:
    """Everything the model needs at one cutoff."""

    cutoff: pd.Timestamp
    season: int
    players: pd.DataFrame      # one row per player (latest team), usage and skill estimates
    defense: pd.DataFrame      # one row per defense, ratios to league
    teams: pd.DataFrame        # one row per offense, volume base rates
    league: dict
    pools: dict                # empirical yards samples by group


def _recency(df: pd.DataFrame, key: str | list[str], half_life: float, carry: float, season: int) -> np.ndarray:
    """0.5^(games ago / half life) × carry^(seasons back). Most recent game = 0 games ago."""
    k = df.groupby(key, sort=False).cumcount(ascending=False).to_numpy(float)
    gap = (season - df["season"].to_numpy(int)).clip(0, None)
    return np.power(0.5, k / half_life) * np.power(carry, gap)


def history(pg: pd.DataFrame, cutoff: pd.Timestamp, season: int) -> pd.DataFrame:
    d = pd.to_datetime(pg["game_date"])
    return pg[(d < cutoff) & (pg["season"] >= season - HISTORY_SEASONS)]


def _wsum(df: pd.DataFrame, by: str | list[str], w: np.ndarray, cols: list[str]) -> pd.DataFrame:
    x = df[cols].to_numpy(float) * w[:, None]
    out = pd.DataFrame(x, columns=cols, index=df.index)
    out["w"] = w
    for b in [by] if isinstance(by, str) else by:
        out[b] = df[b].to_numpy()
    return out.groupby(by, sort=False).sum()


def _shrink(num, den, prior_mean, prior_n):
    return (num + prior_mean * prior_n) / (den + prior_n)


def build(pg: pd.DataFrame, passes: pd.DataFrame, rushes: pd.DataFrame, cutoff: pd.Timestamp, season: int,
          s: PropSettings, depth_now: dict | None = None, depth_hist: pd.DataFrame | None = None) -> Context:
    H = history(pg, cutoff, season).sort_values(["game_date", "game_id"])
    H = H.assign(group=H["position"].map(GROUPS))
    played = H[(H["offense_snaps"].fillna(0) > 0) | (H[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
    played = played[played["group"].notna()]

    # ---------------------------------------------------------------- teams
    tg = H.drop_duplicates(["game_id", "team"])[["game_id", "team", "opp", "season", "game_date", "team_pass_att", "team_carries"]]
    tg = tg.sort_values("game_date")
    wt = _recency(tg, "team", s.def_half_life_games, s.season_carry, season)
    team = _wsum(tg, "team", wt, ["team_pass_att", "team_carries"])
    lg_pa = float(np.average(tg["team_pass_att"], weights=wt))
    lg_ru = float(np.average(tg["team_carries"], weights=wt))
    teams = pd.DataFrame({
        "pa_base": _shrink(team["team_pass_att"], team["w"], lg_pa, s.def_prior_games),
        "ru_base": _shrink(team["team_carries"], team["w"], lg_ru, s.def_prior_games),
    })
    wd = _recency(tg, "opp", s.def_half_life_games, s.season_carry, season)
    faced = _wsum(tg, "opp", wd, ["team_pass_att", "team_carries"])
    teams = teams.join(pd.DataFrame({
        "pa_faced": _shrink(faced["team_pass_att"], faced["w"], lg_pa, s.def_prior_games) - lg_pa,
        "ru_faced": _shrink(faced["team_carries"], faced["w"], lg_ru, s.def_prior_games) - lg_ru,
    }), how="outer").fillna(0.0)

    # ---------------------------------------------------------------- league + defense
    hp = passes[(pd.to_datetime(passes["game_date"]) < cutoff) & (passes["season"] >= season - HISTORY_SEASONS)]
    hr = rushes[(pd.to_datetime(rushes["game_date"]) < cutoff) & (rushes["season"] >= season - HISTORY_SEASONS)]
    pos = played.set_index(["game_id", "player_id"])["group"]
    pos = pos[~pos.index.duplicated()]
    hp = hp.assign(group=pd.MultiIndex.from_arrays([hp["game_id"], hp["receiver_player_id"]]).map(pos))
    hr = hr.assign(group=pd.MultiIndex.from_arrays([hr["game_id"], hr["rusher_player_id"]]).map(pos))

    defense, league = _defense(hp, hr, tg, season, s)
    # Targets to RBs / WRs / TEs per team pass attempt (throwaways, spikes, batted balls and the odd QB or
    # lineman target don't go to the tracked receivers).
    tt = played[played["group"].isin(["RB", "WR", "TE"])].groupby(["game_id", "team"])["targets"].sum()
    pa = tg.set_index(["game_id", "team"])["team_pass_att"]
    pa = pa[~pa.index.duplicated()].reindex(tt.index)
    league["target_rate"] = float(tt.sum() / pa.sum()) if pa.sum() > 0 else 1.0
    # Carries by RBs / WRs / TEs per team carry (the rest: QBs, kneels, others).
    sk = played[played["group"].isin(["RB", "WR", "TE"])].groupby(["game_id", "team"])["carries"].sum()
    ru = tg.set_index(["game_id", "team"])["team_carries"]
    ru = ru[~ru.index.duplicated()].reindex(sk.index)
    league["skill_carry_rate"] = float(sk.sum() / ru.sum()) if ru.sum() > 0 else 0.84

    # ---------------------------------------------------------------- players
    w = _recency(played, "player_id", s.half_life_games, s.season_carry, season)
    wshort = _recency(played, "player_id", 2.0, 0.2, season)
    cols = ["targets", "receptions", "rec_yds", "rec_td", "carries", "rush_yds", "rush_td", "team_pass_att", "team_carries",
            "pass_att", "pass_cmp", "pass_yds", "pass_td", "ints", "scrambles"]
    agg = _wsum(played, "player_id", w, cols)
    if s.share_half_life_games > 0:  # shares on their own (shorter) recency: roles change faster than skill
        ws_ = _recency(played, "player_id", s.share_half_life_games, s.season_carry, season)
        sh = _wsum(played, "player_id", ws_, ["targets", "carries", "team_pass_att", "team_carries"])
        agg_share = sh
    else:
        agg_share = agg
    snap = played.assign(sp=played["offense_pct"]).dropna(subset=["sp"])
    wl = _recency(snap, "player_id", s.half_life_games, s.season_carry, season)
    ws = _recency(snap, "player_id", 2.0, 0.2, season)
    snap_long = (snap["sp"] * wl).groupby(snap["player_id"]).sum() / pd.Series(wl, index=snap.index).groupby(snap["player_id"]).sum()
    snap_short = (snap["sp"] * ws).groupby(snap["player_id"]).sum() / pd.Series(ws, index=snap.index).groupby(snap["player_id"]).sum()
    del wshort

    last = played.groupby("player_id").tail(1).set_index("player_id")
    P = pd.DataFrame(index=agg.index)
    P["name"] = last["full_name"]
    P["group"] = last["group"]
    P["team_last"] = last["team"]
    P["last_game"] = pd.to_datetime(last["game_date"])
    P["sportradar_id"] = last["sportradar_id"]
    P["games_w"] = agg["w"]
    P["games_season"] = played[played["season"] == season].groupby("player_id").size().reindex(P.index).fillna(0)
    P["snap_long"] = snap_long.reindex(P.index)
    P["snap_short"] = snap_short.reindex(P.index)

    # Position priors (share per appearance), from the same window.
    g = P["group"]
    tshare_raw = agg_share["targets"] / agg_share["team_pass_att"].replace(0, np.nan)
    cshare_raw = agg_share["carries"] / agg_share["team_carries"].replace(0, np.nan)
    prior_t = tshare_raw.groupby(g).median()
    prior_c = cshare_raw.groupby(g).median()
    avg_pa = agg_share["team_pass_att"] / agg_share["w"]
    avg_ru = agg_share["team_carries"] / agg_share["w"]
    P["target_share"] = _shrink(agg_share["targets"], agg_share["team_pass_att"], g.map(prior_t).fillna(0.02), s.share_prior_games * avg_pa.fillna(lg_pa))
    P["carry_share"] = _shrink(agg_share["carries"], agg_share["team_carries"], g.map(prior_c).fillna(0.01), s.share_prior_games * avg_ru.fillna(lg_ru))
    if s.share_model == "role":
        P = _role_share(P, played, season, depth_now or {})

    L = league
    P["catch_rate"] = _shrink(agg["receptions"], agg["targets"], g.map(L["cr"]).fillna(L["cr"]["WR"]), s.rate_prior)
    ypr_pos = g.map(L["ypr"]).fillna(L["ypr"]["WR"])
    P["ypr_factor"] = _shrink(agg["rec_yds"], agg["receptions"], ypr_pos, s.rate_prior) / ypr_pos
    P["rec_td_rate"] = _shrink(agg["rec_td"], agg["targets"], g.map(L["rec_td"]).fillna(L["rec_td"]["WR"]), s.td_prior)
    ypc_pos = g.map(L["ypc"]).fillna(L["ypc"]["RB"])
    P["ypc_factor"] = _shrink(agg["rush_yds"], agg["carries"], ypc_pos, s.rate_prior) / ypc_pos
    P["rush_td_rate"] = _shrink(agg["rush_td"], agg["carries"], g.map(L["rush_td"]).fillna(L["rush_td"]["RB"]), s.td_prior)
    # QB passing
    P["cmp_rate"] = _shrink(agg["pass_cmp"], agg["pass_att"], L["qb_cmp"], s.rate_prior * 2)
    P["ypcmp_factor"] = _shrink(agg["pass_yds"], agg["pass_cmp"], L["qb_ypcmp"], s.rate_prior * 2) / L["qb_ypcmp"]
    P["int_rate"] = _shrink(agg["ints"], agg["pass_att"], L["qb_int"], s.td_prior * 3)
    P["pass_td_rate"] = _shrink(agg["pass_td"], agg["pass_att"], L["qb_td"], s.td_prior * 3)
    P["pass_att_w"] = agg["pass_att"]
    # Unweighted sample sizes behind the estimates (for "insufficient history" flags).
    raw = played.groupby("player_id")[["targets", "carries", "pass_att"]].sum()
    P["n_games"] = played.groupby("player_id").size().reindex(P.index).fillna(0).astype(int)
    P["n_targets"] = raw["targets"].reindex(P.index).fillna(0).astype(int)
    P["n_carries"] = raw["carries"].reindex(P.index).fillna(0).astype(int)
    P["n_pass_att"] = raw["pass_att"].reindex(P.index).fillna(0).astype(int)
    # Career pass attempts before the cutoff (every season in the data, from 2018): a QB's experience.
    prior = pg[pd.to_datetime(pg["game_date"]) < pd.Timestamp(cutoff).tz_localize(None) if pd.Timestamp(cutoff).tzinfo else pd.to_datetime(pg["game_date"]) < pd.Timestamp(cutoff)]
    P["career_pass_att"] = prior.groupby("player_id")["pass_att"].sum().reindex(P.index).fillna(0).astype(int)

    P["p_play"] = _play_rate(played, tg, P)
    if s.fill_in_weight < 1.0:
        # Games a player spent filling in for a missing teammate count for less: his share then reflects his
        # usual role, and the model's redistribution adds the fill-in share back when someone is missing now.
        pr = _PROMOTED.get(id(pg))
        if pr is None:
            pr = promoted_flags(pg)
            _PROMOTED.clear()
            _PROMOTED[id(pg)] = pr
        fl = pd.MultiIndex.from_arrays([played["game_id"], played["player_id"]]).map(pr).fillna(0.0).to_numpy()
        wf = w * np.where(fl > 0, s.fill_in_weight, 1.0)
        sf = _wsum(played, "player_id", wf, ["targets", "carries", "team_pass_att", "team_carries"])
        f_pa = sf["team_pass_att"] / sf["w"]
        f_ru = sf["team_carries"] / sf["w"]
        P["target_share_role"] = _shrink(sf["targets"], sf["team_pass_att"], g.map(prior_t).fillna(0.02), s.share_prior_games * f_pa.fillna(lg_pa))
        P["carry_share_role"] = _shrink(sf["carries"], sf["team_carries"], g.map(prior_c).fillna(0.01), s.share_prior_games * f_ru.fillna(lg_ru))
    if depth_now is not None and depth_hist is not None and s.role_share_weight < 1.0:
        # Role-matched usage: history games played at a different depth rank (e.g. a backup's games as the
        # fill-in starter) count for less, so a player's share reflects the role he holds now.
        h = played[["season", "week", "player_id"]].merge(depth_hist, on=["season", "week", "player_id"], how="left")
        hd = h["depth"].fillna(9.0).clip(upper=3).to_numpy()
        nd = played["player_id"].map(lambda x: min(depth_now.get(x, 9.0), 3.0)).to_numpy()
        wr = w * np.where(hd == nd, 1.0, s.role_share_weight)
        sr = _wsum(played, "player_id", wr, ["targets", "carries", "team_pass_att", "team_carries"])
        a_pa = sr["team_pass_att"] / sr["w"]
        a_ru = sr["team_carries"] / sr["w"]
        P["target_share_role"] = _shrink(sr["targets"], sr["team_pass_att"], g.map(prior_t).fillna(0.02), s.share_prior_games * a_pa.fillna(lg_pa))
        P["carry_share_role"] = _shrink(sr["carries"], sr["team_carries"], g.map(prior_c).fillna(0.01), s.share_prior_games * a_ru.fillna(lg_ru))

    P = P.join(_coverage_splits(hp, played, season, s, L))
    P = P.join(_blitz_splits(hp, season, s, L))
    return Context(cutoff, season, P, defense, teams, L, _pools(hp, hr))


# P(plays | played k of his team's last n games since joining), measured on 2021-22 skill-position rosters
# (QB/RB/WR/TE, not ruled Out or Doubtful): tuning seasons, so the test seasons never inform it.
PLAY_RATE = {(1, 0): 0.40, (1, 1): 0.807, (2, 0): 0.37, (2, 1): 0.490, (2, 2): 0.881, (3, 0): 0.37, (3, 1): 0.296,
             (3, 2): 0.567, (3, 3): 0.937, (4, 0): 0.372, (4, 1): 0.556, (4, 2): 0.695, (4, 3): 0.844, (4, 4): 0.962}
PLAY_RATE_NEW = 0.347


def role_features(played: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per player: mean per-game target / carry share over his last 5 games played, and over this season."""
    pp = played.assign(tsh=played["targets"] / played["team_pass_att"].replace(0, np.nan),
                       csh=played["carries"] / played["team_carries"].replace(0, np.nan)).sort_values("game_date")
    last5 = pp.groupby("player_id").tail(5).groupby("player_id")[["tsh", "csh"]].mean().add_prefix("last5_")
    seas = pp[pp["season"] == season].groupby("player_id")[["tsh", "csh"]].mean().add_prefix("season_")
    return last5.join(seas, how="outer")


def _role_share(P: pd.DataFrame, played: pd.DataFrame, season: int, depth_now: dict) -> pd.DataFrame:
    from .config import SHARE_MODEL

    R = role_features(played, season).reindex(P.index)
    rank = pd.Series({pid: min(float(depth_now.get(pid, 9.0)), 4.0) for pid in P.index}, dtype=float).reindex(P.index).fillna(4.0)
    for kind, col, lab in (("t", "target_share", "tsh"), ("c", "carry_share", "csh")):
        new = P[col].copy()
        for grp, co in SHARE_MODEL.get(kind, {}).items():
            m = P["group"] == grp
            if not m.any():
                continue
            h = P.loc[m, col]
            l5 = R.loc[m, f"last5_{lab}"].fillna(h)
            se = R.loc[m, f"season_{lab}"].fillna(h)
            d = rank[m].map(lambda r: co[3 + int(r) - 1] if r <= 3 else 0.0)
            new[m] = (co[0] * h + co[1] * (l5 - h) + co[2] * (se - h) + d).clip(lower=0.0005)
        P[col + "_history"] = P[col]
        P[col] = new
    return P


def promoted_flags(pg: pd.DataFrame) -> pd.Series:
    """1 for a player-game where a teammate at his position who had more usage so far that season, and
    played in one of the team's previous three games, did not play: the player was filling in. Backward-
    looking only (earlier games of the season), so it never uses anything after the game it describes.
    Index: (game_id, player_id)."""
    x = pg[(pg["offense_snaps"].fillna(0) > 0) | (pg[["pass_att", "targets", "carries"]].sum(axis=1) > 0)]
    x = x.assign(group=x["position"].map(GROUPS))
    x = x[x["group"].isin(["RB", "WR", "TE"])]
    out = {}
    for (season, team, grp), d in x.groupby(["season", "team", "group"], sort=False):
        use_col = "carries" if grp == "RB" else "targets"
        games = d[["game_id", "game_date"]].drop_duplicates().sort_values("game_date")["game_id"].tolist()
        by_game = {g: dd for g, dd in d.groupby("game_id")}
        cum: dict = {}
        hist: list[set] = []
        for g in games:
            dd = by_game[g]
            present = set(dd["player_id"])
            recent = set().union(*hist[-3:]) if hist else set()
            absent = recent - present
            for pid in present:
                mine = cum.get(pid, 0.0)
                out[(g, pid)] = int(any(cum.get(j, 0.0) > mine for j in absent))
            for pid, u in zip(dd["player_id"], dd[use_col].fillna(0)):
                cum[pid] = cum.get(pid, 0.0) + float(u)
            hist.append(present)
    return pd.Series(out, name="promoted", dtype=float)


def _play_rate(played: pd.DataFrame, tg: pd.DataFrame, P: pd.DataFrame, k: int = 4) -> pd.Series:
    """Chance a rostered player actually plays, from how many of his team's last k games he played
    (counting only games since he first appeared for that team). Gameday inactives and healthy scratches
    are on the active roster but never touch the ball; without this their share is taken from the
    players who do play."""
    last = tg.sort_values("game_date").groupby("team").tail(k)[["game_id", "team", "game_date"]]
    pt = played[["player_id", "team", "game_id", "game_date"]]
    first = pt.groupby(["player_id", "team"])["game_date"].min()
    out = {}
    games_by_team = {t: d for t, d in last.groupby("team")}
    played_ids = set(zip(pt["player_id"], pt["game_id"]))
    for pid, team in P["team_last"].items():
        d = games_by_team.get(team)
        if d is None:
            continue
        f = first.get((pid, team))
        d = d[d["game_date"] >= f] if f is not None else d.iloc[0:0]
        n = len(d)
        y = sum((pid, g) in played_ids for g in d["game_id"])
        out[pid] = PLAY_RATE.get((n, y), PLAY_RATE_NEW)
    return pd.Series(out).reindex(P.index).fillna(PLAY_RATE_NEW)


def _defense(hp: pd.DataFrame, hr: pd.DataFrame, tg: pd.DataFrame, season: int, s: PropSettings) -> tuple[pd.DataFrame, dict]:
    """Per-defense rates (recency-weighted by the defense's games) as ratios to the league."""
    order = tg[["game_id", "opp", "game_date", "season"]].rename(columns={"opp": "defteam"})
    order = order.sort_values("game_date")
    order["w"] = _recency(order, "defteam", s.def_half_life_games, s.season_carry, season)
    wmap = order.set_index(["game_id", "defteam"])["w"]
    wmap = wmap[~wmap.index.duplicated()]

    def wcol(df):
        return pd.MultiIndex.from_arrays([df["game_id"], df["defteam"]]).map(wmap).fillna(0.0).to_numpy(float)

    p = hp.assign(w=wcol(hp))
    r = hr.assign(w=wcol(hr))
    L: dict = {"cr": {}, "ypr": {}, "rec_td": {}, "tshare": {}, "ypc": {}, "rush_td": {}}
    D = pd.DataFrame(index=sorted(set(order["defteam"])))
    for grp in ("WR", "TE", "RB"):
        x = p[p["group"] == grp]
        tgt = x.groupby("defteam")["w"].sum()
        rec = (x["complete"] * x["w"]).groupby(x["defteam"]).sum()
        yds = (x["yards"] * x["complete"] * x["w"]).groupby(x["defteam"]).sum()
        td = (x["pass_td"] * x["w"]).groupby(x["defteam"]).sum()
        allt = p.groupby("defteam")["w"].sum()
        cr, ypr = float(np.average(x["complete"])), float(x.loc[x["complete"] == 1, "yards"].mean())
        L["cr"][grp], L["ypr"][grp] = cr, ypr
        L["rec_td"][grp] = float(x["pass_td"].mean())
        L["tshare"][grp] = float(len(x) / max(len(p), 1))
        n = s.def_prior_games * 8  # ~8 targets to a group per game
        D[f"cr_{grp}"] = _shrink(rec, tgt, cr, n) / cr
        D[f"ypr_{grp}"] = _shrink(yds, rec, ypr, n * cr) / ypr
        D[f"tshare_{grp}"] = _shrink(tgt, allt, L["tshare"][grp], s.def_prior_games * 34) / L["tshare"][grp]
        D[f"rectd_{grp}"] = _shrink(td, tgt, L["rec_td"][grp], n * 3) / L["rec_td"][grp]
    L["cr"]["QB"], L["ypr"]["QB"], L["rec_td"]["QB"] = L["cr"]["RB"], L["ypr"]["RB"], L["rec_td"]["RB"]
    for grp in ("RB", "QB", "WR", "TE"):
        x = r[r["group"] == grp]
        L["ypc"][grp] = float(x["yards"].mean()) if len(x) else 4.0
        L["rush_td"][grp] = float(x["rush_td"].mean()) if len(x) else 0.02
    rb = r[r["group"] == "RB"]
    car = rb.groupby("defteam")["w"].sum()
    ry = (rb["yards"] * rb["w"]).groupby(rb["defteam"]).sum()
    rtd = (rb["rush_td"] * rb["w"]).groupby(rb["defteam"]).sum()
    D["ypc"] = _shrink(ry, car, L["ypc"]["RB"], s.def_prior_games * 20) / L["ypc"]["RB"]
    D["rushtd"] = _shrink(rtd, car, L["rush_td"]["RB"], s.def_prior_games * 60) / L["rush_td"]["RB"]

    att = p.groupby("defteam")["w"].sum()
    L["qb_cmp"] = float(p["complete"].mean())
    L["qb_ypcmp"] = float(p.loc[p["complete"] == 1, "pass_yards"].mean())
    L["qb_int"] = float(p["int"].mean())
    L["qb_td"] = float(p["pass_td"].mean())
    D["cmp"] = _shrink((p["complete"] * p["w"]).groupby(p["defteam"]).sum(), att, L["qb_cmp"], s.def_prior_games * 34) / L["qb_cmp"]
    D["ypcmp"] = _shrink((p["pass_yards"] * p["complete"] * p["w"]).groupby(p["defteam"]).sum(),
                         (p["complete"] * p["w"]).groupby(p["defteam"]).sum(), L["qb_ypcmp"], s.def_prior_games * 22) / L["qb_ypcmp"]
    D["int"] = _shrink((p["int"] * p["w"]).groupby(p["defteam"]).sum(), att, L["qb_int"], s.def_prior_games * 100) / L["qb_int"]
    D["passtd"] = _shrink((p["pass_td"] * p["w"]).groupby(p["defteam"]).sum(), att, L["qb_td"], s.def_prior_games * 100) / L["qb_td"]
    # Pressure: QB hits per attempt (every season) — participation pressure is not published for the current season.
    L["qb_hit"] = float(p["qb_hit"].mean())
    D["pressure"] = _shrink((p["qb_hit"] * p["w"]).groupby(p["defteam"]).sum(), att, L["qb_hit"], s.def_prior_games * 34) / L["qb_hit"]
    # Blitz (FTN, 2022+) and man coverage (participation, through last season): rates, not ratios.
    for col, key in (("blitz", "blitz_rate"), ("man", "man_rate")):
        # Coverage: earlier seasons only (see _coverage_splits).
        x = p[p[col].notna() & ((p["season"] < season) if col == "man" else True)]
        lg = float(x[col].mean()) if len(x) else np.nan
        L[key] = lg
        if len(x):
            D[key] = _shrink((x[col] * x["w"]).groupby(x["defteam"]).sum(), x.groupby("defteam")["w"].sum(), lg, s.def_prior_games * 34)
        else:
            D[key] = np.nan
    ratio_cols = [c for c in D.columns if c not in ("blitz_rate", "man_rate")]
    D = D.fillna({c: 1.0 for c in ratio_cols})
    # League figures are plain play averages; re-centre each ratio so the average defense is exactly 1.
    D[ratio_cols] = D[ratio_cols] / D[ratio_cols].mean()
    return D, L


def _coverage_splits(hp, played, season, s, L) -> pd.DataFrame:
    """Receiver yards per target vs man and vs zone, shrunk to the receiver's own overall rate.

    Uses earlier seasons only: participation (coverage) data for the current season is not
    published while it is being played, so the backtest doesn't get it either."""
    x = hp[hp["man"].notna() & hp["receiver_player_id"].notna() & (hp["season"] < season)]
    if not len(x):
        return pd.DataFrame(columns=["ypt_man_rel", "ypt_zone_rel"])
    sw = np.power(s.season_carry, (season - 1 - x["season"]).clip(0, None))
    x = x.assign(y=x["yards"] * x["complete"] * sw, n=sw)
    g = x.groupby(["receiver_player_id", "man"])[["y", "n"]].sum().unstack("man").fillna(0.0)
    overall = g["y"].sum(axis=1) / g["n"].sum(axis=1).replace(0, np.nan)
    out = pd.DataFrame(index=g.index)
    for v, name in ((1.0, "ypt_man_rel"), (0.0, "ypt_zone_rel")):
        y = g["y"][v] if v in g["y"].columns else 0.0
        n = g["n"][v] if v in g["n"].columns else 0.0
        out[name] = _shrink(y, n, overall, s.rate_prior) / overall
    out.index.name = "player_id"
    return out.replace([np.inf, -np.inf], np.nan)


def _blitz_splits(hp, season, s, L) -> pd.DataFrame:
    """QB yards per attempt when blitzed vs not, shrunk to the QB's own rate (FTN, 2022+)."""
    x = hp[hp["blitz"].notna() & hp["passer_player_id"].notna()]
    if not len(x):
        return pd.DataFrame(columns=["ypa_blitz_rel", "ypa_noblitz_rel"])
    sw = np.power(s.season_carry, (season - x["season"]).clip(0, None))
    x = x.assign(y=x["pass_yards"] * sw, n=sw)
    g = x.groupby(["passer_player_id", "blitz"])[["y", "n"]].sum().unstack("blitz").fillna(0.0)
    overall = g["y"].sum(axis=1) / g["n"].sum(axis=1).replace(0, np.nan)
    out = pd.DataFrame(index=g.index)
    for v, name in ((1.0, "ypa_blitz_rel"), (0.0, "ypa_noblitz_rel")):
        y = g["y"][v] if v in g["y"].columns else 0.0
        n = g["n"][v] if v in g["n"].columns else 0.0
        out[name] = _shrink(y, n, overall, s.rate_prior * 2) / overall
    out.index.name = "player_id"
    return out[overall > 0].replace([np.inf, -np.inf], np.nan)


def _pools(hp: pd.DataFrame, hr: pd.DataFrame) -> dict:
    """Empirical single-play yardage, by position group (the simulation's shape; players scale it)."""
    pools = {}
    comp = hp[hp["complete"] == 1]
    for grp in ("WR", "TE", "RB"):
        pools[f"rec_{grp}"] = comp.loc[comp["group"] == grp, "yards"].to_numpy(float)
    pools["rec_QB"] = pools["rec_RB"]
    pools["pass"] = comp["pass_yards"].to_numpy(float)
    for grp in ("RB", "QB", "WR", "TE"):
        x = hr.loc[hr["group"] == grp, "yards"].to_numpy(float)
        pools[f"rush_{grp}"] = x if len(x) > 200 else hr.loc[hr["group"] == "RB", "yards"].to_numpy(float)
    return pools
