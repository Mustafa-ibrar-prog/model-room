"""Model Room projection engines.

Layout:
  common/  infrastructure only (paths, downloads, hashing, metrics, linear
           algebra, prediction ledger, publishing). No league logic.
  nba/     NBA ingestion, ratings, projections, backtest.
  nfl/     NFL ingestion, ratings, projections, backtest.

The nba and nfl packages never import each other.
"""
