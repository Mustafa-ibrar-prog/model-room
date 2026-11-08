"""NFL player-prop projections: volume × share × efficiency, matchup-adjusted, then simulated.

For each team in a game
  1. Team pass attempts and carries come from the team's base rates, what the opponent usually faces,
     and the game engine's projected margin and total (trailing teams throw more).
  2. Each active player's target / carry share comes from his recent usage, nudged by his recent snap
     share and by how much this defense funnels targets to his position. Players ruled Out or Doubtful
     are removed and their share is spread over the active players.
  3. Efficiency (catch rate, yards per catch / carry, TD rates; QB completion %, INT and TD rates) is the
     player's shrunk rate × the opponent's allowed ratio for his position, × his man/zone split against
     this defense's coverage mix, × the QB's blitz split against this defense's blitz rate.
  4. Every player is simulated N times. One simulation set gives every threshold of every market.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .config import PropParams
from .features import Context

OUT_STATUSES = {"Out", "Doubtful"}
ACTIVE_ROSTER = {"ACT", "INA"}
STATS = ["pass_att", "pass_cmp", "pass_yds", "pass_td", "ints", "carries", "rush_yds", "rush_td", "targets",
         "receptions", "rec_yds", "rec_td", "long_rec", "rush_rec_yds", "td_any", "fantasy_ppr", "fantasy_sleeper"]


@dataclass
class PlayerProjection:
    player_id: str
    name: str
    team: str
    opp: str
    group: str
    game_id: str
    sims: dict[str, np.ndarray]
    inputs: dict

    def prob(self, stat: str, threshold: float, op: str = ">=") -> float:
        x = self.sims[stat]
        return float(np.mean(x > threshold) if op == ">" else np.mean(x >= threshold))

    def mean(self, stat: str) -> float:
        return float(np.mean(self.sims[stat]))

    def sd(self, stat: str) -> float:
        return float(np.std(self.sims[stat]))

    def support(self, market: str) -> tuple[str, str]:
        from .config import support_level

        return support_level(market, self.group, self.inputs.get("sample", {}))


def _pool_sum(rng, pool: np.ndarray, counts: np.ndarray, scale: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    """Sum and max of `counts` draws from `pool` per simulation, scaled."""
    kmax = int(counts.max()) if counts.size else 0
    if kmax == 0 or pool.size == 0:
        z = np.zeros(counts.shape, float)
        return z, z
    draws = rng.choice(pool, size=(counts.size, kmax)) * (np.asarray(scale)[..., None] if np.ndim(scale) else scale)
    mask = np.arange(kmax)[None, :] < counts[:, None]
    total = np.where(mask, draws, 0.0).sum(axis=1)
    longest = np.where(mask, draws, -np.inf).max(axis=1)
    longest = np.where(counts > 0, longest, 0.0)
    return total, longest


def _beta_share(rng, mean: float, kappa: float, n: int) -> np.ndarray:
    m = float(np.clip(mean, 1e-4, 0.999))
    return rng.beta(m * kappa, (1 - m) * kappa, size=n)


def _shock(rng, sd: float, n: int, kind: str = "lognormal") -> np.ndarray:
    """Mean-one multiplier: a good or bad day for this player, shared across his plays.
    lognormal = right-skewed (0.1); normal = symmetric, floored at 0.1 (0.2 option)."""
    if sd <= 0:
        return np.ones(n)
    if kind == "normal":
        return np.clip(1.0 + rng.normal(0.0, sd, n), 0.1, None)
    return np.exp(rng.normal(-0.5 * sd * sd, sd, n))


def _esd(s, fam: str) -> float:
    v = getattr(s, f"eff_sd_{fam}")
    return s.efficiency_sd if v < 0 else v


def _ratio(d: pd.Series | None, key: str, power: float) -> float:
    if d is None or key not in d or pd.isna(d[key]):
        return 1.0
    return float(d[key]) ** power


def team_volume(ctx: Context, team: str, opp: str, margin: float, total: float, p: PropParams) -> tuple[float, float]:
    T = ctx.teams
    base_pa = float(T["pa_base"].get(team, T["pa_base"].mean()))
    base_ru = float(T["ru_base"].get(team, T["ru_base"].mean()))
    faced_pa = float(T["pa_faced"].get(opp, 0.0))
    faced_ru = float(T["ru_faced"].get(opp, 0.0))
    a, b = p.volume.pass_coef, p.volume.rush_coef
    pa = a[0] + a[1] * base_pa + a[2] * faced_pa + a[3] * margin + a[4] * total
    ru = b[0] + b[1] * base_ru + b[2] * faced_ru + b[3] * margin + b[4] * total
    return max(pa, 12.0), max(ru, 8.0)


def candidates(ctx: Context, team: str, roster: pd.DataFrame | None, injuries: pd.DataFrame | None,
               gameday: bool = False) -> pd.DataFrame:
    """Players expected to be available for this team, with the reason any were left out."""
    P = ctx.players
    if roster is not None and len(roster):
        # gameday=True: the official inactive list is out (~90 min before kickoff), so INA players are known not to play.
        r = roster[(roster["team"] == team) & roster["status"].isin({"ACT"} if gameday else ACTIVE_ROSTER)]
        ids = set(r["gsis_id"])
        c = P[P.index.isin(ids)].copy()
    else:
        recent = ctx.cutoff - pd.Timedelta(days=35)
        c = P[(P["team_last"] == team) & (P["last_game"] >= recent)].copy()
    c["injury_status"] = None
    if injuries is not None and len(injuries):
        inj = injuries[injuries["team"] == team].set_index("gsis_id")["report_status"]
        c["injury_status"] = c.index.map(inj)
    c["out"] = c["injury_status"].isin(OUT_STATUSES)
    return c


def play_chance(c: pd.DataFrame, s, depth: dict | None = None) -> pd.Series:
    """Chance each candidate plays: 0 if Out/Doubtful. Otherwise
    table: his recent appearance rate (measured table) x the Questionable factor;
    depth: the logistic PLAY_MODEL on depth rank, recent appearance rate and a Questionable designation."""
    from .config import PLAY_MODEL
    from .features import PLAY_RATE_NEW

    p = c["p_play"].fillna(PLAY_RATE_NEW) if "p_play" in c else pd.Series(1.0, index=c.index)
    q = (c["injury_status"] == "Questionable").to_numpy()
    if s.play_model == "depth":
        d = np.array([min(int((depth or {}).get(pid, 3)), 3) for pid in c.index])
        a = np.vectorize(PLAY_MODEL["a"].get)(np.clip(d, 1, 3))
        x = p.clip(0.01, 0.99).to_numpy()
        z = a + PLAY_MODEL["b"] * np.log(x / (1 - x)) + PLAY_MODEL["q"] * q
        p = pd.Series(1 / (1 + np.exp(-z)), index=c.index)
    else:
        p = p * np.where(q, s.questionable_factor, 1.0)
    return p.where(~c["out"], 0.0).clip(0.0, 1.0)


def role_rank(c: pd.DataFrame, raw: pd.Series, depth: dict | None) -> pd.Series:
    """1..n within each position group: depth-chart rank first, ties and unlisted players by usage."""
    d = pd.Series({pid: (depth or {}).get(pid, 9.0) for pid in c.index}, dtype=float)
    key = pd.DataFrame({"g": c["group"], "d": d, "u": -raw.reindex(c.index).fillna(0.0)})
    return key.sort_values(["g", "d", "u"]).groupby("g").cumcount().add(1).reindex(c.index).astype(float)


def redistribute(raw: pd.Series, group: pd.Series, pplay: pd.Series, rank: pd.Series, total: float, s) -> pd.Series:
    """Conditional-on-playing shares.

    1. Scale the usage shares of everyone on the roster (Out / Doubtful included) so they add up to `total`,
       what these players historically get (not every pass attempt has a tracked receiver).
    2. Each player's expected missing share, (1 - chance he plays) x share, goes mostly to his position
       group, weighted toward the next players down the depth chart (decay per step) and a little to those
       above him; the rest goes to everyone available, in proportion to usage.
    No share is created: the missing share moves to the players likely to be on the field."""
    raw = raw.fillna(0.0).clip(lower=0.0)
    tot = float(raw.sum())
    if tot <= 0:
        return raw
    sh = raw * (total / tot)
    gain = pd.Series(0.0, index=raw.index)
    pool = 0.0
    avail = pplay > 0
    for j in raw.index:
        mj = (1.0 - float(pplay[j])) * float(sh[j])
        if mj <= 0:
            continue
        same = avail & (group == group[j]) & (raw.index != j)
        if not same.any():
            pool += mj
            continue
        steps = rank[same] - rank[j]
        # Below him: the next man down first (decay per extra step). Above him: the starters, by usage
        # (redist_up, with its own decay per step; 1 = no decay, i.e. in proportion to their share).
        w = sh[same] ** s.redist_concentration * np.where(steps > 0, s.redist_decay ** (steps - 1).clip(lower=0), s.redist_up * s.redist_up_decay ** (-steps - 1).clip(lower=0))
        if w.sum() <= 0:
            pool += mj
            continue
        gain[same] += s.redist_in_group * mj * w / w.sum()
        pool += (1.0 - s.redist_in_group) * mj
    base = (sh ** s.redist_concentration * pplay)[avail]
    if pool > 0 and base.sum() > 0:
        gain[avail] += pool * base / base.sum()
    return (sh + gain).where(avail, 0.0)


def _questionable_split(c, skill, rushers, t_share, c_share, s, depth):
    """Questionable players, three separate pieces (each measured on 2021-22):
    1. chance he plays: PLAY_MODEL (depth rank, recent appearances, the designation);
    2. his role if he plays: his share x QUESTIONABLE_ROLE[position] (players listed Questionable who
       played got 9% (WR) / 16% (TE) fewer targets than their usual share; RBs no fewer carries);
    3. where the rest goes: the expected share he doesn't use (1 - chance x role) goes to his position
       group in depth-chart order (next man down first, then the starters by usage).
    The team's expected total is unchanged; only Questionable players' shares move."""
    from .config import QUESTIONABLE_ROLE

    q = c.index[(c["injury_status"] == "Questionable") & ~c["out"]]
    q = [pid for pid in q if pid in skill.index]
    if not q:
        return t_share, c_share, {}
    allsk = c.loc[skill.index]
    pp = play_chance(allsk, replace(s, play_model="depth"), depth)
    rank = role_rank(allsk, t_share, depth)
    info = {}
    t_new, c_new = t_share.copy(), c_share.copy()
    for pid in q:
        grp = allsk.at[pid, "group"]
        role = float(QUESTIONABLE_ROLE.get(grp, 1.0))
        # After the inactive lists, an active Questionable player is known to play: chance 1, role still reduced.
        p = 1.0 if s.gameday_inactives else float(pp[pid])
        info[pid] = {"play_chance": round(p, 3), "role_if_active": role}
        for series, target in ((t_share, "t"), (c_share, "c")):
            if pid not in series.index or series[pid] <= 0:
                continue
            base = float(series[pid])
            missing = base * (1.0 - p * role)
            mates = [j for j in series.index if j != pid and j in allsk.index and allsk.at[j, "group"] == grp and j not in q]
            if not mates:
                continue
            steps = rank.reindex(mates).fillna(9) - rank.get(pid, 9)
            w = series[mates].clip(lower=0) * np.where(steps > 0, s.redist_decay ** (steps - 1).clip(lower=0), 1.0)
            if w.sum() <= 0:
                continue
            gain = missing * w / w.sum()
            dest = t_new if target == "t" else c_new
            dest[mates] = dest[mates] + gain.values
            dest[pid] = base * role
    return t_new, c_new, info


def project_team(ctx: Context, game_id: str, team: str, opp: str, margin: float, total: float, qb_id: str | None,
                 roster: pd.DataFrame | None, injuries: pd.DataFrame | None, p: PropParams, rng,
                 depth: dict | None = None) -> list[PlayerProjection]:
    s = p.settings
    n = s.sims
    c = candidates(ctx, team, roster, injuries, gameday=s.gameday_inactives)
    active = c[~c["out"]]
    if active.empty:
        return []
    D = ctx.defense.loc[opp] if opp in ctx.defense.index else None
    L = ctx.league
    mu_pa, mu_ru = team_volume(ctx, team, opp, margin, total, p)

    # Starting QB: the listed starter if active, else the active QB with the most recent passing volume.
    qbs = active[active["group"] == "QB"]
    starter = qb_id if qb_id in qbs.index else (qbs["pass_att_w"].idxmax() if len(qbs) and qbs["pass_att_w"].max() > 0 else None)
    skill = active[active["group"].isin(["WR", "TE", "RB"])].copy()

    def snap_adj(df):
        r = (df["snap_short"] / df["snap_long"]).replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(0.4, 1.6)
        return r ** s.snap_trend_strength

    t_share = skill["target_share"] * snap_adj(skill) * skill["group"].map(lambda g: _ratio(D, f"tshare_{g}", s.matchup_strength))
    av = lambda df: df["p_play"].fillna(0.75) ** s.availability_weight if "p_play" in df else 1.0  # noqa: E731
    tw = (t_share * av(skill)).sum()
    t_total = float(ctx.league.get("target_rate", 1.0)) if (s.availability_weight > 0 or s.target_total_rate) else 1.0
    t_scale = float(np.clip(t_total / tw, 0.75, 1.4)) if tw > 0 else 1.0
    if not s.share_normalize:
        t_scale = 1.0
    t_share = t_share * t_scale
    rushers = skill.copy()
    if starter is not None:
        rushers = pd.concat([rushers, active.loc[[starter]]])
    c_share = rushers["carry_share"] * snap_adj(rushers).where(rushers["group"] != "QB", 1.0)
    cw = (c_share * av(rushers)).sum()
    c_scale = float(np.clip(1.0 / cw, 0.75, 1.4)) if cw > 0 else 1.0
    if not s.share_normalize:
        c_scale = 1.0
    c_share = c_share * c_scale
    q_info = {}
    if s.questionable_model == "split":
        t_share, c_share, q_info = _questionable_split(c, skill, rushers, t_share, c_share, s, depth)
    if s.opp_redistribution == "depth":
        # Every skill candidate, including those ruled Out / Doubtful (their share is redistributed, not lost).
        allsk = c[c["group"].isin(["WR", "TE", "RB"])]
        pp = play_chance(allsk, s, depth)
        ts = allsk["target_share_role"].fillna(allsk["target_share"]) if "target_share_role" in allsk else allsk["target_share"]
        cs = allsk["carry_share_role"].fillna(allsk["carry_share"]) if "carry_share_role" in allsk else allsk["carry_share"]
        t_raw = ts * snap_adj(allsk) * allsk["group"].map(lambda g: _ratio(D, f"tshare_{g}", s.matchup_strength))
        c_raw = cs * snap_adj(allsk)
        rk_t = role_rank(allsk, t_raw, depth)
        rk_c = role_rank(allsk, c_raw, depth)
        t_new = redistribute(t_raw, allsk["group"], pp, rk_t, float(L.get("target_rate", 0.95)) * s.target_total_factor, s)
        qb_c = float(rushers.loc[starter, "carry_share"]) if starter is not None else 0.0
        c_tot = float(L.get("skill_carry_rate", 0.84)) * s.carry_total_factor
        c_new = redistribute(c_raw, allsk["group"], pp, rk_c, c_tot, s)
        if s.redist_targets:
            t_share = t_new.reindex(skill.index).fillna(0.0)
        c_share = c_new.reindex(rushers.index)
        if starter is not None:
            c_share[starter] = qb_c
        c_share = c_share.fillna(0.0)
        role = rk_t.where(allsk["group"] != "RB", rk_c)

    if s.rb_role_factors:
        # Experimental lead-back correction: the model spreads carries too evenly across backs (lead backs short by
        # 8-10% every season 2023-25, backups over). RB1 = the active back with the largest projected carry share.
        rbs = [i for i in c_share.index if i in rushers.index and rushers.at[i, "group"] == "RB"] if len(c_share) else []
        if rbs:
            lead = max(rbs, key=lambda i: float(c_share[i]))
            for i in rbs:
                c_share[i] = float(c_share[i]) * float(s.rb_role_factors[0] if i == lead else s.rb_role_factors[1])
    PA = np.clip(np.rint(rng.normal(mu_pa, p.volume.pass_sd, n)), 8, 75).astype(int)
    RU = np.clip(np.rint(rng.normal(mu_ru, p.volume.rush_sd, n)), 5, 60).astype(int)

    # Team passing-efficiency factors from the QB (blitz split) and the defense.
    bz = 1.0
    if starter is not None and D is not None and pd.notna(D.get("blitz_rate")) and pd.notna(L.get("blitz_rate")):
        q = ctx.players.loc[starter]
        if pd.notna(q.get("ypa_blitz_rel")) and pd.notna(q.get("ypa_noblitz_rel")):
            b, bl = float(D["blitz_rate"]), float(L["blitz_rate"])
            num = b * q["ypa_blitz_rel"] + (1 - b) * q["ypa_noblitz_rel"]
            den = bl * q["ypa_blitz_rel"] + (1 - bl) * q["ypa_noblitz_rel"]
            bz = float(num / den) ** s.blitz_strength if den > 0 else 1.0
    man = float(D["man_rate"]) if D is not None and pd.notna(D.get("man_rate")) else L.get("man_rate", np.nan)
    # Inexperienced starting QB (0.1.1): the whole passing game, his yards and his receivers', is scaled together.
    qx = 1.0
    qb_note = None
    if starter is not None and s.inexp_qb_attempts > 0:
        ca = int(ctx.players.loc[starter].get("career_pass_att", 0) or 0)
        if ca < s.inexp_qb_attempts:
            qx = s.inexp_qb_yards
            qb_note = f"starting QB {ctx.players.loc[starter]['name']} has {ca} career pass attempts: team passing yards x{qx:.2f}"

    out: list[PlayerProjection] = []
    rows = {}
    for pid in set(skill.index) | set(rushers.index):
        rows[pid] = {k: np.zeros(n) for k in STATS}

    # Receivers
    for pid, x in skill.iterrows():
        grp = x["group"]
        share = _beta_share(rng, t_share[pid], s.target_dispersion, n)
        tg = rng.binomial(PA, share)
        cr = float(np.clip(x["catch_rate"] * _ratio(D, f"cr_{grp}", s.matchup_strength) *
                           _ratio(D, "pressure", -0.15 * s.pressure_strength), 0.05, 0.97))
        rec = rng.binomial(tg, cr)
        cov = 1.0
        if pd.notna(man) and pd.notna(x.get("ypt_man_rel")) and pd.notna(x.get("ypt_zone_rel")):
            ml = L.get("man_rate", man)
            num = man * x["ypt_man_rel"] + (1 - man) * x["ypt_zone_rel"]
            den = ml * x["ypt_man_rel"] + (1 - ml) * x["ypt_zone_rel"]
            cov = float(num / den) ** s.coverage_strength if den > 0 else 1.0
        f = float(x["ypr_factor"]) * _ratio(D, f"ypr_{grp}", s.matchup_strength) * cov * bz * qx
        yds, lng = _pool_sum(rng, ctx.pools[f"rec_{grp}"], rec, f * _shock(rng, _esd(s, "rec"), n, s.shock_kind))
        td = rng.binomial(tg, float(np.clip(x["rec_td_rate"] * _ratio(D, f"rectd_{grp}", s.matchup_strength), 0, 0.5)))
        r = rows[pid]
        r.update(targets=tg.astype(float), receptions=rec.astype(float), rec_yds=yds, long_rec=lng, rec_td=td.astype(float))
        r["_inputs"] = {"target_share": round(float(t_share[pid]), 4), "catch_rate": round(cr, 3), "yards_factor": round(f, 3),
                        **({"role_rank": int(role[pid]), "play_chance": round(float(pp[pid]), 3), "depth_rank": (depth or {}).get(pid)}
                           if s.opp_redistribution == "depth" else {}),
                        **({"questionable": q_info[pid]} if pid in q_info else {}),
                        "coverage_factor": round(cov, 3), "blitz_factor": round(bz, 3)}

    # Rushers (including the starting QB)
    for pid, x in rushers.iterrows():
        grp = x["group"]
        share = _beta_share(rng, c_share[pid], s.carry_dispersion, n)
        car = rng.binomial(RU, share)
        f = float(x["ypc_factor"]) * _ratio(D, "ypc", s.matchup_strength)
        yds, _ = _pool_sum(rng, ctx.pools[f"rush_{grp}"], car, f * _shock(rng, _esd(s, "rush"), n, s.shock_kind))
        td = rng.binomial(car, float(np.clip(x["rush_td_rate"] * _ratio(D, "rushtd", s.matchup_strength), 0, 0.5)))
        r = rows.setdefault(pid, {k: np.zeros(n) for k in STATS})
        r.update(carries=car.astype(float), rush_yds=yds, rush_td=td.astype(float))
        r.setdefault("_inputs", {})["carry_share"] = round(float(c_share[pid]), 4)

    # Starting QB passing
    if starter is not None:
        x = ctx.players.loc[starter]
        att = rng.binomial(PA, _beta_share(rng, 0.975, 200.0, n))
        cmp_p = float(np.clip(x["cmp_rate"] * _ratio(D, "cmp", s.matchup_strength) *
                              _ratio(D, "pressure", -0.15 * s.pressure_strength), 0.3, 0.85))
        cm = rng.binomial(att, cmp_p)
        f = float(x["ypcmp_factor"]) * _ratio(D, "ypcmp", s.matchup_strength) * bz * qx
        yds, _ = _pool_sum(rng, ctx.pools["pass"], cm, f * _shock(rng, _esd(s, "pass"), n, s.shock_kind))
        ints = rng.binomial(att, float(np.clip(x["int_rate"] * _ratio(D, "int", s.matchup_strength), 0.001, 0.2)))
        ptd = rng.binomial(att, float(np.clip(x["pass_td_rate"] * _ratio(D, "passtd", s.matchup_strength), 0.001, 0.2)))
        r = rows.setdefault(starter, {k: np.zeros(n) for k in STATS})
        r.update(pass_att=att.astype(float), pass_cmp=cm.astype(float), pass_yds=yds, ints=ints.astype(float), pass_td=ptd.astype(float))
        r.setdefault("_inputs", {}).update(completion_pct=round(cmp_p, 3), pass_yards_factor=round(f, 3), blitz_factor=round(bz, 3))

    for pid, r in rows.items():
        inputs = r.pop("_inputs", {})
        r["rush_rec_yds"] = r["rush_yds"] + r["rec_yds"]
        r["td_any"] = r["rush_td"] + r["rec_td"]
        r["fantasy_ppr"] = (0.04 * r["pass_yds"] + 4 * r["pass_td"] - 2 * r["ints"] + 0.1 * r["rush_yds"] + 6 * r["rush_td"]
                            + r["receptions"] + 0.1 * r["rec_yds"] + 6 * r["rec_td"])
        r["fantasy_sleeper"] = r["fantasy_ppr"] + r["ints"]  # Sleeper full PPR: interception −1, not −2
        x = ctx.players.loc[pid]
        inputs["sample"] = {"games": int(x["n_games"]), "targets": int(x["n_targets"]), "carries": int(x["n_carries"]),
                            "pass_att": int(x["n_pass_att"])} if "n_games" in x else {}
        if s.inexp_qb_attempts > 0 or s.injury_context:
            inputs.update(starting_qb=str(ctx.players.loc[starter]["name"]) if starter is not None else None,
                          starting_qb_career_attempts=int(ctx.players.loc[starter].get("career_pass_att", 0) or 0) if starter is not None else None,
                          qb_note=qb_note)
        inputs.update(team_pass_attempts=round(mu_pa, 1), team_carries=round(mu_ru, 1),
                      injury_status=c.loc[pid, "injury_status"] if pid in c.index else None,
                      snap_share_recent=None if pd.isna(x["snap_short"]) else round(float(x["snap_short"]), 3))
        out.append(PlayerProjection(pid, str(x["name"]), team, opp, str(x["group"]), game_id, r, inputs))
    return out


def project_games(ctx: Context, games: pd.DataFrame, roster: pd.DataFrame | None, injuries: pd.DataFrame | None,
                  p: PropParams, seed: int = 7, depth: dict | None = None) -> list[PlayerProjection]:
    """games: game_id, home_team, away_team, proj_home_score, proj_away_score, home_qb_id, away_qb_id.

    Each team-game gets its own random stream from (seed, game_id, team), so a projection reproduces
    exactly from the stored seed no matter which other games are in the run."""
    out: list[PlayerProjection] = []
    for _, g in games.iterrows():
        total = float(g["proj_home_score"] + g["proj_away_score"])
        m = float(g["proj_home_score"] - g["proj_away_score"])
        for team, opp, margin, qb in ((g["home_team"], g["away_team"], m, g.get("home_qb_id")),
                                      (g["away_team"], g["home_team"], -m, g.get("away_qb_id"))):
            rng = np.random.default_rng([seed, zlib.crc32(f"{g['game_id']}|{team}".encode())])
            out += project_team(ctx, g["game_id"], team, opp, margin, total, qb if isinstance(qb, str) else None,
                                roster, injuries, p, rng, depth=depth)
    return out
