"""NBA injury-aware props: active 0.2.0 vs shadow 0.2.3b, out of sample (TEST research; Moose 2026-11-27).

Nothing here changes a model, a params file, a ledger or a published board. It replays past game days walk-forward
(each day projected with games before that day only) for three versions on IDENTICAL player-games:

    0.2.0          the active model (no injury feed: a rotation player who missed his team's last 2 games is out)
    0.2.3b         the shadow (official injury report + minutes fix + its own calibration)
    0.2.3b-nofeed  0.2.3b with the injury feed switched off (ablation: what the injury report alone changes)

Pre-game injury information = the NBA's official injury report PDF published at or before 30 minutes before each tip
(the same leak-free rule 0.2.3b was fitted with on 2023-24). Test seasons 2024-25 and 2025-26, never used to fit it.
Players are graded only if they played; availability calls (projected a player who sat / left out one who played)
are counted separately.

    python -m modelroom.nba.props.injury_eval [--seasons 2025,2026] [--sims 3000] [--cache DIR] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
import unicodedata
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from modelroom.injuries import nba_official as NO

from . import model as M
from . import returns
from .config import MARKETS, PropParams

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[3]
PARAMS = Path(__file__).resolve().parent
EPS = 1e-6
SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


# ------------------------------------------------------------------------------------------------- official reports
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s.replace(".", ""))
    return " ".join(w for w in s.split() if w not in SUFFIX)


def pdf_name(n: str) -> str:
    """'James, LeBron' -> 'LeBron James' (the report lists Last, First)."""
    if "," in n:
        last, first = n.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return n


def slot_for(tip: datetime) -> datetime:
    """The newest 15-minute report slot at or before tip - 30 min, Eastern."""
    t = (tip - timedelta(minutes=30)).astimezone(ET).replace(second=0, microsecond=0)
    return t.replace(minute=(t.minute // 15) * 15)


class Reports:
    """Fetches (and caches on disk) the official report for a slot, walking back up to 3 hours to the newest one
    published at or before it. Counts requests."""

    def __init__(self, cache: Path, gap: float = 0.25, offline: bool = False):
        self.cache, self.gap, self.requests, self.found, self.missing, self.offline = cache, gap, 0, 0, 0, offline
        cache.mkdir(parents=True, exist_ok=True)
        self._mem: dict = {}

    def _get(self, url: str) -> bytes | None:
        f = self.cache / url.rsplit("/", 1)[1]
        if f.exists():
            return f.read_bytes() or None
        if self.offline:
            return None
        time.sleep(self.gap)
        self.requests += 1
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=NO.UA), timeout=20).read()
        except Exception:  # noqa: BLE001  not published for that slot
            b = b""
        f.write_bytes(b)
        return b or None

    def at(self, slot: datetime):
        if slot in self._mem:
            return self._mem[slot]
        got = None
        for i in range(13):                       # back to 3 hours earlier, newest first
            x = slot - timedelta(minutes=15 * i)
            urls = [NO.URL.format(x.strftime("%Y-%m-%d_%I_%M%p"))] + ([NO.URL.format(x.strftime("%Y-%m-%d_%I%p"))] if x.minute == 0 else [])
            for u in urls:
                b = self._get(u)
                if b:
                    try:
                        got = NO.parse(b, x)
                    except Exception:  # noqa: BLE001  unreadable report: keep walking back
                        got = None
                    if got is not None:
                        break
            if got is not None:
                break
        self.found += got is not None
        self.missing += got is None
        self._mem[slot] = got
        return got


def team_rows(rows: pd.DataFrame, roster: dict[str, list[str]], team: str, game_date: str) -> tuple[pd.DataFrame, dict]:
    """Report rows for one team-game with player ids matched EXACTLY (normalised full name, unique on the roster)."""
    r = rows[(rows["team"] == team) & (rows["game_date"] == game_date)].copy()
    stats = {"rows": len(r), "matched": 0, "unmatched": 0, "ambiguous": 0}
    ids = []
    for n in r["player"]:
        c = roster.get(norm(pdf_name(n)), [])
        if len(c) == 1:
            ids.append(c[0]); stats["matched"] += 1
        else:
            ids.append(None); stats["ambiguous" if len(c) > 1 else "unmatched"] += 1
    r["player_id"] = ids
    return r[r["player_id"].notna()], stats


# ------------------------------------------------------------------------------------------------- scoring
def ll(p, y):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS); y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(p) else float("nan")


def ece(p, y, b=10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    if not len(p):
        return float("nan")
    i = np.clip((p * b).astype(int), 0, b - 1)
    return float(sum((i == k).mean() * abs(p[i == k].mean() - y[i == k].mean()) for k in range(b) if (i == k).any()))


def metrics(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"n": 0}
    e = g["mean"] - g["actual"]
    o = {"n": int(len(g)), "player_games": int(g["pg"].nunique()), "mae": round(float(e.abs().mean()), 3),
         "bias_pct": round(float(100 * e.mean() / max(g["actual"].mean(), 1e-9)), 2)}
    lp = np.concatenate(g["lad_p"].to_numpy()) if len(g) else np.array([])
    ly = np.concatenate(g["lad_y"].to_numpy()) if len(g) else np.array([])
    k = (lp >= 0.02) & (lp <= 0.98)
    o.update(ladder_n=int(k.sum()), ladder_ll=round(ll(lp[k], ly[k]), 5), ladder_brier=round(float(np.mean((lp[k] - ly[k]) ** 2)), 5),
             ladder_ece=round(ece(lp[k], ly[k]), 4))
    q = g.dropna(subset=["p_over"])
    if len(q):
        o.update(ou_n=int(len(q)), ou_ll=round(ll(q["p_over"], q["y_over"]), 5), ou_ece=round(ece(q["p_over"], q["y_over"]), 4),
                 pred_over=round(float(q["p_over"].mean()), 4), actual_over=round(float(q["y_over"].mean()), 4))
    m = g[g["market"] == "points"]
    if len(m):
        me = m["proj_min"] - m["minutes"]
        o.update(minutes_mae=round(float(me.abs().mean()), 3), minutes_bias=round(float(me.mean()), 3))
    return o


def paired_ll_gain(G: pd.DataFrame, a: str, b: str, seed=5) -> dict:
    """Ladder log-loss of version a minus version b on identical rows (positive = b better), with a 95% interval
    resampling whole game days."""
    x = G[G["version"].isin([a, b])]
    if x.empty or (x["version"] == a).sum() == 0 or (x["version"] == b).sum() == 0:
        return {"n": 0}
    rows = []
    for v in (a, b):
        s = x[x["version"] == v]
        lp = np.concatenate(s["lad_p"].to_numpy()); ly = np.concatenate(s["lad_y"].to_numpy())
        day = np.concatenate([[d] * len(p) for d, p in zip(s["date"], s["lad_p"])])
        key = np.concatenate([[f"{k}|{mk}|{i}" for i in range(len(p))] for k, mk, p in zip(s["pg"], s["market"], s["lad_p"])])
        rows.append(pd.DataFrame({"key": key, "day": day, "p": lp, "y": ly}).set_index("key"))
    j = rows[0].join(rows[1][["p"]], rsuffix="_b", how="inner")
    j = j[(j["p"].between(0.02, 0.98)) | (j["p_b"].between(0.02, 0.98))]
    if j.empty:
        return {"n": 0}
    la = -(j["y"] * np.log(np.clip(j["p"], EPS, 1 - EPS)) + (1 - j["y"]) * np.log(np.clip(1 - j["p"], EPS, 1)))
    lb = -(j["y"] * np.log(np.clip(j["p_b"], EPS, 1 - EPS)) + (1 - j["y"]) * np.log(np.clip(1 - j["p_b"], EPS, 1)))
    d = (la - lb).to_numpy()
    days = j["day"].to_numpy()
    s = pd.DataFrame({"d": d, "day": days}).groupby("day")["d"].agg(["sum", "count"]).to_numpy()
    rng = np.random.default_rng(seed)
    bs = [(lambda t: t[0] / t[1])(s[rng.integers(0, len(s), len(s))].sum(axis=0)) for _ in range(1000)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"n": int(len(d)), "gain": round(float(d.mean()), 5), "ci95": [round(float(lo), 5), round(float(hi), 5)], "days": int(len(s))}


# ------------------------------------------------------------------------------------------------- replay
VERSIONS = ("0.2.0", "0.2.3b", "0.2.3b-nofeed")


def load_params(sims: int) -> dict[str, PropParams]:
    p0 = PropParams.load(PARAMS / "params_0.2.0.json")
    pb = PropParams.load(PARAMS / "params_0.2.3b.json")
    out = {"0.2.0": p0, "0.2.3b": pb, "0.2.3b-nofeed": replace(pb, settings=replace(pb.settings, injury_feed=False))}
    return {k: replace(v, settings=replace(v.settings, sims=sims)) for k, v in out.items()}


def run(seasons: list[int], sims: int, cache: Path, max_days: int | None = None, log=print, offline: bool = False, skip_days: int = 0) -> dict:
    from . import inputs as I
    inp = I.load()
    pg = inp.player_games.copy()
    pg["player_id"] = pg["player_id"].astype(str)
    pg["gd"] = pd.to_datetime(pg["game_date"])
    games = inp.games
    games = games[games["season"].isin(seasons) & (games["status"] == "final")].copy()
    games["game_id"] = games["game_id"].astype(str)
    params = load_params(sims)
    rep = Reports(cache, offline=offline)
    played = pg[pg["played"]].set_index(["game_id", "player_id"])
    box_all = pg.set_index(["game_id", "player_id"])
    stat_cols = sorted({m["stat"] for m in MARKETS.values()})
    rows, avail_rows, match_stats = [], [], {"rows": 0, "matched": 0, "unmatched": 0, "ambiguous": 0}
    days = sorted(games["game_date"].astype(str).unique())
    days = days[skip_days:]
    if max_days:
        days = days[:max_days]
    ctx_cache: dict = {}
    t0 = time.time()
    for di, day in enumerate(days):
        dg = games[games["game_date"].astype(str) == day]
        season = int(dg["season"].iloc[0])
        cutoff = pd.Timestamp(day)
        before = pg[pg["gd"] < cutoff]
        # rosters for name matching: anyone who appeared for the team this season or last, before this day
        rs = before[before["season"] >= season - 1]
        roster_by_team: dict[str, dict[str, list[str]]] = {}
        for (team, pid), nm in rs.groupby(["team", "player_id"])["name"].last().items():
            roster_by_team.setdefault(team, {}).setdefault(norm(nm), [])
            if pid not in roster_by_team[team][norm(nm)]:
                roster_by_team[team][norm(nm)].append(pid)
        teams = set(dg["home_abbr"]) | set(dg["away_abbr"])
        back = returns.current_back(before[before["team"].isin(teams) & (before["season"] >= season - 1)],
                                    rs.loc[rs["team"].isin(teams), "player_id"].unique().tolist())
        avail, ctx_info = {}, {}
        for g in dg.itertuples():
            tip = pd.Timestamp(g.start_time).to_pydatetime()
            got = rep.at(slot_for(tip))
            gd_et = str(pd.Timestamp(g.start_time).tz_convert("America/New_York").date())
            for team in (g.home_abbr, g.away_abbr):
                if got is None:
                    continue
                rws, filings = got
                tr, st = team_rows(rws, roster_by_team.get(team, {}), team, gd_et)
                for k in match_stats:
                    match_stats[k] += st[k]
                submitted = any(f["team"] == team and f["game_date"] == gd_et and f["submitted"] for f in filings)
                avail[(str(g.game_id), team)] = M.availability(tr, back, submitted, None)
                ctx_info[(str(g.game_id), team)] = {str(r.player_id): r.status for r in tr.itertuples()}
        projs = {}
        for v, p in params.items():
            ck = (day, v.replace("-nofeed", ""))
            if ck not in ctx_cache:
                if len(ctx_cache) > 4:
                    ctx_cache.clear()
                ctx_cache[ck] = M.build(inp.player_games, inp.pace, cutoff, season, p.settings)
            projs[v] = {(str(x.game_id), str(x.player_id)): x for x in M.project_games(ctx_cache[ck], dg, p, seed=int(day.replace("-", "")),
                                                                            avail=avail if p.settings.injury_feed else None)}
        keys = set.intersection(*(set(d) for d in projs.values()))
        anyk = set.union(*(set(d) for d in projs.values()))
        # availability calls on every player-game any version projected
        for k in anyk:
            inb = k in box_all.index
            pl = bool(box_all.loc[k, "played"]) if inb else False
            avail_rows.append({"date": day, **{f"proj_{v}": k in projs[v] for v in params}, "played": pl,
                               "listed": (ctx_info.get((k[0], projs[next(v for v in params if k in projs[v])][k].team)) or {}).get(str(k[1]))})
        for k in keys:
            if k not in played.index:
                continue
            a = played.loc[k]
            gid, pid = k
            team = projs["0.2.0"][k].team
            listed = ctx_info.get((gid, team), {})
            n_out = sum(1 for s in listed.values() if s in ("out", "doubtful"))
            own = listed.get(str(pid)) or "not listed"
            hist = before[before["player_id"] == str(pid)]
            hist = hist[hist["played"]].tail(10)
            start_rate = float(hist["starter"].mean()) if len(hist) else np.nan
            m10 = float(hist["minutes"].mean()) if len(hist) else np.nan
            for v, p in params.items():
                x = projs[v][k]
                for mk, m in MARKETS.items():
                    y = float(a[m["stat"]])
                    lad = [t for t in m["ladder"]]
                    lp = np.array([p.calibrate(mk, x.prob(m["stat"], t)) for t in lad])
                    line = float(max(1, math.ceil(float(np.median(hist[m["stat"]])))) ) if len(hist) >= 5 else None
                    p_over = float(p.calibrate(mk, x.prob(m["stat"], line))) if line is not None else None
                    rows.append({"version": v, "pg": f"{gid}|{pid}", "date": day, "season": season, "market": mk, "mean": float(x.mean(m["stat"])),
                                 "actual": y, "lad_p": lp, "lad_y": np.array([float(y >= t) for t in lad]), "p_over": p_over,
                                 "y_over": float(y >= line) if line is not None else None, "proj_min": float(x.inputs.get("projected_minutes", np.nan)),
                                 "minutes": float(a["minutes"]), "n_out": "0" if n_out == 0 else ("1" if n_out == 1 else "2+"),
                                 "own_status": own, "role": "bench" if not (start_rate >= 0.5) else "starter",
                                 "minutes_band": "<16" if not (m10 >= 16) else ("16-24" if m10 < 24 else ("24-30" if m10 < 30 else "30+"))})
        if di % 20 == 0:
            log(f"{day}: {di + 1}/{len(days)} days, {len(rows)} rows, reports found {rep.found} missing {rep.missing}, requests {rep.requests}, {time.time() - t0:.0f}s")
    G = pd.DataFrame(rows)
    A = pd.DataFrame(avail_rows)
    return summarize(G, A, seasons, sims, rep, match_stats)


def summarize(G: pd.DataFrame, A: pd.DataFrame, seasons, sims, rep, match_stats) -> dict:
    vs = list(VERSIONS)

    def by(col=None, sub=None, min_n=60):
        S = G if sub is None else G[sub]
        if col is None:
            return {v: metrics(S[S["version"] == v]) for v in vs}
        return {str(k): {v: metrics(x[x["version"] == v]) for v in vs} for k, x in S.groupby(col) if len(x) >= len(vs) * min_n}

    # how much the injury report moves individual projections (0.2.3b with vs without the feed), by teammates out
    w = G[G["version"].isin(["0.2.3b", "0.2.3b-nofeed"])].pivot_table(index=["pg", "market"], columns="version", values="mean", aggfunc="first")
    ctx = G[G["version"] == "0.2.3b"].set_index(["pg", "market"])[["n_out", "actual", "role"]]
    w = w.join(ctx, how="inner")
    w["delta"] = w["0.2.3b"] - w["0.2.3b-nofeed"]
    move = {}
    for (no, mk), x in w.groupby(["n_out", w.index.get_level_values("market")]):
        d = x["delta"]
        move.setdefault(mk, {})[no] = {"player_games": int(len(x)), "mean_change": round(float(d.mean()), 3), "mean_abs_change": round(float(d.abs().mean()), 3),
                                       "share_moved_over_10pct": round(float((d.abs() > 0.1 * x["0.2.3b-nofeed"].clip(lower=0.5)).mean()), 3)}
    av = {}
    if len(A):
        for v in vs:
            c = A[f"proj_{v}"]
            av[v] = {"projected_and_played": int((c & A["played"]).sum()), "projected_but_did_not_play": int((c & ~A["played"]).sum()),
                     "listed_out_or_doubtful_but_projected": int((c & A["listed"].isin(["out", "doubtful"])).sum())}
    replacement = (G["n_out"] != "0") & (G["own_status"] == "not listed") & (G["role"] == "bench")
    out = {
        "kind": "nba_injury_eval", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seasons": seasons, "sims": sims, "versions": vs,
        "method": __doc__.strip().split("\n\n")[1],
        "reports": {"slots_found": rep.found, "slots_missing": rep.missing, "http_requests": rep.requests},
        "name_matching": match_stats,
        "player_games": int(G["pg"].nunique()), "game_days": int(G["date"].nunique()), "first_day": str(G["date"].min()), "last_day": str(G["date"].max()),
        "overall": by(),
        "by_market": by("market"),
        "by_season": by("season"),
        "by_teammates_out": by("n_out"),
        "by_own_status": by("own_status", min_n=20),
        "by_role": by("role"),
        "by_minutes_band": by("minutes_band"),
        "replacement_players": {"definition": "bench players (started <50% of last 10) not on the report, with 1+ teammate Out/Doubtful",
                                **by(None, replacement)},
        "replacement_by_market": by("market", replacement, min_n=20),
        "teammates_out_by_market": {mk: by("n_out", G["market"] == mk, min_n=20) for mk in MARKETS},
        "projection_change_from_injury_report": move,
        "paired_ladder_ll_gain": {f"{a}->{b}": paired_ll_gain(G, a, b) for a, b in (("0.2.0", "0.2.3b"), ("0.2.3b-nofeed", "0.2.3b"), ("0.2.0", "0.2.3b-nofeed"))},
        "paired_ladder_ll_gain_teammates_out": {f"{a}->{b}": paired_ll_gain(G[G["n_out"] != "0"], a, b) for a, b in (("0.2.0", "0.2.3b"), ("0.2.3b-nofeed", "0.2.3b"))},
        "paired_by_market": {mk: paired_ll_gain(G[G["market"] == mk], "0.2.0", "0.2.3b") for mk in MARKETS},
        "availability": av,
    }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2025,2026")
    ap.add_argument("--sims", type=int, default=3000)
    ap.add_argument("--cache", default="/tmp/nba_injury_reports")
    ap.add_argument("--max-days", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "docs" / "models" / "results" / "nba-props-injury-eval.json"))
    a = ap.parse_args(argv)
    r = run([int(s) for s in a.seasons.split(",")], a.sims, Path(a.cache), a.max_days)
    Path(a.out).write_text(json.dumps(r, indent=1, default=str))
    print(json.dumps({k: r[k] for k in ("player_games", "game_days", "reports", "name_matching", "overall", "paired_ladder_ll_gain")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
