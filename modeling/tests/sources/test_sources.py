import pandas as pd
import pytest

from modelroom.sources import land_of_basketball, odds
from modelroom.sources.profile import profile
from modelroom.sources.registry import REGISTRY

from ..conftest import real_nba, real_nfl


def test_registry_entries_are_complete():
    ids = [s.id for s in REGISTRY]
    assert len(ids) == len(set(ids))
    for s in REGISTRY:
        assert s.sport in ("nba", "nfl", "both")
        assert s.api_key in ("none", "optional", "required")
        assert s.status in ("collected", "optional", "manual", "reference-only", "unavailable")
        if s.status == "collected":
            assert s.collector and s.datasets, s.id
    # A required key is never the only route for a collected dataset.
    assert not [s for s in REGISTRY if s.status == "collected" and s.api_key == "required"]


def test_profile_counts_duplicates_and_missing():
    df = pd.DataFrame({"k": [1, 1, 2], "v": [1.0, None, 3.0]})
    p = profile(df, "t", keys=["k"], required=["v"])
    assert p.duplicate_keys == 1
    assert not p.ok
    assert next(c for c in p.columns if c["name"] == "v")["missing"] == 1


# SYNTHETIC markup mirroring Land of Basketball's results table layout (teams are fake).
LOB_HTML = """
<table class="color-alt"> <tbody><tr class="t-enc-5 a-left"> <td><h4 class="pad-l20 negri"><a href="/nba_daily_summary/20301021.htm">Oct 21, 2030</a></h4></td> </tr>
<tr class="a-top"><td><div class="clearfix"> <div class="left"> <div class="left a-left a-right-sm" style="width: 180px; ">Testville Alphas</div>
<div class="left a-right" style="width: 37px;"><a href="../box_scores/2030/1021TSATSB.htm"> 101</a></div> <div class="no-1 left">-</div> </div>
<div class="left"> <div class="left right-sm" style="width: 180px; ">Sampletown Betas</div>
<div class="left a-right a-left-sm" style="width: 37px ; "><a href="../box_scores/2030/1021TSATSB.htm"><b> 109</b></a></div></div> OT</div></td></tr>
</tbody></table>
"""


def test_land_of_basketball_parser():
    rows = land_of_basketball.parse(LOB_HTML)
    assert rows == [["Oct 21, 2030", "Testville Alphas", 101, "Sampletown Betas", 109, "OT"]]


def test_land_of_basketball_urls_stay_on_results_pages():
    url = land_of_basketball.page_url(2027, "nov")
    assert url.endswith("/results/2026_2027_nov_scores.htm") and "box_scores" not in url
    assert land_of_basketball.CRAWL_DELAY_S >= 20


def _manual(**over):
    row = {"game_date": "2030-01-02", "home_team": "BOS", "away_team": "NY", "sportsbook": "examplebook",
           "market": "spread", "line": -3.5, "home_price": -110, "away_price": -110, "over_price": None,
           "under_price": None, "captured_at": "2030-01-02T10:00:00-05:00", "entered_by": "test", "note": ""}
    row.update(over)
    return pd.DataFrame([row])


def test_manual_lines_accepts_valid_row():
    valid, problems = odds.validate_manual(_manual())
    assert len(valid) == 1 and not problems


@pytest.mark.parametrize(
    "over, msg",
    [
        ({"captured_at": "2030-01-02 10:00"}, "timezone"),
        ({"line": None}, "line is required"),
        ({"home_price": -50}, "American odds"),
        ({"sportsbook": ""}, "sportsbook is required"),
        ({"market": "parlay"}, "market must be"),
    ],
)
def test_manual_lines_rejects_bad_rows(over, msg):
    valid, problems = odds.validate_manual(_manual(**over))
    assert len(valid) == 0 and msg in problems[0]


def test_parse_odds_api_shape():
    # SYNTHETIC response in The Odds API v4 format.
    events = [{
        "id": "x", "commence_time": "2030-01-03T00:30:00Z", "home_team": "Home Club", "away_team": "Away Club",
        "bookmakers": [{"key": "examplebook", "last_update": "2030-01-02T20:00:00Z", "markets": [
            {"key": "spreads", "last_update": "2030-01-02T20:00:00Z", "outcomes": [
                {"name": "Home Club", "price": -110, "point": -4.5}, {"name": "Away Club", "price": -110, "point": 4.5}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": -105, "point": 221.5},
                                           {"name": "Under", "price": -115, "point": 221.5}]},
        ]}],
    }]
    df = odds.parse_odds_api(events, "nba")
    sp = df[df["market"] == "spread"].iloc[0]
    assert sp["line"] == -4.5 and sp["sportsbook"] == "examplebook" and sp["captured_at"] == "2030-01-02T20:00:00Z"
    tot = df[df["market"] == "total"].iloc[0]
    assert tot["line"] == 221.5 and tot["over_price"] == -105


def test_consensus_uses_latest_per_book_then_median():
    snaps = pd.DataFrame([
        {"game_id": "g", "market": "spread", "sportsbook": "a", "line": -3.0, "captured_at": "2030-01-01T00:00:00Z", "source": "s"},
        {"game_id": "g", "market": "spread", "sportsbook": "a", "line": -4.0, "captured_at": "2030-01-01T05:00:00Z", "source": "s"},
        {"game_id": "g", "market": "spread", "sportsbook": "b", "line": -5.0, "captured_at": "2030-01-01T03:00:00Z", "source": "s"},
    ])
    c = odds.consensus(snaps).iloc[0]
    assert c["line"] == -4.5 and c["books"] == 2


@real_nba
@real_nfl
def test_real_data_passes_validation():
    from modelroom.sources import validate

    report = validate.run("all")
    failed = [(d["dataset"], c["name"]) for d in report["datasets"] for c in d["checks"] if not c["ok"]]
    assert not failed, failed
