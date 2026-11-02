import pandas as pd

from modelroom.nfl import ingest

from ..conftest import real_nfl


def test_franchise_mapping_covers_relocations():
    assert ingest.FRANCHISE == {"OAK": "LV", "SD": "LAC", "STL": "LA"}


def test_spread_converted_to_home_convention(tmp_data):
    # SYNTHETIC games.csv row: nflverse spread_line +3 means the HOME team is favored by 3.
    raw = tmp_data / "raw" / "nfl"
    raw.mkdir(parents=True)
    cols = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "away_score", "home_team",
            "home_score", "location", "overtime", "away_rest", "home_rest", "away_moneyline", "home_moneyline",
            "spread_line", "away_spread_odds", "home_spread_odds", "total_line", "under_odds", "over_odds", "div_game",
            "roof", "surface", "temp", "wind", "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name",
            "stadium_id", "stadium", "old_game_id", "gsis", "espn"]
    row = {c: None for c in cols}
    row.update(game_id="2030_01_OAK_SD", season=2030, game_type="REG", week=1, gameday="2030-09-08", gametime="13:00",
               away_team="OAK", home_team="SD", location="Home", away_rest=7, home_rest=7, spread_line=3.0,
               total_line=44.5, div_game=1)
    pd.DataFrame([row]).to_csv(raw / "games.csv", index=False)
    games, market = ingest.build_games()
    assert games.iloc[0]["home_team"] == "LAC" and games.iloc[0]["away_team"] == "LV"
    spread = market[market["market"] == "spread"].iloc[0]
    assert spread["line"] == -3.0
    assert spread["captured_at"] is None and "not document" in spread["capture_note"]
    assert str(games.iloc[0]["start_time"]) == "2030-09-08 17:00:00+00:00"  # 1 PM Eastern


@real_nfl
def test_real_pbp_has_required_columns():
    pbp = pd.read_parquet(ingest.processed_dir("nfl") / "pbp.parquet")
    assert set(ingest.PBP_COLUMNS) <= set(pbp.columns)
    assert pbp["season"].nunique() >= 3
