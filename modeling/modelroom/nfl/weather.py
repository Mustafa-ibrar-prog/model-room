"""Pregame wind forecasts for NFL games at open-air stadiums (TEST only; read by the 0.1.6 shadow).

Source: the National Weather Service's GFS MOS station forecast (the same product the 0.1.6 coefficients were fitted on,
2021-23), read from the Iowa Environmental Mesonet's public mirror of NWS MOS output
(https://mesonet.agron.iastate.edu/api/1/mos.json). NWS data is public domain; IEM states its materials "are in the public
domain and may be used freely by anyone for any lawful purpose". Free, no key. The NWS gridded API (api.weather.gov) serves
a different product (the gridded/NBM forecast), so it would not match the fitted coefficients.

  fetch(games, now)        store the CURRENT forecast run for each open-air game kicking off within the next 40 h
  select(recs, game, ...)  the forecast a prediction made at `as_of` may use: the latest run ISSUED at least 5 h before
                           kickoff and RETRIEVED no later than `as_of`. Later runs (revisions) are never used.

Storage: ledger series `nfl_weather` (append-only, hash-chained, one record per game and forecast run). Each record keeps the
issue time (MOS run time), retrieval time, station, matched stadium and the raw 3-hourly wind speed (knots) and direction
around the game. A record can only be written before its game starts (the ledger rejects anything later).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from modelroom.common import ledger
from modelroom.common.hashing import hash_obj
from modelroom.common.paths import ledger_path

SOURCE = "nws-gfs-mos"
URL = "https://mesonet.agron.iastate.edu/api/1/mos.json?station={station}&model=GFS"
USER_AGENT = "ModelRoom-TEST (research shadow; github.com/Mustafa-ibrar-prog/model-room)"
KT_TO_MPH = 1.15078
LOOKAHEAD_HOURS = 40          # fetch for games kicking off within this window (forecast runs reach ~78 h ahead)
MIN_LEAD_HOURS = 5.0          # a run is usable only if issued at least this long before kickoff (as in the research)
GAME_MID_HOURS = 1.5          # wind is read at kickoff + 1.5 h, interpolated between the 3-hourly forecast times

# Home stadiums that are open-air EVERY game (nflverse stadium_id) and the airport station used in the research.
# Retractable roofs (ATL, DAL, HOU, IND, ARI), domes and neutral / international sites get no forecast: whether a roof
# is open is not reliably known in advance, and international venues have no GFS MOS station.
STATIONS = {"BAL00": "KBWI", "BOS00": "KOWD", "BUF00": "KBUF", "CAR00": "KCLT", "CHI98": "KMDW", "CIN00": "KLUK",
            "CLE00": "KBKL", "DEN00": "KDEN", "GNB00": "KGRB", "JAX00": "KJAX", "KAN00": "KMKC", "MIA00": "KOPF",
            "NAS00": "KBNA", "NYC01": "KTEB", "PHI00": "KPHL", "PIT00": "KAGC", "SEA00": "KBFI", "SFO01": "KSJC",
            "TAM00": "KTPA", "WAS00": "KDCA"}
FALLBACK = {"BOS00": "KBOS", "CIN00": "KCVG", "CLE00": "KCLE", "KAN00": "KMCI", "MIA00": "KMIA", "NYC01": "KEWR",
            "PIT00": "KPIT", "SEA00": "KSEA"}


def _utc(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def open_air(stadium_id) -> bool:
    return isinstance(stadium_id, str) and stadium_id in STATIONS


def _get(station: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(URL.format(station=station), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URL)
        return json.loads(r.read().decode())


def parse(payload: dict, station: str) -> tuple[pd.Timestamp, list[dict]]:
    """(issue time, rows) from the IEM MOS JSON. Raises ValueError on anything malformed: one run, numeric winds."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        raise ValueError("no forecast rows")
    runs = {str(r.get("runtime")) for r in data}
    if len(runs) != 1:
        raise ValueError(f"expected one forecast run, got {len(runs)}")
    issued = _utc(runs.pop())
    rows = []
    for r in data:
        ws, wd = r.get("wsp"), r.get("wdr")
        if ws is None or not isinstance(ws, (int, float)) or not np.isfinite(ws) or not 0 <= ws <= 100:
            continue                                   # a missing or impossible wind value is dropped, never guessed
        if wd is not None and (not isinstance(wd, (int, float)) or not 0 <= wd <= 360):
            wd = None
        rows.append({"valid": _utc(r["ftime"]).isoformat(), "wind_kt": float(ws), "wind_dir": None if wd is None else int(wd)})
    if not rows:
        raise ValueError("no valid wind values")
    return issued, rows


def fetch(games: pd.DataFrame, now: datetime | None = None, getter=_get) -> dict:
    """Store the current forecast run for every open-air game kicking off within LOOKAHEAD_HOURS.
    games: game_id, start_time (UTC), stadium_id. Never raises for a source problem: problems are returned in the summary
    and the shadow then falls back to the unchanged 0.1.5-based projection for that game."""
    now = _utc(now or datetime.now(timezone.utc))
    g = games[(games["start_time"] > now) & (games["start_time"] <= now + pd.Timedelta(hours=LOOKAHEAD_HOURS))]
    out = {"retrieved_at": now.isoformat(), "games": int(len(g)), "open_air": 0, "stored": 0, "duplicate": 0, "problems": []}
    recs = []
    cache: dict = {}
    for r in g.itertuples():
        if not open_air(getattr(r, "stadium_id", None)):
            continue
        out["open_air"] += 1
        kick = _utc(r.start_time)
        got = None
        for st in (STATIONS[r.stadium_id], FALLBACK.get(r.stadium_id)):
            if not st:
                continue
            try:
                if st not in cache:
                    cache[st] = parse(getter(st), st)
                got = (st, *cache[st])
                break
            except Exception as e:  # noqa: BLE001 - any source failure is recorded, never fatal
                cache.pop(st, None)
                out["problems"].append({"game_id": r.game_id, "station": st, "error": str(e)[:200]})
        if got is None:
            continue
        st, issued, rows = got
        if issued > now:
            out["problems"].append({"game_id": r.game_id, "station": st, "error": "issue time is in the future"})
            continue
        keep = [x for x in rows if kick - pd.Timedelta(hours=3) <= pd.Timestamp(x["valid"]) <= kick + pd.Timedelta(hours=6)]
        if not keep:
            out["problems"].append({"game_id": r.game_id, "station": st, "error": "forecast run does not reach this game"})
            continue
        body = {"source": SOURCE, "station": st, "issued_at": issued.isoformat(), "rows": keep}
        recs.append({"game_id": f"{r.game_id}|{issued.strftime('%Y%m%dT%H%MZ')}", "nfl_game_id": r.game_id, "stadium_id": r.stadium_id,
                     "model_version": SOURCE, "inputs_hash": hash_obj(body), "params_hash": None,
                     "generated_at": now.isoformat(timespec="seconds"), "retrieved_at": now.isoformat(timespec="seconds"),
                     "game_start": kick.isoformat(), **body})
    if recs:
        res = ledger.append_weekly(ledger_path("nfl_weather"), now.to_pydatetime(), recs)
        out["stored"], out["duplicate"] = res.appended, res.skipped_duplicate
    return out


def load() -> list[dict]:
    return ledger.read_series(ledger_path("nfl_weather"))


def select(recs: list[dict], game_id: str, kickoff, as_of, min_lead_hours: float = MIN_LEAD_HOURS) -> dict:
    """The forecast a prediction made at `as_of` may use. Returns {"usable": bool, "reason": str, ...}."""
    kick, as_of = _utc(kickoff), _utc(as_of)
    mine = [r for r in recs if r.get("nfl_game_id") == game_id and r.get("source") == SOURCE]
    if not mine:
        return {"usable": False, "reason": "no forecast stored"}
    seen = [r for r in mine if _utc(r["retrieved_at"]) <= as_of]
    if not seen:
        return {"usable": False, "reason": "no forecast retrieved before this prediction"}
    early = [r for r in seen if _utc(r["issued_at"]) <= kick - pd.Timedelta(hours=min_lead_hours)]
    if not early:
        return {"usable": False, "reason": f"no forecast issued at least {min_lead_hours:g} h before kickoff"}
    r = max(early, key=lambda x: (_utc(x["issued_at"]), -_utc(x["retrieved_at"]).value))   # latest run; its first copy
    mid = kick + pd.Timedelta(hours=GAME_MID_HOURS)
    pts = sorted(((pd.Timestamp(x["valid"]) - mid).total_seconds() / 3600, x["wind_kt"], x.get("wind_dir")) for x in r["rows"])
    t = np.array([p[0] for p in pts])
    if not len(t) or t.min() > 0 or t.max() < 0:
        return {"usable": False, "reason": "forecast does not cover the game"}
    kt = float(np.interp(0.0, t, [p[1] for p in pts]))
    near = min(pts, key=lambda p: abs(p[0]))
    return {"usable": True, "reason": "ok", "wind_mph": round(kt * KT_TO_MPH, 1), "wind_dir": near[2], "station": r["station"],
            "issued_at": r["issued_at"], "retrieved_at": r["retrieved_at"],
            "lead_hours": round((kick - _utc(r["issued_at"])).total_seconds() / 3600, 1), "record_hash": r.get("hash")}


def for_games(games: pd.DataFrame, as_of, recs: list[dict] | None = None) -> dict:
    """{game_id: selection} for every game; non-open-air games say so."""
    recs = load() if recs is None else recs
    out = {}
    for r in games.itertuples():
        if not open_air(getattr(r, "stadium_id", None)):
            out[r.game_id] = {"usable": False, "reason": "dome, retractable roof or neutral site: no adjustment"}
        else:
            out[r.game_id] = select(recs, r.game_id, r.start_time, as_of)
    return out
