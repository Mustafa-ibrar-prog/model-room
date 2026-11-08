"""NFL player-prop model settings and the market definitions it can price."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

MODEL_ID = "nfl-props"
MODEL_VERSION = "0.1.0"
PARAMS_FILE = Path(__file__).with_name("params.json")
CANDIDATE_VERSION = "0.2.0"
CANDIDATE_FILE = Path(__file__).with_name("params_0.2.0.json")  # yardage-shape candidate: held, never activated
OPP_VERSION = "0.3.0"
OPP_FILE = Path(__file__).with_name("params_0.3.0.json")  # opportunity redistribution (test site only when enabled)
INJURY_VERSION = "0.1.1"
INJURY_FILE = Path(__file__).with_name("params_0.1.1.json")  # 0.1.0 + live injury feed + inexperienced-QB passing

HISTORY_SEASONS = 3      # prior seasons used alongside the current one
TUNE_SEASONS = (2021, 2022)
TEST_SEASONS = (2023, 2024, 2025)
FIT_SEASONS = (2019, 2020, 2021, 2022)  # team-volume regression for the backtest


@dataclass(frozen=True)
class PropSettings:
    half_life_games: float = 8.0      # player usage/efficiency recency weight
    season_carry: float = 0.5         # weight multiplier per season back
    def_half_life_games: float = 10.0
    share_prior_games: float = 2.0    # target/carry share pulled toward the position average
    rate_prior: float = 40.0          # catch rate, YPR etc.: prior in targets / carries / receptions
    td_prior: float = 120.0           # TD rates are noisy: stronger pull
    def_prior_games: float = 6.0      # defense-allowed rates pulled toward league average
    target_dispersion: float = 30.0   # beta concentration for game-to-game target share (lower = wider)
    carry_dispersion: float = 6.0     # same for carry share (carries swing more with game script)
    efficiency_sd: float = 0.15       # game-level shock to yards per play (lognormal sd), shared by a player's plays
    matchup_strength: float = 1.0     # exponent on opponent-allowed ratios (0 = ignore defense)
    coverage_strength: float = 1.0    # receiver man/zone split × opponent man rate
    blitz_strength: float = 1.0       # QB blitz split × opponent blitz rate
    pressure_strength: float = 1.0    # opponent pressure/sack rate → QB completion %
    snap_trend_strength: float = 0.5  # recent snap share vs longer-run snap share
    # 0.2 foundation settings. Defaults reproduce 0.1 exactly.
    share_half_life_games: float = 0.0  # recency of target/carry shares (0 = same as half_life_games)
    eff_sd_pass: float = -1.0           # yards shock per family (negative = use efficiency_sd)
    eff_sd_rec: float = -1.0
    eff_sd_rush: float = -1.0
    shock_kind: str = "lognormal"       # "lognormal" (right-skewed) or "normal" (symmetric, floored)
    availability_weight: float = 0.0    # 1 = when shares are scaled to the team total, each rostered player
                                        # counts by his chance of actually playing (gameday inactives took ~7%
                                        # of projected carries and ~6% of targets in 2024)
    # 0.2 opportunity redistribution (defaults = 0.1 behaviour).
    opp_redistribution: str = "proportional"  # "proportional": shares of unavailable players are spread over
                                        # everyone by rescaling; "depth": each player's expected missing share
                                        # ((1 - chance he plays) x his share, all of it if Out/Doubtful) goes to
                                        # his position group in depth-chart order, and team totals are set to
                                        # what tracked receivers / rushers historically get
    redist_decay: float = 0.5           # weight multiplier per extra depth step below the missing player
    redist_up: float = 0.3              # weight for players ranked above him (relative to the next man down)
    redist_up_decay: float = 0.5        # weight multiplier per extra step for players ranked above him
    share_model: str = "history"        # "history": recency-weighted share (0.1); "role": that share corrected
                                        # with his last-5-game and this-season share and his depth-chart rank now
                                        # (coefficients SHARE_MODEL, fit on 2021-22)
    gameday_inactives: bool = False     # True: projections made after the official inactive lists (~90 min
                                        # before kickoff): gameday inactives are removed; Questionable players
                                        # who are active are known to be active
    target_total_rate: bool = False     # True: receivers' shares add up to the share of pass attempts that
                                        # historically reach RBs/WRs/TEs (~95%), not 100%
    inexp_qb_attempts: int = 0          # 0.1.1: a starting QB with fewer career attempts than this (0 = off) ...
    injury_context: bool = False        # 0.1.1: record the starting QB and the injury feed on every projection
    inexp_qb_yards: float = 1.0         # ... has his team's passing yards (his and his receivers') scaled by this:
                                        # his rates are pulled toward the league-average QB, but such QBs reach
                                        # 93% of it (measured 2021-22, held out 2023-25: same 0.931)
    share_normalize: bool = True        # False (share_model="role"): role shares are absolute (share of team
                                        # attempts if he plays), not rescaled so the roster sums to 100%
    questionable_model: str = "none"    # "none": a Questionable player is projected as fully active (0.1);
                                        # "split": (1) chance he plays, (2) his role if he plays, (3) where his
                                        # share goes if he doesn't, each measured separately on 2021-22
    redist_targets: bool = True         # False: carries only (targets keep the 0.1 allocation)
    redist_concentration: float = 1.0   # >1: missing opportunity goes to the bigger roles more than in proportion
    target_total_factor: float = 1.0    # team-total calibration (fit on 2021-22): projected targets / carries to the
    carry_total_factor: float = 1.0     # players who play, summed per team-game, should match what they get
    redist_in_group: float = 0.8        # share of the missing opportunity kept in his position group
    questionable_factor: float = 0.78   # chance-of-playing multiplier for a Questionable designation (play_model="table")
    fill_in_weight: float = 1.0         # weight of history games he played filling in for a missing teammate
    role_share_weight: float = 1.0      # weight of history games played at another depth rank (1 = all equal, 0.1)
    play_model: str = "table"           # "depth": chance of playing from depth rank + recent appearances +
                                        # Questionable (logistic fit on 2021-22, PLAY_MODEL below)
    rb_role_factors: tuple = ()         # experimental: carry-share multipliers for the team's lead back and the other
                                        # backs (RB1, RB2+), fitted on 2021-22; empty = off (0.1.1 unchanged)
    sims: int = 4000


# Role-aware share (share_model="role"): share = a*history + b*(last5 - history) + c*(season - history)
# + d[depth rank 1, 2, 3] (rank 4+/unlisted = 0), per position group; targets "t", carries "c". Fit on 2021-22
# skill players who played (share of team pass attempts / carries).
SHARE_MODEL: dict = {
    "t": {"WR": [0.8725, 0.1899, 0.2329, 0.031, 0.0077, 0.0038], "TE": [0.9797, 0.109, 0.2398, 0.0123, 0.0015, 0.0001],
          "RB": [0.9127, 0.1231, 0.0434, 0.0096, 0.0086, 0.0006]},
    "c": {"RB": [0.9577, 0.2799, 0.3336, 0.0221, 0.0194, -0.0055]},
}
# Questionable (questionable_model="split"): his share if he plays = share x QUESTIONABLE_ROLE[group];
# measured on 2021-22 Questionable players who played.
QUESTIONABLE_ROLE: dict = {"WR": 0.906, "TE": 0.842, "RB": 1.003}

# P(plays) = sigmoid(a[depth] + b * logit(recent appearance rate) + q * Questionable); depth 1, 2, 3+ (or
# unlisted). Fit on 2021-22 skill players not ruled Out/Doubtful; calibrated within 2 points on 2023-25.
PLAY_MODEL = {"a": {1: 1.9017, 2: 0.6419, 3: 0.0867}, "b": 0.7252, "q": -1.6071}


ADDED_SETTINGS = ("share_half_life_games", "eff_sd_pass", "eff_sd_rec", "eff_sd_rush", "shock_kind", "availability_weight",
                  "opp_redistribution", "redist_decay", "redist_up", "redist_up_decay", "redist_in_group", "questionable_factor",
                  "fill_in_weight", "role_share_weight", "play_model", "redist_targets", "redist_concentration",
                  "target_total_factor", "carry_total_factor", "share_model", "questionable_model", "share_normalize", "gameday_inactives", "target_total_rate",
                  "inexp_qb_attempts", "inexp_qb_yards", "injury_context", "rb_role_factors")


@dataclass(frozen=True)
class VolumeModel:
    """team pass attempts / carries = b0 + b1·team_base + b2·(opp_faced − league) + b3·proj_margin + b4·proj_total"""

    pass_coef: tuple[float, ...] = (0.0, 1.0, 1.0, -0.35, 0.0)
    rush_coef: tuple[float, ...] = (0.0, 1.0, 1.0, 0.25, 0.0)
    pass_sd: float = 6.5
    rush_sd: float = 5.5


@dataclass(frozen=True)
class PropParams:
    settings: PropSettings = field(default_factory=PropSettings)
    volume: VolumeModel = field(default_factory=VolumeModel)
    calibration: dict = field(default_factory=dict)  # market -> [a, b]: p' = σ(a + b·logit(p)), fit on tuning seasons
    provenance: dict = field(default_factory=dict)

    def calibrate(self, market: str, p: float) -> float:
        ab = self.calibration.get(market)
        if not ab:
            return p
        q = min(max(p, 1e-4), 1 - 1e-4)
        z = ab[0] + ab[1] * math.log(q / (1 - q))
        return 1.0 / (1.0 + math.exp(-z))

    def to_json(self) -> dict:
        d = {"model_id": MODEL_ID, "model_version": MODEL_VERSION, **asdict(self)}
        # Settings added after 0.1.0 are left out while they sit at their default, so 0.1.0's parameter hash
        # (stored in every ledger record) stays exactly what it was.
        default = PropSettings()
        d["settings"] = {k: v for k, v in d["settings"].items() if k not in ADDED_SETTINGS or v != getattr(default, k)}
        return d

    def save(self, path: Path = PARAMS_FILE) -> None:
        path.write_text(json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path = PARAMS_FILE) -> "PropParams":
        if not path.exists():
            return cls()
        d = json.loads(path.read_text())
        known = {f.name for f in fields(PropSettings)}
        s = PropSettings(**{k: v for k, v in d["settings"].items() if k in known})
        v = d["volume"]
        vm = VolumeModel(tuple(v["pass_coef"]), tuple(v["rush_coef"]), v["pass_sd"], v["rush_sd"])
        return cls(s, vm, d.get("calibration", {}), d.get("provenance", {}))


# History behind a projection, in the window the model uses (this season + 3 before).
# A market is "ok" at or above the first number, "limited" at or above the second, else "insufficient".
SUPPORT = {
    "targets": (40, 15),     # receiving markets
    "carries": (50, 20),     # rushing markets
    "pass_att": (150, 60),   # QB passing markets
    "games": (6, 3),         # every market
}
MARKET_BASIS = {
    "passing_yards": "pass_att", "passing_attempts": "pass_att", "passing_completions": "pass_att", "passing_tds": "pass_att",
    "interceptions": "pass_att", "rushing_yards": "carries", "rushing_attempts": "carries", "receiving_yards": "targets",
    "receptions": "targets", "longest_reception": "targets", "rush_rec_yards": "role", "anytime_td": "role", "fantasy_points": "role",
}


def support_level(market: str, position: str, n: dict) -> tuple[str, str]:
    """→ (level, plain reason). n: games, targets, carries, pass_att (unweighted counts)."""
    basis = MARKET_BASIS.get(market, "role")
    if basis == "role":
        basis = "pass_att" if position == "QB" else "carries" if position == "RB" else "targets"
    if basis == "carries" and position == "QB":
        basis = "pass_att"  # a QB's rushing is judged on his snaps as the passer
    hi, lo = SUPPORT[basis]
    ghi, glo = SUPPORT["games"]
    v, g = n.get(basis, 0), n.get("games", 0)
    label = basis.replace("pass_att", "pass attempts")
    if v >= hi and g >= ghi:
        return "ok", f"{g} games, {v} {label}"
    if v >= lo and g >= glo:
        return "limited", f"only {g} games, {v} {label}"
    return "insufficient", f"only {g} games, {v} {label}"


# Normalized market keys shared with the market-data adapters (modelroom.markets).
# stat: column in the simulated / actual player-game table.
# ladder: thresholds used by the backtest ("k or more").
MARKETS: dict[str, dict] = {
    "passing_yards": {"stat": "pass_yds", "label": "Passing yards", "positions": ("QB",), "ladder": [150, 175, 200, 225, 250, 275, 300, 325, 350]},
    "passing_attempts": {"stat": "pass_att", "label": "Pass attempts", "positions": ("QB",), "ladder": [25, 30, 35, 40, 45]},
    "passing_completions": {"stat": "pass_cmp", "label": "Completions", "positions": ("QB",), "ladder": [14, 16, 18, 20, 22, 24, 26, 28]},
    "passing_tds": {"stat": "pass_td", "label": "Passing TDs", "positions": ("QB",), "ladder": [1, 2, 3]},
    "interceptions": {"stat": "ints", "label": "Interceptions", "positions": ("QB",), "ladder": [1, 2]},
    "rushing_yards": {"stat": "rush_yds", "label": "Rushing yards", "positions": ("QB", "RB", "WR"), "ladder": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 125]},
    "rushing_attempts": {"stat": "carries", "label": "Rush attempts", "positions": ("QB", "RB"), "ladder": [5, 10, 15, 20, 25]},
    "receiving_yards": {"stat": "rec_yds", "label": "Receiving yards", "positions": ("RB", "WR", "TE"), "ladder": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 125, 150]},
    "receptions": {"stat": "receptions", "label": "Receptions", "positions": ("RB", "WR", "TE"), "ladder": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
    "rush_rec_yards": {"stat": "rush_rec_yds", "label": "Rush + rec yards", "positions": ("RB", "WR", "TE"), "ladder": [25, 50, 75, 100, 125, 150]},
    "anytime_td": {"stat": "td_any", "label": "Anytime TD", "positions": ("QB", "RB", "WR", "TE"), "ladder": [1, 2]},
    "longest_reception": {"stat": "long_rec", "label": "Longest reception", "positions": ("RB", "WR", "TE"), "ladder": [10, 15, 20, 25, 30, 40]},
    "fantasy_points": {"stat": "fantasy_ppr", "label": "Fantasy points (PPR)", "positions": ("QB", "RB", "WR", "TE"), "ladder": [5, 8, 10, 12, 15, 18, 20, 25, 30]},
}
