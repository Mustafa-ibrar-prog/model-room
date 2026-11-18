"""Only the published prop version ever becomes a pick or a shown result; shadows sharing a ledger are ignored."""
import re
from pathlib import Path

from modelroom import published as PUB
from modelroom.history import _pregame

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "preview.yml"


def _env(name):
    m = re.search(rf"^\s*{name}:\s*\"([^\"]*)\"", WORKFLOW.read_text(), re.M)
    return m.group(1) if m else None


def test_timeline_matches_the_workflow():
    for lg in ("nba", "nfl"):
        assert PUB.TIMELINE[lg][-1][1] == _env(f"MODELROOM_{lg.upper()}_PROPS_VERSION"), \
            f"{lg}: add the active-version switch to modelroom/published.py"
        shadows = [v for v in (_env(f"MODELROOM_{lg.upper()}_PROPS_SHADOW") or "").split(",") if v]
        assert PUB.TIMELINE[lg][-1][1] not in shadows


def test_published_version_at_switches():
    assert PUB.published_version("nba", "2026-11-03T12:00:00+00:00") == "0.1.0"
    assert PUB.published_version("nba", "2026-11-05T00:00:00+00:00") == "0.2.1"
    assert PUB.published_version("nba", "2026-11-08T02:22:42+00:00") == "0.2.1"
    assert PUB.published_version("nba", "2026-11-08T02:22:43+00:00") == "0.2.0"
    assert PUB.published_version("nfl", "2026-11-04T17:00:00+00:00") == "0.1.0"
    assert PUB.published_version("nfl", "2026-11-20T00:00:00+00:00") == "0.1.1"


def test_shadow_record_never_wins_even_when_newer():
    base = {"game_id": "g|p", "game_start": "2026-11-20T01:00:00+00:00"}
    recs = [{**base, "model_version": "0.1.1", "generated_at": "2026-11-19T20:00:00+00:00"},
            {**base, "model_version": "0.1.5", "generated_at": "2026-11-20T00:30:00+00:00"},   # newer shadow
            {**base, "model_version": "0.1.0", "generated_at": "2026-11-20T00:31:00+00:00"}]   # newer shadow
    kept = _pregame([r for r in recs if PUB.is_published("nfl", r)])
    assert kept["g|p"]["model_version"] == "0.1.1"
    # the old behaviour, for the record: the newest record of any version would have been used
    assert _pregame(recs)["g|p"]["model_version"] == "0.1.0"
