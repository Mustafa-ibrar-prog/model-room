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

import itertools
import os
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
    out["minutes_high"] = (P.groupby("player_id").tail(10).groupby("player_id")["minutes"].quantile(0.9)).reindex(out.index)
    if s.rate_prior_kind == "role":
        # Prior = per-minute rate of players at the same position in the same minutes band (as of the cutoff).
        band = pd.cut(out["minutes_when_playing"], [0, 15, 22, 28, 34, 60], labels=False).fillna(0).astype(int)
        pb = pd.Series(band.reindex(P["player_id"]).to_numpy(), index=P.index)
        role_min = P.groupby([P["group"], pb])["minutes"].sum()
    for r in RATES:
        lg = out["group"].map(lambda g: league.get(g, league["F"])[r])
        if s.rate_prior_kind == "role":
            role_rate = (P.groupby([P["group"], pb])[r].sum() / role_min).rename("rr")
            key = pd.MultiIndex.from_arrays([out["group"], band])
            lg = pd.Series(role_rate.reindex(key).to_numpy(), index=out.index).fillna(lg)
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


_AUDIT_PARTS = os.environ.get("MODELROOM_AUDIT_USAGE_PARTS") == "1"

# Each published stat as per-minute rates: (rate, coefficient, power of the usage factor on it). Points use the scoring
# shock (usage^1) on fg2m / fg3m / ftm, assists usage^0.5, the rest none; exactly as in project_team's simulation.
CONTRIB_PARTS = {
    "pts": [("fg2m", 2.0, 1.0), ("fg3m", 3.0, 1.0), ("ftm", 1.0, 1.0)],
    "fg3m": [("fg3m", 1.0, 1.0)],
    "reb": [("reb", 1.0, 0.0)],
    "ast": [("ast", 1.0, 0.5)],
    "stl": [("stl", 1.0, 0.0)],
    "blk": [("blk", 1.0, 0.0)],
}
CONTRIB_PARTS["pra"] = CONTRIB_PARTS["pts"] + CONTRIB_PARTS["reb"] + CONTRIB_PARTS["ast"]
CONTRIB_VERSION = 1


def contributions(x: pd.Series, mwp0: float | None, base_pid: float, starter_rate: float, margin: float, s: PropSettings,
                  pace_f: float, opp_f, uf, sims: dict, scenarios: bool) -> dict:
    """Measured contribution of each existing adjustment to one player's mean, per published stat (bookkeeping only).

    The model's mean is rate x minutes x usage x pace x matchup (each a multiplier on the per-minute rate). Starting from
    his history (recency-weighted rates x his usual minutes when he plays), the adjustments are applied one at a time in
    this fixed order and each step's change in the expected value is recorded: minutes (the fill to the team's 240,
    which includes minutes freed by absent teammates; the two are not separable), the blowout cut, the usage boost from
    teammates ruled out, pace, opponent defense. The steps add up exactly to the deterministic expectation; what remains
    to the simulated mean ("simulation") is minutes clipping to 1-48 and random variation. Steps are order-dependent
    (a multiplicative chain), so they are an attribution in this order, not unique causes. With lineup scenarios (not
    used by the active version) the minutes / usage steps can't be isolated and are marked unavailable."""
    out = {"version": CONTRIB_VERSION, "order": ["baseline", "minutes", "blowout", "usage", "pace", "matchup", "simulation"], "stats": {}}
    if scenarios or mwp0 is None or not np.isfinite(mwp0):
        out["unavailable"] = "lineup scenarios or no usual-minutes figure: adjustments not isolated"
        return out
    blow = max(0.0, abs(float(margin)) - 6.0) * s.blowout_strength
    b_fill = base_pid / (1.0 - blow) if starter_rate > 0.5 and blow < 1.0 else base_pid
    u = float(np.mean(uf))
    for stat, parts in CONTRIB_PARTS.items():
        def mu(minutes, usage=False, pace=False, opp=False):
            t = 0.0
            for r, c, pw in parts:
                v = float(x[f"{r}_pm"]) * c * minutes
                if usage:
                    v *= u ** pw
                if pace:
                    v *= pace_f
                if opp:
                    v *= opp_f(r)
                t += v
            return t
        vals = [mu(mwp0), mu(b_fill), mu(base_pid), mu(base_pid, True), mu(base_pid, True, True), mu(base_pid, True, True, True)]
        if not all(np.isfinite(vals)):
            out["stats"][stat] = None
            continue
        final = float(np.mean(sims[stat]))
        out["stats"][stat] = {"baseline": round(vals[0], 3), "minutes": round(vals[1] - vals[0], 3), "blowout": round(vals[2] - vals[1], 3),
                              "usage": round(vals[3] - vals[2], 3), "pace": round(vals[4] - vals[3], 3), "matchup": round(vals[5] - vals[4], 3),
                              "simulation": round(final - vals[5], 3), "final": round(final, 3)}
    out["minutes"] = {"usual": round(mwp0, 2), "after_fill": round(b_fill, 2), "projected": round(base_pid, 2)}
    return out


def _shock(rng, sd: float, n: int) -> np.ndarray:
    return np.exp(rng.normal(-0.5 * sd * sd, sd, n)) if sd > 0 else np.ones(n)


def candidates(ctx: Context, team: str, s: PropSettings, avail: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(active, ruled out) players for a team. Out = a rotation player who missed the team's last N games.

    With the injury feed (0.2.1, `avail` = this game's availability, see availability()): a current Out /
    Doubtful designation rules a player out whatever his streak; Questionable / Probable / Available (or not
    listed on the team's submitted official report) keeps him in even after missed games, as a returning
    player. Players with no current information fall back to the streak rule: missing data is never read
    as healthy or as out. Ruled-out rows carry `out_weight` (Doubtful counts partly)."""
    c = ctx.players[(ctx.players["team"] == team) & (ctx.cutoff - ctx.players["last_game"] <= pd.Timedelta(days=60))].copy()
    rotation = c["minutes_when_playing"] >= 12
    streak = c["missed_in_row"].fillna(99) >= s.missed_games_out
    if not (s.injury_feed and avail):
        out = c[rotation & streak]
        active = c.drop(out.index)
        active = active[active["appear_rate"] > 0]
        return active, out.assign(out_weight=1.0)
    players = avail.get("players", {})
    st = pd.Series({pid: (players.get(str(pid)) or {}).get("status") for pid in c.index}, dtype=object)
    ruled = st.isin(["out", "doubtful"])
    cleared = st.isin(["questionable", "probable", "available"]) | (st.isna() & bool(avail.get("submitted")) & s.unlisted_clears)
    out_mask = ruled | (rotation & streak & ~cleared)
    out = c[out_mask].copy()
    out = out[rotation[out.index] | ruled[out.index]]
    out["out_weight"] = np.where(st[out.index] == "doubtful", s.doubtful_weight, 1.0)
    active = c[~out_mask]
    active = active[(active["appear_rate"] > 0) | cleared[active.index]]
    return active, out


def availability(team_feed: pd.DataFrame | None, back: dict, submitted: bool, starters: set | None) -> dict:
    """This team-game's availability from the injury feed rows (current, not stale): {players: {id: {...}},
    submitted, starters}."""
    players = {}
    if team_feed is not None:
        for r in team_feed.itertuples():
            players[str(r.player_id)] = {"status": r.status, "raw_status": r.raw_status, "source": r.source, "kind": r.kind,
                                         "report_time": None if pd.isna(r.report_time) else pd.Timestamp(r.report_time).isoformat(),
                                         "restriction": bool(r.restriction), "restriction_minutes": None if pd.isna(r.restriction_minutes) else float(r.restriction_minutes),
                                         "late_scratch": bool(getattr(r, "late_scratch", False)), "conflict": getattr(r, "conflict", None) or None,
                                         "detail": r.detail if isinstance(r.detail, str) else None}
    return {"players": players, "back": back, "submitted": submitted, "starters": starters}


def project_team(ctx: Context, game_id: str, team: str, opp: str, margin: float, pace: float | None, p: PropParams,
                 rng, avail: dict | None = None) -> list[PlayerProjection]:
    s = p.settings
    n = s.sims
    active, out = candidates(ctx, team, s, avail)
    if active.empty:
        return []
    feed_on = bool(s.injury_feed and avail)
    sd_f = pd.Series(1.0, index=active.index)
    notes: dict = {}
    if feed_on:
        # Returning players (1st-3rd game after missing 3+) play fewer, less predictable minutes (measured); a
        # stated minutes restriction caps them. Done before the minutes fill, so the gap goes to teammates.
        active = active.copy()
        info = avail["players"]
        for pid in active.index:
            k = str(pid)
            nb = 1 if active.at[pid, "missed_in_row"] >= 3 else (avail["back"].get(k, 99) + 1)
            f = 1.0
            if s.return_minutes and 1 <= nb <= len(s.return_minutes):
                f = float(s.return_minutes[nb - 1])
                sd_f[pid] = float(s.return_sd_factor[nb - 1]) if s.return_sd_factor else 1.0
                notes.setdefault(pid, []).append(f"game {nb} back from a {int(active.at[pid, 'missed_in_row']) if nb == 1 else 3}+ game absence: minutes x{f:.2f}")
            r = info.get(k) or {}
            if s.play_prob_available:
                # 0.2.2: the report status sets a probability of playing (measured by role on 2023-24 reports), never a
                # certainty: Available bench players often still don't play.
                band = int(np.searchsorted(np.asarray(s.play_bands, float), float(active.at[pid, "minutes_when_playing"]), side="right"))
                if r.get("status") in ("available", "probable"):
                    active.at[pid, "appear_rate"] = float(s.play_prob_available[band])
                elif r.get("status") == "questionable" and s.play_prob_questionable:
                    active.at[pid, "appear_rate"] = float(s.play_prob_questionable[band])
            elif r.get("status") in ("available", "probable") or (nb == 1 and (r.get("status") is None or r.get("status") != "questionable")):
                # Expected to play: his recent appearance rate (low after an absence) no longer applies.
                active.at[pid, "appear_rate"] = 1.0
            cap = r.get("restriction_minutes")
            mwp = float(active.at[pid, "minutes_when_playing"])
            new_m = mwp * f
            if cap:
                new_m = min(new_m, float(cap))
                notes.setdefault(pid, []).append(f"minutes restriction reported (~{cap:.0f})")
            elif r.get("restriction"):
                notes.setdefault(pid, []).append("minutes restriction reported, amount not given")
                if nb > len(s.return_minutes or ()) and s.return_minutes:
                    new_m = min(new_m, mwp * float(s.return_minutes[0]))
                    sd_f[pid] = float(s.return_sd_factor[0]) if s.return_sd_factor else 1.0
            if new_m != mwp:
                active.at[pid, "minutes_when_playing"] = new_m
                active.at[pid, "minutes_high"] = min(float(active.at[pid, "minutes_high"]) if pd.notna(active.at[pid, "minutes_high"]) else new_m, new_m + 4.0)
        if avail.get("starters"):
            active["starter_rate"] = [1.0 if str(pid) in avail["starters"] else 0.0 for pid in active.index]
    fade = np.power(0.5, out["missed_in_row"].fillna(0).to_numpy(float) / s.rate_half_life) if s.usage_decay > 0 else 1.0
    fade = fade ** s.usage_decay if s.usage_decay > 0 else fade
    ow = out["out_weight"].to_numpy(float) if "out_weight" in out else 1.0
    out_usage0 = float((out["usage_pm"].fillna(0) * out["minutes_when_playing"] * out["appear_rate"] * fade * ow).sum())

    def fill(ap: pd.Series, gone: list) -> tuple[pd.Series, float, float]:
        """Minutes when playing (filled to the team's 240) and usage freed, given each player's chance of playing `ap`
        and the uncertain players sitting in this lineup (`gone`)."""
        exp_min = active["minutes_when_playing"] * ap
        if s.minutes_fill == "headroom" and exp_min.sum() > 0:
            mwp = active["minutes_when_playing"]
            gap = TEAM_MINUTES - float(exp_min.sum())
            if gap > 0 and s.minutes_gap_fill != 1.0:
                gap = max(gap * s.minutes_gap_fill, 1e-9)   # still the "room to fill" branch, never the scale-up one
            if gap > 0:
                cap = np.minimum(42.0, np.maximum(active["minutes_high"].fillna(mwp), mwp + 4.0))
                room = ((cap - mwp).clip(lower=0) * ap)
                add = room / room.sum() * min(gap, float(room.sum())) if room.sum() > 0 else 0.0
                base = mwp + (add / ap.clip(lower=0.2))
                base = np.minimum(base, cap)
            else:
                base = mwp * (TEAM_MINUTES / float(exp_min.sum()))
            scale = float(np.average(base / mwp.replace(0, np.nan), weights=exp_min)) if exp_min.sum() > 0 else 1.0
            base = base.clip(upper=42.0)
        else:
            scale = float(np.clip(TEAM_MINUTES / exp_min.sum(), 0.85, 1.25)) if exp_min.sum() > 0 else 1.0
            base = (active["minutes_when_playing"] * scale).clip(upper=42.0)
        blow = max(0.0, abs(margin) - 6.0) * s.blowout_strength
        base = base * np.where(active["starter_rate"] > 0.5, 1 - blow, 1.0)
        # Usage freed by ruled-out teammates (share of the team's usage they normally take), plus uncertain players
        # who sit in this lineup.
        team_usage = float((active["usage_pm"].fillna(0) * active["minutes_when_playing"] * ap).sum())
        out_usage = out_usage0 + float(sum(float(active.at[g, "usage_pm"] or 0) * float(active.at[g, "minutes_when_playing"]) for g in gone if pd.notna(active.at[g, "usage_pm"])))
        freed = out_usage / (team_usage + out_usage) if team_usage + out_usage > 0 else 0.0
        return base, scale, freed

    base, scale, freed = fill(active["appear_rate"], [])
    usage_f = 1.0 + s.usage_boost * freed
    parts = None
    if _AUDIT_PARTS and feed_on:
        # Audit only (never set on the site): the ingredients of the freed-usage share, for refitting it offline.
        st_ = {str(k): (v or {}).get("status") for k, v in avail["players"].items()}
        parts = {"T_w": float((active["usage_pm"].fillna(0) * active["minutes_when_playing"] * active["appear_rate"]).sum()),
                 "T_u": float((active["usage_pm"].fillna(0) * active["minutes_when_playing"]).sum()),
                 "out": [(float(o["usage_pm"] if pd.notna(o["usage_pm"]) else 0) * float(o["minutes_when_playing"]), float(o["appear_rate"]),
                          float(o["out_weight"]) if "out_weight" in out else 1.0, float(o["missed_in_row"]) if pd.notna(o["missed_in_row"]) else -1.0,
                          st_.get(str(oid))) for oid, o in out.iterrows()]}
    # 0.2.2 lineup scenarios: the most consequential uncertain rotation players either play or sit; every lineup is
    # filled on its own, so a healthy starter only loses minutes in the lineups where the uncertain player plays.
    U: list = []
    if s.lineup_scenarios and feed_on:
        ar = active["appear_rate"]
        unc = active[(ar > 0.05) & (ar < 0.95) & (active["minutes_when_playing"] >= 12)]
        U = list((unc["minutes_when_playing"] * np.minimum(unc["appear_rate"], 1 - unc["appear_rate"])).nlargest(s.lineup_scenarios).index)
    if U:
        sc_p, sc_play, sc_base, sc_freed = [], [], [], []
        for bits in itertools.product((1, 0), repeat=len(U)):
            ap = active["appear_rate"].copy()
            pr = 1.0
            for u, b in zip(U, bits):
                pr *= float(ap[u]) if b else 1.0 - float(ap[u])
                ap[u] = float(b)
            b_, _, f_ = fill(ap, [u for u, b in zip(U, bits) if not b])
            sc_p.append(pr), sc_play.append(bits), sc_base.append(b_.to_numpy(float)), sc_freed.append(f_)
        sc_p, sc_play, sc_base, sc_freed = np.array(sc_p), np.array(sc_play, float), np.vstack(sc_base), np.array(sc_freed)
        col = {pid: i for i, pid in enumerate(active.index)}
    tp = ctx.team_pace.get(team, ctx.league["pace"])
    pace_f = (float(pace) / tp) ** s.pace_strength if pace and tp else 1.0
    res = []
    for pid, x in active.iterrows():
        grp = x["group"]
        dfn = ctx.defense.loc[(opp, grp)] if (opp, grp) in ctx.defense.index else None

        def opp_f(r):
            return float(dfn[r]) ** s.matchup_strength if dfn is not None else 1.0

        if U:
            w = sc_p * (sc_play[:, U.index(pid)] if pid in U else 1.0)   # props are graded only if he plays
            w = w / w.sum()
            idx = rng.choice(len(w), n, p=w)
            m = np.clip(rng.normal(sc_base[idx, col[pid]], s.minutes_sd * float(sd_f.get(pid, 1.0)), n), 1.0, 48.0)
            uf = 1.0 + s.usage_boost * sc_freed[idx]
            base_pid = float(w @ sc_base[:, col[pid]])
        else:
            m = np.clip(rng.normal(base[pid], s.minutes_sd * float(sd_f.get(pid, 1.0)), n), 1.0, 48.0)
            uf = usage_f
            base_pid = float(base[pid])
        sh_score = _shock(rng, s.scoring_sd, n) * uf
        sh_reb, sh_ast, sh_stk = _shock(rng, s.rebound_sd, n), _shock(rng, s.assist_sd, n) * uf ** 0.5, _shock(rng, s.stock_sd, n)
        lam = lambda r, sh: x[f"{r}_pm"] * m * pace_f * opp_f(r) * sh  # noqa: E731
        fg2 = rng.poisson(lam("fg2m", sh_score))
        fg3 = rng.poisson(lam("fg3m", sh_score))
        ft = rng.poisson(lam("ftm", sh_score))
        sims = {"minutes": m, "fg3m": fg3.astype(float), "pts": (2 * fg2 + 3 * fg3 + ft).astype(float),
                "reb": rng.poisson(lam("reb", sh_reb)).astype(float), "ast": rng.poisson(lam("ast", sh_ast)).astype(float),
                "stl": rng.poisson(lam("stl", sh_stk)).astype(float), "blk": rng.poisson(lam("blk", sh_stk)).astype(float)}
        sims["pra"] = sims["pts"] + sims["reb"] + sims["ast"]
        # Bookkeeping only (P3): the measured contribution of each existing adjustment to the mean, from values already
        # computed above. No random draws and nothing fed back into the simulation.
        contrib = contributions(x, float(ctx.players.at[pid, "minutes_when_playing"]) if pid in ctx.players.index else None,
                                base_pid, float(active.at[pid, "starter_rate"]), margin, s, pace_f, opp_f, uf, sims, bool(U))
        inputs = {"projected_minutes": round(base_pid, 1), "minutes_scale": round(scale, 3), "pace_factor": round(pace_f, 3),
                  "usage_freed_by_absences": round(float(np.mean(uf) - 1.0) / s.usage_boost if U and s.usage_boost else freed, 3), "starter_rate": round(float(x["starter_rate"]), 2),
                  "appear_rate_last10": round(float(x["appear_rate"]), 2),
                  "teammates_out": ", ".join(out["name"].astype(str).tolist()) or None,
                  **({"uncertain_teammates": [{"name": str(active.at[u, "name"]), "play_prob": round(float(active.at[u, "appear_rate"]), 2)}
                                              for u in U if u != pid]} if U else {}),
                  "opp_points_factor": round(opp_f("fg2m"), 3), "opp_rebounds_factor": round(opp_f("reb"), 3),
                  "opp_assists_factor": round(opp_f("ast"), 3),
                  "sample": {"games": int(x["n_games"]), "minutes": round(float(x["n_minutes"]), 0)},
                  "contributions": contrib}
        if feed_on:
            me = avail["players"].get(str(pid)) or {}
            inputs["availability"] = {"status": me.get("status"), "raw_status": me.get("raw_status"), "source": me.get("source"),
                                      "confirmed": me.get("kind") == "official", "report_time": me.get("report_time"),
                                      "late_scratch": me.get("late_scratch"), "conflict": me.get("conflict"),
                                      "starter_confirmed": (str(pid) in avail["starters"]) if avail.get("starters") else None,
                                      "notes": notes.get(pid, [])}
            inputs["teammates_out_detail"] = [{"name": str(o["name"]), "status": (avail["players"].get(str(oid)) or {}).get("status") or "missed recent games",
                                               "source": (avail["players"].get(str(oid)) or {}).get("source") or "box scores",
                                               "weight": round(float(o["out_weight"]), 2)} for oid, o in out.iterrows()]
        if parts is not None:
            inputs["usage_parts"] = parts
            inputs["usage_f_mean"] = float(np.mean(uf))
        res.append(PlayerProjection(pid, str(x["name"]), team, opp, grp, game_id, sims, inputs))
    return res


def project_games(ctx: Context, games: pd.DataFrame, p: PropParams, seed: int, avail: dict | None = None) -> list[PlayerProjection]:
    """games: game_id, home_abbr, away_abbr, proj_margin (home), proj_pace. Seeded per (seed, game, team).
    avail: {(game_id, team): availability(...)} when the injury feed is used (0.2.1)."""
    out = []
    for _, g in games.iterrows():
        for team, opp, mg in ((g["home_abbr"], g["away_abbr"], g["proj_margin"]), (g["away_abbr"], g["home_abbr"], -g["proj_margin"])):
            rng = np.random.default_rng([seed, zlib.crc32(f"{g['game_id']}|{team}".encode())])
            out += project_team(ctx, str(g["game_id"]), team, opp, float(mg) if pd.notna(mg) else 0.0,
                                g.get("proj_pace"), p, rng, (avail or {}).get((str(g["game_id"]), team)))
    return out
