"""Manual prop lines (fallback when no exchange lists a market): data/manual/<league>_props.csv.

Columns (template: modeling/templates/props_template.csv)
  source        where the price came from (e.g. a sportsbook name, or "exchange-screen")
  game_date     YYYY-MM-DD (US Eastern date of the game)
  home_team, away_team, team   Model Room team codes (nflverse: KC, LA, LAC, JAX, ...)
  player        player name as listed
  market        receiving_yards, receptions, passing_yards, anytime_td, ... (see schema.NFL_MARKETS)
  op            ">=" for "N or more" contracts, ">" for over/under lines like 54.5
  threshold     N or the line
  yes_bid, yes_ask   exchange-style prices 0-1 (either side may be blank)
  over_odds, under_odds   OR sportsbook American odds for over / under
  captured_at   when you copied the price, with timezone (2026-11-02T18:30:00-08:00)

Rows that fail validation are reported and skipped. Nothing is filled in.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from modelroom.common.paths import data_root

from .schema import NBA_MARKETS, NFL_MARKETS, PropQuote, price, to_float

COLUMNS = ["source", "game_date", "home_team", "away_team", "team", "player", "market", "op", "threshold",
           "yes_bid", "yes_ask", "over_odds", "under_odds", "captured_at", "note"]


def path(league: str):
    return data_root() / "manual" / f"{league}_props.csv"


def american_to_prob(odds) -> float | None:
    o = to_float(odds)
    if o is None or -100 < o < 100:
        return None
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def load(league: str, file=None) -> tuple[list[PropQuote], list[str]]:
    f = file or path(league)
    if not f.exists():
        return [], []
    df = pd.read_csv(f, dtype=str).fillna("")
    allowed = set(NFL_MARKETS if league == "nfl" else NBA_MARKETS)
    quotes, problems = [], []
    for i, r in df.iterrows():
        row = i + 2
        missing = [c for c in ("source", "game_date", "home_team", "away_team", "player", "market", "op", "threshold", "captured_at") if not r.get(c)]
        if missing:
            problems.append(f"row {row}: missing {', '.join(missing)}")
            continue
        if r["market"] not in allowed:
            problems.append(f"row {row}: unknown market {r['market']!r}")
            continue
        if r["op"] not in (">=", ">"):
            problems.append(f"row {row}: op must be >= or >")
            continue
        thr = to_float(r["threshold"])
        if thr is None:
            problems.append(f"row {row}: threshold is not a number")
            continue
        try:
            ts = datetime.fromisoformat(r["captured_at"])
            if ts.tzinfo is None:
                raise ValueError
        except ValueError:
            problems.append(f"row {row}: captured_at needs a date, time and timezone")
            continue
        yb, ya = price(r.get("yes_bid")), price(r.get("yes_ask"))
        po, pu = american_to_prob(r.get("over_odds")), american_to_prob(r.get("under_odds"))
        if r.get("over_odds") and po is None or r.get("under_odds") and pu is None:
            problems.append(f"row {row}: odds must be American (e.g. -115, +130)")
            continue
        if yb is None and ya is None and po is None and pu is None:
            problems.append(f"row {row}: no price (yes_bid / yes_ask or over_odds / under_odds)")
            continue
        q = PropQuote(
            provider=f"manual:{r['source']}", league=league, market=r["market"], op=r["op"], threshold=thr,
            player_name=r["player"], team=r.get("team") or None, game_date=r["game_date"], home_team=r["home_team"],
            away_team=r["away_team"], yes_bid=yb, yes_ask=ya if ya is not None else po,
            no_bid=(1 - ya) if ya is not None else None, no_ask=(1 - yb) if yb is not None else pu,
            fee_rate=0.0, status="manual", title=r.get("note") or None, captured_at=ts.isoformat(),
            void_rule="as stated by the source",
        )
        quotes.append(q)
    return quotes, problems
