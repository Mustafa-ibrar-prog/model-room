"""NFL model settings. Tuned values are chosen by the backtest, then frozen in params.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MODEL_ID = "nfl-game"
MODEL_VERSION = "1.0.1"  # 1.0.0 = first draft with last-4-games QB mix (ledger only, never shipped)
PARAMS_FILE = Path(__file__).with_name("params.json")
WINDOW_SEASONS = 3          # prior seasons of plays used alongside the current one
PLAYS_PER_GAME = 60.0       # converts "games of evidence" into weighted plays for the ridge penalty


@dataclass(frozen=True)
class RatingSettings:
    half_life_games: float = 8.0     # recency weight halves every N team games
    season_carry: float = 0.5        # weight multiplier per season back
    prior_games: float = 4.0         # ridge pull toward league average, in games of evidence
    home_prior_games: float = 20.0
    qb_shrink_dropbacks: float = 250.0


@dataclass(frozen=True)
class PointsModel:
    """points = intercept + epa_coef × exp_off_epa + rest_coef × rest_adv + indoor_coef × indoor + home_coef × is_home"""

    intercept: float = 0.0
    epa_coef: float = 0.0
    rest_coef: float = 0.0
    indoor_coef: float = 0.0
    home_coef: float = 0.0
    margin_sigma: float = 13.0
    total_sigma: float | None = None
    qb_replacement_epa: float = -0.1


@dataclass(frozen=True)
class ModelParams:
    ratings: RatingSettings = field(default_factory=RatingSettings)
    points: PointsModel = field(default_factory=PointsModel)
    provenance: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"model_id": MODEL_ID, "model_version": MODEL_VERSION, **asdict(self)}

    def save(self, path: Path = PARAMS_FILE) -> None:
        path.write_text(json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path = PARAMS_FILE) -> "ModelParams":
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found. Run: python -m modelroom nfl backtest")
        d = json.loads(path.read_text())
        return cls(RatingSettings(**d["ratings"]), PointsModel(**d["points"]), d.get("provenance", {}))
