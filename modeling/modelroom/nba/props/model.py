"""NBA player-prop projections: minutes × per-minute production, matchup- and pace-adjusted, then simulated.

At a cutoff date, using only games before it:
  1. Minutes: recency-weighted minutes when the player plays, times how often he has played lately
     (expected minutes). A rotation player who missed his team's last N games is treated as out. The
     active players' expected minutes are scaled so the team's total matches a game's 240 (+ overtime);
     conditional-on-playing minutes are scaled by the same factor. Starters lose a little time in
     projected blowouts (game engine margin).
  2. Rates per minute: 2-point makes, 3-point makes, free throws made, rebounds, assists, steals, blocks.
     Recency-weighted, pulled toward the position group (G / F / C) average.
  3. Matchup: the opponent's allowed per-minute rate to that position group, as a ratio to the league
     (pulled toward 1). Pace: the game engine's projected pace over the team's usual pace.
     Teammates ruled out free up usage, which lifts scoring and assists a little.
  4. Simulation: minutes vary game to game; each stat is Poisson given minutes, with a shared lognormal
     "night" shock for shooting (2s, 3s, free throws move together) and separate shocks for rebounds,
     assists and steals/blocks. Points = 2·2PM + 3·3PM + FTM, so points and threes stay consistent.

Players who don't play are not projected (exchanges settle those props at a fair price).
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import HISTORY_SEASONS, TEAM_MINUTES, PropParams, PropSettings, support_level

RATES = ["fg2m", "fg3m", "ftm", "reb", "ast", "stl", "blk"]
STATS = ["minutes", "pts", "fg3m", "reb", "ast", "stl", "blk", "pra"]
USAGE = ["fga", "fta", "tov"]


@dataclass
class Context:
    cutoff: pd.Timestamp
    season: int
    players: pd.DataFrame
    defense: pd.DataFrame
    team_pace: pd.Series
    league: dict


@dataclass
class PlayerProjection:
    player_id: str
    name: str
    team: str
    opp: str
    group: str
    game_id: str
    sims: dict
    inputs: dict

    def prob(self, stat: str, k: float, op: str = ">=") -> float:
        x = self.sims[stat]
        return float(np.mean(x > k) if op == ">" else np.mean(x >= k))

    def mean(self, stat: str) -> float:
        return float(np.mean(self.sims[stat]))

    def sd(self, stat: str) -> float:
        return float(np.std(self.sims[stat]))

    def support(self, market: str | None = None) -> tuple[str, str]:
        s = self.inputs.get("sample", {})
        return support_level(int(s.get("games", 0)), float(s.get("minutes", 0)))

    @property
    def position(self) -> str:
        return self.group


def _recency(df: pd.DataFrame, key: str, hl: float, carry: float, season: int) -> np.ndarray:
    k = df.groupby(key, sort=False).cumcount(ascending=False).to_numpy(float)
    gap = (season - df["season"].to_numpy(int)).clip(0, None)
    return np.power(0.5, k / hl) * np.power(carry, gap)


def build(pg: pd.DataFrame, pace: pd.DataFrame, cutoff: pd.Timestamp, season: int, s: PropSettings) -> Context:
    """pace: per game_id, possessions-per-48 (from the game engine's box-score features)."""
    d = pd.to_datetime(pg["game_date"])
    H = pg[(d < cutoff) & (pg["season"] >= season - HISTORY_SEASONS)].sort_values(["game_date", "game_id"])
    P = H[H["played"]]

    # ------------------------------------------------------------ league + defense vs position
    lg_min = P.groupby("group")["minutes"].sum()
    league = {g: {r: float(P.loc[P["group"] == g, r].sum() / lg_min[g]) for r in RATES} for g in lg_min.index}
    opp_games = P.drop_duplicates(["game_id", "opp"])[["game_id", "opp", "season", "game_date"]].sort_values("game_date")
    opp_games["w"] = _recency(opp_games, "opp", s.def_half_life, s.season_carry, season)
    w = P.merge(opp_games[["game_id", "opp", "w"]], on=["game_id", "opp"], how="left")["w"].fillna(0).to_numpy()
    rows = []
    for (opp, grp), g in P.assign(w=w).groupby(["opp", "group"]):
        mins = float((g["minutes"] * g["w"]).sum())
        row = {"opp": opp, "group": grp}
        for r in RATES:
            lg = league[grp][r]
            num = float((g[r] * g["w"]).sum())
            row[r] = ((num + lg * s.def_prior_minutes) / (mins + s.def_prior_minutes)) / lg if lg > 0 else 1.0
        rows.append(row)
    D = pd.DataFrame(rows).set_index(["opp", "group"])
    D = D / D.groupby(level="group").transform("mean")  # average defense = 1 for each position group

    # ------------------------------------------------------------ team pace (possessions per 48)
    tp = H.drop_duplicates(["game_id", "team"])[["game_id", "team", "season", "game_date"]].merge(pace, on="game_id", how="inner")
    tp = tp.sort_values("game_date")
    tp["w"] = _recency(tp, "team", 10.0, s.season_carry, season)
    team_pace = (tp["pace"] * tp["w"]).groupby(tp["team"]).sum() / tp.groupby("team")["w"].sum()

    # ------------------------------------------------------------ players
    wr = _recency(P, "player_id", s.rate_half_life, s.season_carry, season)
    wm = _recency(P, "player_id", s.minutes_half_life, 0.25, season)
    X = P[RATES + USAGE].to_numpy(float) * wr[:, None]
    agg = pd.DataFrame(X, columns=RATES + USAGE, index=P.index).assign(player_id=P["player_id"].to_numpy())
    agg["wmin"] = P["minutes"].to_numpy() * wr
    agg = agg.groupby("player_id").sum()
    mins = (pd.Series(P["minutes"].to_numpy() * wm, index=P.index).groupby(P["player_id"]).sum()
            / pd.Series(wm, index=P.index).groupby(P["player_id"]).sum())
    last = P.groupby("player_id").tail(1).set_index("player_id")
    out = pd.DataFrame(index=agg.index)
    out["name"] = last["name"]
    out["team"] = last["team"]
    out["group"] = last["group"]
    out["last_game"] = pd.to_datetime(last["game_date"])
    out["minutes_when_playing"] = mins
    out["starter_rate"] = (pd.Series(P["starter"].astype(float).to_numpy() * wm, index=P.index).groupby(P["player_id"]).sum()
                           / pd.Series(wm, index=P.index).groupby(P["player_id"]).sum())
    for r in RATES:
        lg = out["group"].map(lambda g: league.get(g, league["F"])[r])
        out[f"{r}_pm"] = (agg[r] + lg * s.rate_prior_minutes) / (agg["wmin"] + s.rate_prior_minutes)
    out["usage_pm"] = (agg["fga"] + 0.44 * agg["fta"] + agg["tov"]) / agg["wmin"].replace(0, np.nan)
    out["n_games"] = P.groupby("player_id").size()
    out["n_minutes"] = P.groupby("player_id")["minutes"].sum()

    # Availability: share of the team's last 10 games he played (since joining), and games missed in a row.
    team_games = H.drop_duplicates(["game_id", "team"])[["game_id", "team", "game_date"]].sort_values("game_date")
    team_games["k"] = team_games.groupby("team").cumcount(ascending=False)  # 0 = team's most recent game
    recent = team_games[team_games["k"] < 10]
    hk = H.merge(recent[["game_id", "team", "k"]], on=["game_id", "team"], how="inner")
    first_k = hk.groupby("player_id")["k"].max()  # earliest of the last 10 team games he was on the roster for
    played_k = hk[hk["played"]].groupby("player_id")["k"]
    out["appear_rate"] = (played_k.size() / (first_k + 1)).reindex(out.index).fillna(0.0).clip(0, 1)
    out["missed_in_row"] = played_k.min().reindex(out.index)  # team games since his last appearance
    on_team_now = recent[recent["k"] == 0].set_index("team")["game_id"]
    out["listed_last_game"] = out.index.isin(set(H[H["game_id"].isin(set(on_team_now))]["player_id"]))
    return Context(cutoff, season, out, D, team_pace, {"rates": league, "pace": float(np.nanmean(team_pace)) if len(team_pace) else 99.0})


def _shock(rng, sd: float, n: int) -> np.ndarray:
    return np.exp(rng.normal(-0.5 * sd * sd, sd, n)) if sd > 0 else np.ones(n)


def candidates(ctx: Context, team: str, s: PropSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(active, ruled out) players for a team. Out = a rotation player who missed the team's last N games."""
    c = ctx.players[(ctx.players["team"] == team) & (ctx.cutoff - ctx.players["last_game"] <= pd.Timedelta(days=60))].copy()
    rotation = c["minutes_when_playing"] >= 12
    out = c[rotation & (c["missed_in_row"].fillna(99) >= s.missed_games_out)]
    active = c.drop(out.index)
    active = active[active["appear_rate"] > 0]
    return active, out


def project_team(ctx: Context, game_id: str, team: str, opp: str, margin: float, pace: float | None, p: PropParams,
                 rng) -> list[PlayerProjection]:
    s = p.settings
    n = s.sims
    active, out = candidates(ctx, team, s)
    if active.empty:
        return []
    exp_min = active["minutes_when_playing"] * active["appear_rate"]
    scale = float(np.clip(TEAM_MINUTES / exp_min.sum(), 0.85, 1.25)) if exp_min.sum() > 0 else 1.0
    base = (active["minutes_when_playing"] * scale).clip(upper=42.0)
    blow = max(0.0, abs(margin) - 6.0) * s.blowout_strength
    base = base * np.where(active["starter_rate"] > 0.5, 1 - blow, 1.0)
    # Usage freed by ruled-out teammates (share of the team's usage they normally take).
    team_usage = float((active["usage_pm"].fillna(0) * active["minutes_when_playing"] * active["appear_rate"]).sum())
    out_usage = float((out["usage_pm"].fillna(0) * out["minutes_when_playing"] * out["appear_rate"]).sum())
    freed = out_usage / (team_usage + out_usage) if team_usage + out_usage > 0 else 0.0
    usage_f = 1.0 + s.usage_boost * freed
    tp = ctx.team_pace.get(team, ctx.league["pace"])
    pace_f = (float(pace) / tp) ** s.pace_strength if pace and tp else 1.0
    res = []
    for pid, x in active.iterrows():
        grp = x["group"]
        dfn = ctx.defense.loc[(opp, grp)] if (opp, grp) in ctx.defense.index else None

        def opp_f(r):
            return float(dfn[r]) ** s.matchup_strength if dfn is not None else 1.0

        m = np.clip(rng.normal(base[pid], s.minutes_sd, n), 1.0, 48.0)
        sh_score = _shock(rng, s.scoring_sd, n) * usage_f
        sh_reb, sh_ast, sh_stk = _shock(rng, s.rebound_sd, n), _shock(rng, s.assist_sd, n) * usage_f ** 0.5, _shock(rng, s.stock_sd, n)
        lam = lambda r, sh: x[f"{r}_pm"] * m * pace_f * opp_f(r) * sh  # noqa: E731
        fg2 = rng.poisson(lam("fg2m", sh_score))
        fg3 = rng.poisson(lam("fg3m", sh_score))
        ft = rng.poisson(lam("ftm", sh_score))
        sims = {"minutes": m, "fg3m": fg3.astype(float), "pts": (2 * fg2 + 3 * fg3 + ft).astype(float),
                "reb": rng.poisson(lam("reb", sh_reb)).astype(float), "ast": rng.poisson(lam("ast", sh_ast)).astype(float),
                "stl": rng.poisson(lam("stl", sh_stk)).astype(float), "blk": rng.poisson(lam("blk", sh_stk)).astype(float)}
        sims["pra"] = sims["pts"] + sims["reb"] + sims["ast"]
        inputs = {"projected_minutes": round(float(base[pid]), 1), "minutes_scale": round(scale, 3), "pace_factor": round(pace_f, 3),
                  "usage_freed_by_absences": round(freed, 3), "starter_rate": round(float(x["starter_rate"]), 2),
                  "appear_rate_last10": round(float(x["appear_rate"]), 2),
                  "teammates_out": ", ".join(out["name"].astype(str).tolist()) or None,
                  "opp_points_factor": round(opp_f("fg2m"), 3), "opp_rebounds_factor": round(opp_f("reb"), 3),
                  "opp_assists_factor": round(opp_f("ast"), 3),
                  "sample": {"games": int(x["n_games"]), "minutes": round(float(x["n_minutes"]), 0)}}
        res.append(PlayerProjection(pid, str(x["name"]), team, opp, grp, game_id, sims, inputs))
    return res


def project_games(ctx: Context, games: pd.DataFrame, p: PropParams, seed: int) -> list[PlayerProjection]:
    """games: game_id, home_abbr, away_abbr, proj_margin (home), proj_pace. Seeded per (seed, game, team)."""
    out = []
    for _, g in games.iterrows():
        for team, opp, mg in ((g["home_abbr"], g["away_abbr"], g["proj_margin"]), (g["away_abbr"], g["home_abbr"], -g["proj_margin"])):
            rng = np.random.default_rng([seed, zlib.crc32(f"{g['game_id']}|{team}".encode())])
            out += project_team(ctx, str(g["game_id"]), team, opp, float(mg) if pd.notna(mg) else 0.0,
                                g.get("proj_pace"), p, rng)
    return out
