"""Every data source Model Room uses or has evaluated, with the facts behind the decision.

Terms and robots.txt were checked on 2026-11-02. Re-check before a paid launch.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    sport: str                      # "nba", "nfl" or "both"
    categories: tuple[str, ...]
    official: bool                  # published by the league itself
    api_key: str                    # "none", "optional", "required"
    status: str                     # "collected", "optional", "manual", "reference-only", "unavailable"
    access: str                     # how it is retrieved
    license: str
    update_frequency: str
    historical_coverage: str
    limitations: tuple[str, ...] = ()
    priority: int = 50              # lower wins when sources conflict
    crawl_delay_s: float = 0.0
    collector: str | None = None    # CLI target that refreshes it
    datasets: tuple[str, ...] = field(default_factory=tuple)  # processed tables it feeds


REGISTRY: tuple[Source, ...] = (
    # ------------------------------------------------------------------ NFL
    Source(
        id="nflverse_games", name="nflverse schedules and results (nfldata games.csv)", sport="nfl",
        categories=("schedules", "scores", "spreads", "totals", "moneylines", "rest", "starting QBs", "stadium", "roof", "weather"),
        official=False, api_key="none", status="collected",
        access="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
        license="nflverse data, CC-BY 4.0 (credit nflverse)",
        update_frequency="about every 5 minutes in season",
        historical_coverage="1999 to the current season (lines from 1999)",
        limitations=(
            "spread_line is positive when the HOME team is favored; converted on ingest",
            "capture time of spread_line/total_line is not documented; treated as a late line, not a verified close",
            "one line per game; no sportsbook name and no line history",
        ),
        priority=20, collector="nfl ingest", datasets=("processed/nfl/games.parquet", "processed/nfl/market_lines.parquet"),
    ),
    Source(
        id="nflverse_pbp", name="nflverse play-by-play", sport="nfl",
        categories=("play-by-play", "EPA", "success rate", "win probability", "passing", "rushing", "QB"),
        official=False, api_key="none", status="collected",
        access="https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_<season>.parquet (or a local folder)",
        license="nflverse data, CC-BY 4.0 (credit nflverse)",
        update_frequency="nightly after game days; stat corrections settle by Thursday",
        historical_coverage="1999 to the current season",
        limitations=("GitHub release file: downloads on your PC; the cloud build environment cannot fetch it",),
        priority=20, collector="nfl ingest", datasets=("processed/nfl/pbp.parquet",),
    ),
    Source(
        id="nflverse_injuries", name="nflverse injury reports", sport="nfl",
        categories=("injuries", "practice participation", "game status"),
        official=False, api_key="none", status="collected",
        access="https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_<season>.parquet",
        license="nflverse data, CC-BY 4.0",
        update_frequency="during the season (nflverse does not publish an exact schedule)",
        historical_coverage="2009 to the current season",
        limitations=("mirrors the NFL's official injury reports; check freshness before games",),
        priority=30, collector="nfl ingest", datasets=("processed/nfl/injuries.parquet",),
    ),
    Source(
        id="nfl_com", name="NFL.com", sport="nfl",
        categories=("schedules", "scores", "standings", "team stats", "player stats", "rosters", "injuries"),
        official=True, api_key="none", status="reference-only",
        access="public web pages",
        license="NFL Terms: no robots/spiders collecting information 'for any commercial purpose'",
        update_frequency="live",
        historical_coverage="varies by page",
        limitations=(
            "robots.txt allows most pages, but the Terms forbid automated collection for commercial use",
            "used for manual verification only until the data is licensed",
        ),
        priority=10,
    ),
    # ------------------------------------------------------------------ NBA
    Source(
        id="hoopr_schedule", name="hoopR NBA schedules (sportsdataverse, from ESPN)", sport="nba",
        categories=("schedules", "scores", "status", "neutral site", "venue", "periods/OT"),
        official=False, api_key="none", status="collected",
        access="https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/schedules/parquet/nba_schedule_<season>.parquet",
        license="hoopR code MIT; data scraped from ESPN, ESPN terms apply",
        update_frequency="daily",
        historical_coverage="2002 to the current season (Model Room uses 2015-16 onward)",
        limitations=("ESPN-derived, not official league records", "season named by end year (2027 = 2026-27)"),
        priority=30, collector="nba ingest", datasets=("processed/nba/games.parquet",),
    ),
    Source(
        id="hoopr_team_box", name="hoopR NBA team box scores", sport="nba",
        categories=("team box scores", "possession inputs", "efficiency", "pace"),
        official=False, api_key="none", status="collected",
        access="https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/team_box/parquet/team_box_<season>.parquet",
        license="hoopR code MIT; data scraped from ESPN, ESPN terms apply",
        update_frequency="daily",
        historical_coverage="2002 to the current season",
        limitations=("2017-18 file lacks team turnovers; player turnovers used (about one possession low per game)",),
        priority=30, collector="nba ingest", datasets=("processed/nba/team_games.parquet",),
    ),
    Source(
        id="hoopr_player_box", name="hoopR NBA player box scores", sport="nba",
        categories=("player box scores", "minutes", "inactive players with reason"),
        official=False, api_key="none", status="collected",
        access="https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/player_box/parquet/player_box_<season>.parquet",
        license="hoopR code MIT; data scraped from ESPN, ESPN terms apply",
        update_frequency="daily",
        historical_coverage="2002 to the current season",
        limitations=("inactive reasons are free text",),
        priority=30, collector="nba ingest", datasets=("processed/nba/player_games.parquet",),
    ),
    Source(
        id="land_of_basketball", name="Land of Basketball results", sport="nba",
        categories=("final scores", "overtime"),
        official=False, api_key="none", status="collected",
        access="https://www.landofbasketball.com/results/<YYYY>_<YYYY>_<mon>_scores.htm",
        license="All rights reserved; used only to cross-check final scores, never republished",
        update_frequency="daily",
        historical_coverage="1946-47 to the current season",
        limitations=(
            "robots.txt: /box_scores and player stats pages are off limits; 20 s crawl delay honored",
            "scores and team names only (no box-score stats)",
        ),
        priority=40, crawl_delay_s=20.0, collector="nba crosscheck",
        datasets=("processed/nba/crosscheck_lob.parquet",),
    ),
    Source(
        id="statscrew", name="StatsCrew NBA team season statistics", sport="nba",
        categories=("team season totals", "standings"),
        official=False, api_key="none", status="reference-only",
        access="https://www.statscrew.com/basketball/l-NBA/y-<season start>",
        license="site terms apply",
        update_frequency="during the season",
        historical_coverage="1946-47 onward",
        limitations=("season-level totals only, not game level; robots.txt crawl delay 5 s",),
        priority=45, crawl_delay_s=5.0,
    ),
    Source(
        id="nba_com", name="NBA.com / stats.nba.com / cdn.nba.com", sport="nba",
        categories=("schedules", "scores", "standings", "team stats", "player stats", "box scores", "rosters", "injury report"),
        official=True, api_key="none", status="reference-only",
        access="public web pages; the data CDN refuses direct downloads (Access Denied)",
        license=(
            "NBA Terms (updated 2026-07-13): NBA Statistics may not be used in connection with any gambling activity, "
            "commercial products, or comprehensive regularly updated databases without NBA consent"
        ),
        update_frequency="live",
        historical_coverage="1946-47 onward",
        limitations=(
            "robots.txt disallows /api/* and blocks AI crawlers",
            "use is incompatible with a betting-analytics product without a license; manual verification only",
        ),
        priority=10,
    ),
    # ---------------------------------------------------------------- ODDS
    Source(
        id="the_odds_api", name="The Odds API", sport="both",
        categories=("spreads", "totals", "moneylines", "sportsbook", "timestamp"),
        official=False, api_key="optional", status="optional",
        access="https://api.the-odds-api.com/v4/sports/<sport>/odds (ODDS_API_KEY)",
        license="commercial API terms",
        update_frequency="on request (poll)",
        historical_coverage="historical snapshots from 2020 on paid plans",
        limitations=(
            "needs a key: no public NBA line feed exists that sportsbook terms allow automated access to",
            "free tier is 500 credits a month",
        ),
        priority=20, collector="nba odds",
        datasets=("processed/<league>/market_lines.parquet",),
    ),
    Source(
        id="manual_lines", name="Manual line entry (CSV)", sport="both",
        categories=("spreads", "totals", "moneylines", "sportsbook", "timestamp"),
        official=False, api_key="none", status="manual",
        access="data/manual/<league>_lines.csv (template in modeling/templates/lines_template.csv)",
        license="your own records",
        update_frequency="whenever entered",
        historical_coverage="whatever is entered",
        limitations=("validated on ingest: book, market, timestamp and line are required",),
        priority=25, collector="<league> lines",
        datasets=("processed/<league>/market_lines.parquet",),
    ),
    Source(
        id="sportsbook_sites", name="Sportsbook websites (DraftKings, FanDuel, BetMGM, ...)", sport="both",
        categories=("spreads", "totals", "moneylines"),
        official=False, api_key="none", status="unavailable",
        access="n/a",
        license="sportsbook terms prohibit automated access; pages require location checks",
        update_frequency="live",
        historical_coverage="none (current lines only)",
        limitations=("not collected",),
    ),
    Source(
        id="sbro_archive", name="SportsbookReviewsOnline odds archive", sport="both",
        categories=("historical closing lines",),
        official=False, api_key="none", status="unavailable",
        access="archive URL now redirects to an advertising page (checked 2026-11-02)",
        license="n/a",
        update_frequency="n/a",
        historical_coverage="formerly 2007 onward",
        limitations=("no longer published",),
    ),
    Source(
        id="licensed_feeds", name="Licensed official data (Sportradar, Genius Sports, SportsDataIO)", sport="both",
        categories=("official stats", "injuries", "odds"),
        official=True, api_key="required", status="optional",
        access="commercial contract",
        license="covers commercial and betting-adjacent use when contracted",
        update_frequency="live",
        historical_coverage="full",
        limitations=("cost and terms by quote; evaluate before a paid launch",),
        priority=5,
    ),
)


def get(source_id: str) -> Source:
    for s in REGISTRY:
        if s.id == source_id:
            return s
    raise KeyError(source_id)
