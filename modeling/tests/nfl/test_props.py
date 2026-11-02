"""NFL prop engine. Synthetic tests check the simulation mechanics; `real_nfl` tests use downloaded data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modelroom.nfl.props import model as M
from modelroom.nfl.props.config import MARKETS, PropParams, PropSettings, VolumeModel
from modelroom.nfl.props.features import Context

from ..conftest import has_real

real_players = pytest.mark.skipif(not has_real("nfl", "player_games"), reason="run `python -m modelroom nfl ingest` first")


def _ctx() -> Context:
    idx = ["qb1", "qb2", "wr1", "wr2", "te1", "rb1"]
    P = pd.DataFrame(index=idx)
    P["name"] = ["Q One", "Q Two", "W One", "W Two", "T One", "R One"]
    P["group"] = ["QB", "QB", "WR", "WR", "TE", "RB"]
    P["team_last"] = "AAA"
    P["last_game"] = pd.Timestamp("2030-10-01")
    P["sportradar_id"] = None
    P["target_share"] = [0, 0, 0.30, 0.20, 0.20, 0.15]
    P["carry_share"] = [0.10, 0.05, 0.01, 0.01, 0.0, 0.60]
    P["catch_rate"] = [0.6, 0.6, 0.65, 0.65, 0.7, 0.8]
    P["ypr_factor"] = 1.0
    P["rec_td_rate"] = 0.04
    P["ypc_factor"] = 1.0
    P["rush_td_rate"] = 0.03
    P["cmp_rate"] = 0.65
    P["ypcmp_factor"] = 1.0
    P["int_rate"] = 0.02
    P["pass_td_rate"] = 0.045
    P["pass_att_w"] = [300.0, 20.0, 0, 0, 0, 0]
    P["snap_long"] = 0.8
    P["snap_short"] = 0.8
    for c in ("ypt_man_rel", "ypt_zone_rel", "ypa_blitz_rel", "ypa_noblitz_rel"):
        P[c] = np.nan
    teams = pd.DataFrame({"pa_base": [34.0, 34.0], "ru_base": [26.0, 26.0], "pa_faced": [0.0, 0.0], "ru_faced": [0.0, 0.0]}, index=["AAA", "BBB"])
    rng = np.random.default_rng(0)
    pools = {f"rec_{g}": rng.gamma(2.0, 5.5, 5000) for g in ("WR", "TE", "RB", "QB")}
    pools["pass"] = rng.gamma(2.0, 5.5, 5000)
    pools.update({f"rush_{g}": rng.normal(4.3, 6.0, 5000) for g in ("RB", "QB", "WR", "TE")})
    league = {"man_rate": 0.35, "blitz_rate": 0.27}
    return Context(pd.Timestamp("2030-10-08"), 2030, P, pd.DataFrame(index=["AAA", "BBB"]), teams, league, pools)


def _params(**kw):
    return PropParams(PropSettings(sims=3000, **kw), VolumeModel(pass_coef=(0, 1, 1, 0, 0), rush_coef=(0, 1, 1, 0, 0)))


def test_probabilities_fall_as_the_threshold_rises():
    out = M.project_team(_ctx(), "g", "AAA", "BBB", 0.0, 44.0, "qb1", None, None, _params(), np.random.default_rng(1))
    wr = next(x for x in out if x.player_id == "wr1")
    probs = [wr.prob("rec_yds", k) for k in MARKETS["receiving_yards"]["ladder"]]
    assert all(a >= b for a, b in zip(probs, probs[1:]))
    assert wr.prob("long_rec", 10) <= wr.prob("receptions", 1)
    assert np.all(wr.sims["long_rec"] <= wr.sims["rec_yds"] + 1e-9)  # longest catch never exceeds the total


def test_starting_qb_gets_the_attempts_and_fantasy_scoring_variants_differ():
    out = M.project_team(_ctx(), "g", "AAA", "BBB", 0.0, 44.0, "qb1", None, None, _params(), np.random.default_rng(1))
    qb = next(x for x in out if x.player_id == "qb1")
    assert 25 < qb.mean("pass_att") < 40
    assert all(x.mean("pass_att") == 0 for x in out if x.player_id == "qb2")
    assert np.allclose(qb.sims["fantasy_sleeper"] - qb.sims["fantasy_ppr"], qb.sims["ints"])


def test_out_player_is_removed_and_his_targets_go_to_teammates():
    ctx = _ctx()
    p = _params()
    base = {x.player_id: x.mean("targets") for x in M.project_team(ctx, "g", "AAA", "BBB", 0, 44, "qb1", None, None, p, np.random.default_rng(2))}
    inj = pd.DataFrame([{"team": "AAA", "gsis_id": "wr1", "report_status": "Out"}])
    after = {x.player_id: x.mean("targets") for x in M.project_team(ctx, "g", "AAA", "BBB", 0, 44, "qb1", None, inj, p, np.random.default_rng(2))}
    assert "wr1" not in after
    assert after["wr2"] > base["wr2"] and after["te1"] > base["te1"]


def test_wider_share_dispersion_widens_the_distribution():
    narrow = M.project_team(_ctx(), "g", "AAA", "BBB", 0, 44, "qb1", None, None, _params(target_dispersion=200.0), np.random.default_rng(3))
    wide = M.project_team(_ctx(), "g", "AAA", "BBB", 0, 44, "qb1", None, None, _params(target_dispersion=8.0), np.random.default_rng(3))
    sd = lambda out: next(x for x in out if x.player_id == "wr1").sims["targets"].std()  # noqa: E731
    assert sd(wide) > sd(narrow)


def test_calibration_maps_probabilities():
    p = PropParams(calibration={"receptions": [0.0, 1.0], "receiving_yards": [0.2, 0.9]})
    assert p.calibrate("receptions", 0.3) == pytest.approx(0.3)
    assert p.calibrate("unknown", 0.3) == 0.3
    assert p.calibrate("receiving_yards", 0.5) > 0.5


@real_players
def test_player_table_matches_team_passing():
    from modelroom.nfl import player_data

    pg, passes, _ = player_data.load()
    g = pg[pg["season"] == pg["season"].max() - 1]
    team = g.groupby(["game_id", "team"]).agg(rec=("rec_yds", "sum"), pas=("pass_yds", "sum"), tgt=("targets", "sum"), att=("pass_att", "sum"))
    # Receiving yards equal passing yards except on rare laterals; targets never exceed attempts.
    assert (team["rec"] - team["pas"]).abs().median() == 0
    assert (team["tgt"] <= team["att"]).all()
    assert g["position"].notna().mean() > 0.99


@real_players
def test_features_use_only_earlier_games():
    from modelroom.nfl import player_data
    from modelroom.nfl.props import features as F

    pg, passes, rushes = player_data.load()
    season = int(pg["season"].max()) - 1
    cutoff = pd.Timestamp(f"{season}-11-01")
    ctx = F.build(pg, passes, rushes, cutoff, season, PropSettings())
    assert (ctx.players["last_game"] < cutoff).all()
    assert len(ctx.defense) == 32 and abs(ctx.defense["ypc"].mean() - 1) < 1e-9


def test_projections_reproduce_from_the_stored_seed_regardless_of_other_games():
    ctx = _ctx()
    p = _params()
    g1 = pd.DataFrame([{"game_id": "g1", "home_team": "AAA", "away_team": "BBB", "proj_home_score": 24.0, "proj_away_score": 20.0,
                        "home_qb_id": "qb1", "away_qb_id": None}])
    g2 = pd.concat([pd.DataFrame([{**g1.iloc[0].to_dict(), "game_id": "g0"}]), g1], ignore_index=True)
    a = {x.player_id: x.sims["rec_yds"] for x in M.project_games(ctx, g1, None, None, p, seed=202609) if x.game_id == "g1" and x.team == "AAA"}
    b = {x.player_id: x.sims["rec_yds"] for x in M.project_games(ctx, g2, None, None, p, seed=202609) if x.game_id == "g1" and x.team == "AAA"}
    assert a.keys() == b.keys() and all(np.array_equal(a[k], b[k]) for k in a)


def test_support_levels_flag_thin_history():
    from modelroom.nfl.props.config import support_level

    assert support_level("receiving_yards", "WR", {"games": 10, "targets": 80})[0] == "ok"
    assert support_level("receiving_yards", "WR", {"games": 4, "targets": 20})[0] == "limited"
    assert support_level("receiving_yards", "WR", {"games": 1, "targets": 3})[0] == "insufficient"
    assert support_level("rushing_yards", "QB", {"games": 10, "pass_att": 300, "carries": 30})[0] == "ok"


def test_strong_edges_need_every_reliability_gate():
    from modelroom.markets import compare as C

    best = {"yes": {"provider": "kalshi", "price": 0.40, "fee": 0.017, "ev": 0.08, "size": 900.0}, "no": None, "edge": "yes"}
    good = {"ece": 0.01, "baseline_log_loss": 0.50, "model_log_loss_same_rows": 0.46}
    assert C.grade(best, "ok", good)["grade"] == "strong"
    assert C.grade(best, "limited", good)["grade"] == "lean"
    assert C.grade(best, "ok", {**good, "ece": 0.08})["grade"] == "lean"
    assert C.grade(best, "ok", None)["grade"] == "lean"
    thin = {**best, "yes": {**best["yes"], "size": None}}
    assert "size at this price not published" in C.grade(thin, "ok", good)["reasons"]
    assert C.grade({"yes": None, "no": None, "edge": None}, "ok", good)["grade"] is None
