"""NBA model settings. Tunable values are chosen by the backtest, then frozen in params.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MODEL_ID = "nba-game"
MODEL_VERSION = "1.0.0"
PARAMS_FILE = Path(__file__).with_name("params.json")


@dataclass(frozen=True)
class RatingSettings:
    """Hyperparameters for the rating fit (see docs/models/nba.md)."""

    half_life_days: float = 45.0      # recency weight halves every N days
    prior_games: float = 12.0         # strength of last season's prior, in games of evidence
    prior_retention: float = 0.7      # share of last season's rating carried into the prior
    home_prior_games: float = 200.0   # home edge changes slowly
    pace_prior_games: float = 10.0
    pace_retention: float = 0.8
    mean_prior_games: float = 1.0     # keeps league average defined on opening night


@dataclass(frozen=True)
class FittedAdjustments:
    """Learned from training seasons' out-of-sample residuals."""

    b2b_points: float = 0.0           # margin effect of the opponent being on a back-to-back
    rest_points: float = 0.0          # margin per day of rest advantage (capped at 3)
    total_points: float = 0.0         # mean total residual (overtime, scoring drift)
    margin_sigma: float = 12.0        # std. dev. of margin errors, for win probability
    total_sigma: float | None = None  # std. dev. of total errors, for the total's uncertainty range
    injury_points_per_value: float | None = None  # k in docs; None until fitted


@dataclass(frozen=True)
class ModelParams:
    ratings: RatingSettings = field(default_factory=RatingSettings)
    adjustments: FittedAdjustments = field(default_factory=FittedAdjustments)
    provenance: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"model_id": MODEL_ID, "model_version": MODEL_VERSION, **asdict(self)}

    def save(self, path: Path = PARAMS_FILE) -> None:
        path.write_text(json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path = PARAMS_FILE) -> "ModelParams":
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found. Run: python -m modelroom nba backtest --fit")
        d = json.loads(path.read_text())
        return cls(
            ratings=RatingSettings(**d["ratings"]),
            adjustments=FittedAdjustments(**d["adjustments"]),
            provenance=d.get("provenance", {}),
        )
