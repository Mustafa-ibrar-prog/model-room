"""Load the latest stored prices for a league and match them to projected players.

Used by the prop pipelines after the model has run. Reads only stored snapshots and the manual CSV;
never calls an exchange.
"""
from __future__ import annotations

import pandas as pd

from . import config as MC
from . import manual, matching, snapshots
from .schema import PropQuote


def _none(v):
    return None if isinstance(v, float) and v != v else v


def load(league: str, games: pd.DataFrame, players: pd.DataFrame) -> tuple[dict, dict, list[dict], list[dict]]:
    """games: game_id, game_date, home_team, away_team. players: game_id, player_id, name, team, sportradar_id.

    Returns (publishable quotes by (game_id, player_id), all quotes by the same key, provider info,
    unmatched publishable quotes)."""
    quotes: list[PropQuote] = []
    info = []
    for prov in MC.PROVIDERS:
        st = MC.status(prov)
        snap = snapshots.latest(league, prov) if st.enabled else pd.DataFrame()
        qs = [PropQuote(**{k: _none(v) for k, v in r.items() if k in PropQuote.__dataclass_fields__}) for r in snap.to_dict("records")] if len(snap) else []
        for q in qs:
            q.game_id = q.player_id = q.match_note = None
        info.append({"provider": prov, "enabled": st.enabled, "publishable": st.publishable, "reason": st.reason,
                     "quotes": len(qs), "last_captured_at": max((q.captured_at for q in qs), default=None)})
        quotes += qs
    mq, problems = manual.load(league)
    info.append({"provider": "manual", "enabled": True, "publishable": True, "reason": "manual CSV", "quotes": len(mq),
                 "last_captured_at": max((q.captured_at for q in mq), default=None), "rejected_rows": problems})
    quotes += mq
    matching.match_games(quotes, games)
    if len(players):
        matching.match_players(quotes, players)
    publishable = {i["provider"] for i in info if i["publishable"]}
    pub = [q for q in quotes if q.provider.split(":")[0] in publishable or q.provider.startswith("manual:")]

    def index(qs):
        idx: dict = {}
        for q in qs:
            if q.player_id and q.game_id:
                idx.setdefault((q.game_id, q.player_id), []).append(q)
        return idx

    unmatched = [{"provider": q.provider, "player": q.player_name, "market": q.market, "threshold": q.threshold, "note": q.match_note}
                 for q in pub if q.player_id is None][:200]
    return index(pub), index(quotes), info, unmatched
