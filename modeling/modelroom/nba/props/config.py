"""NBA player-prop model settings and the markets it prices."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

MODEL_ID = "nba-props"
MODEL_VERSION = "0.1.0"
PARAMS_FILE = Path(__file__).with_name("params.json")
CANDIDATE_VERSION = "0.2.0"
CANDIDATE_FILE = Path(__file__).with_name("params_0.2.0.json")  # candidate; not used live until approved
INJURY_VERSION = "0.2.1"
INJURY_FILE = Path(__file__).with_name("params_0.2.1.json")      # 0.2.0 + the live injury feed (test site)

HISTORY_SEASONS = 2                  # earlier seasons used alongside the current one (hoopR season = end year)
TUNE_SEASONS = (2021, 2022)          # 2020-21, 2021-22
TEST_SEASONS = (2023, 2024, 2025, 2026)  # 2022-23 to 2025-26, same held-out window as the NBA game engine
TEAM_MINUTES = 240.0 * 1.012         # regulation minutes plus the average overtime share


@dataclass(frozen=True)
class PropSettings:
    minutes_half_life: float = 6.0     # recent games dominate minutes (role changes fast)
    rate_half_life: float = 20.0       # per-minute production is steadier
    season_carry: float = 0.5
    def_half_life: float = 20.0        # opponent games
    rate_prior_minutes: float = 250.0  # per-minute rates pulled toward the position average
    def_prior_minutes: float = 1500.0  # defense-vs-position ratios pulled toward 1
    minutes_sd: float = 5.0            # game-to-game minutes noise (conditional on playing)
    scoring_sd: float = 0.25           # lognormal "shooting night" shock shared by 2s, 3s and free throws
    rebound_sd: float = 0.25
    assist_sd: float = 0.25
    stock_sd: float = 0.25             # steals and blocks
    matchup_strength: float = 1.0      # exponent on opponent defense-vs-position ratios
    pace_strength: float = 1.0         # exponent on projected game pace / the team's usual pace
    usage_boost: float = 0.5           # extra scoring/assists from teammates' missing usage (0 = none)
    blowout_strength: float = 0.02     # starters' minutes cut per point of projected margin beyond 6
    missed_games_out: int = 2          # a rotation player who missed the team's last N games is treated as out
    # 0.2 foundation settings. Defaults reproduce 0.1 exactly.
    rate_prior_kind: str = "position"  # per-minute rates pulled toward the position average, or toward players
                                       # in the same role ("role": position x minutes band), so bench players
                                       # aren't lifted to starter rates
    minutes_fill: str = "scale"        # "scale": every active player's minutes scaled to fill 240 (stars too);
                                       # "headroom": missing minutes go to players in proportion to their room
                                       # below their own recent high, extra minutes are trimmed pro rata
    usage_decay: float = 0.0           # 1 = freed usage from an absent teammate fades as his absence ages
                                       # (teammates' recent rates already include it); 0 = full boost always
    # 0.2.1 injury-feed settings. Defaults reproduce 0.2.0 exactly (and leave its params hash unchanged).
    injury_feed: bool = False          # availability from the injury feed (official NBA report, ESPN) for each game,
                                       # ahead of the "missed the last N games" rule; that rule stays the fallback
    doubtful_weight: float = 0.75      # share of a Doubtful player's usage treated as freed (as in the game model)
    return_minutes: tuple = ()         # minutes multiplier in a player's 1st, 2nd, 3rd... game back after missing 3+
                                       # (measured on box scores, fit 2016-22: see params_0.2.1.json provenance)
    return_sd_factor: tuple = ()       # minutes_sd multiplier in those games (their minutes are less predictable)
    # 0.2.2 (experimental) play-probability settings. Defaults reproduce 0.2.1 exactly.
    play_bands: tuple = ()             # minutes-when-playing band edges for the play-probability tables, e.g. (8, 16, 24)
    play_prob_available: tuple = ()    # P(plays | listed Available or Probable at the final pregame report), per band;
                                       # empty = 0.2.1's rule (an Available player is certain to play)
    play_prob_questionable: tuple = () # P(plays | listed Questionable), per band; empty = his recent appearance rate
    unlisted_clears: bool = True       # 0.2.1: a player absent from a submitted report counts as cleared even after a
                                       # long absence. False = the missed-games rule still applies to him (measured:
                                       # such players play ~12% of the time; most have left the team)
    minutes_gap_fill: float = 1.0      # share of the team's unclaimed minutes (240 minus expected minutes) handed out to
                                       # the active players; 1 = all (0.2.0-0.2.2). Fitted on 2023-24 for 0.2.3
    lineup_scenarios: int = 0          # up to this many uncertain rotation players are simulated as playing / sitting
                                       # (2^k lineups); teammates' minutes and usage are filled per lineup. 0 = off
    sims: int = 4000


ADDED_SETTINGS = ("injury_feed", "doubtful_weight", "return_minutes", "return_sd_factor",
                  "play_bands", "play_prob_available", "play_prob_questionable", "unlisted_clears", "lineup_scenarios", "minutes_gap_fill")


@dataclass(frozen=True)
class PropParams:
    settings: PropSettings = field(default_factory=PropSettings)
    calibration: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        d = {"model_id": MODEL_ID, "model_version": MODEL_VERSION, **asdict(self)}
        # Settings added after a version shipped are left out while at their default, so that version's
        # params hash (stored in every ledger record) stays exactly what it was.
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
        st = {k: (tuple(v) if isinstance(v, list) else v) for k, v in d["settings"].items() if k in known}
        return cls(PropSettings(**st), d.get("calibration", {}), d.get("provenance", {}))

    def calibrate(self, market: str, p: float) -> float:
        ab = self.calibration.get(market)
        if not ab:
            return p
        q = min(max(p, 1e-4), 1 - 1e-4)
        return 1.0 / (1.0 + math.exp(-(ab[0] + ab[1] * math.log(q / (1 - q)))))


MARKETS: dict[str, dict] = {
    "points": {"stat": "pts", "label": "Points", "ladder": [5, 10, 15, 20, 25, 30, 35, 40]},
    "rebounds": {"stat": "reb", "label": "Rebounds", "ladder": [2, 4, 6, 8, 10, 12, 14]},
    "assists": {"stat": "ast", "label": "Assists", "ladder": [2, 4, 6, 8, 10, 12]},
    "pra": {"stat": "pra", "label": "Pts + reb + ast", "ladder": [10, 15, 20, 25, 30, 35, 40, 45, 50]},
    "threes": {"stat": "fg3m", "label": "Threes made", "ladder": [1, 2, 3, 4, 5, 6]},
    "steals": {"stat": "stl", "label": "Steals", "ladder": [1, 2, 3]},
    "blocks": {"stat": "blk", "label": "Blocks", "ladder": [1, 2, 3]},
}

# History behind a projection: (ok, limited) thresholds on games played and minutes in the model's window.
SUPPORT = {"games": (15, 5), "minutes": (300, 100)}


def support_level(n_games: int, n_minutes: float) -> tuple[str, str]:
    g_hi, g_lo = SUPPORT["games"]
    m_hi, m_lo = SUPPORT["minutes"]
    note = f"{n_games} games, {int(n_minutes)} minutes"
    if n_games >= g_hi and n_minutes >= m_hi:
        return "ok", note
    if n_games >= g_lo and n_minutes >= m_lo:
        return "limited", "only " + note
    return "insufficient", "only " + note
