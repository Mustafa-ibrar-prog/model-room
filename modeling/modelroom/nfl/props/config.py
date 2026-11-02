"""NFL player-prop model settings and the market definitions it can price."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

MODEL_ID = "nfl-props"
MODEL_VERSION = "0.1.0"
PARAMS_FILE = Path(__file__).with_name("params.json")

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
    sims: int = 4000


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
        return {"model_id": MODEL_ID, "model_version": MODEL_VERSION, **asdict(self)}

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
