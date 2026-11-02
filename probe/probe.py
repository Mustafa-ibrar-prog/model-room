"""One-off, read-only probe of Kalshi public market data (no auth) + Polymarket US NFL slate. Round 3."""
import json, time, urllib.request, urllib.parse, os, collections
out = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "calls": []}
os.makedirs("probe/out3", exist_ok=True)
K = "https://api.elections.kalshi.com/trade-api/v2"
P = "https://gateway.polymarket.us"

def get(url, params=None, save=None, pause=0.6):
    url = url + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    rec = {"url": url}
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "model-room-probe/1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode(); rec["status"] = r.status; rec["headers"] = dict(r.headers.items())
    except urllib.error.HTTPError as e:
        rec["status"] = e.code; body = e.read().decode()[:2000]
    except Exception as e:
        rec["status"] = None; body = repr(e)
    rec["bytes"] = len(body); out["calls"].append(rec)
    if save: open(f"probe/out3/{save}.json", "w").write(body)
    time.sleep(pause)
    try: return json.loads(body)
    except Exception: return None

# Kalshi: all sports series
series = []
cursor = None
d = get(K + "/series", {"category": "Sports"}, save="k_series_sports")
series = (d or {}).get("series") or []
nflnba = [s for s in series if any(x in (s.get("ticker", "") + s.get("title", "")).upper() for x in ("NFL", "NBA", "FOOTBALL", "BASKETBALL"))]
json.dump([{k: s.get(k) for k in ("ticker", "title", "frequency", "tags", "settlement_sources", "contract_url")} for s in nflnba], open("probe/out3/k_series_nflnba.json", "w"), indent=1)
summary = {"kalshi_series_total": len(series), "kalshi_nfl_nba_series": len(nflnba), "series_events": {}}
for s in nflnba:
    t = s["ticker"]
    if not any(w in (t + s.get("title", "")).upper() for w in ("YD", "YARD", "REC", "TD", "TOUCHDOWN", "PASS", "RUSH", "PTS", "POINT", "REB", "AST", "PRA", "PLAYER", "3PT", "THREE", "STL", "BLK", "INT", "FANTASY")):
        continue
    e = get(K + "/events", {"series_ticker": t, "status": "open", "with_nested_markets": "true", "limit": 20}, save=f"k_ev_{t}")
    evs = (e or {}).get("events") or []
    ms = [m for ev in evs for m in ev.get("markets", [])]
    summary["series_events"][t] = {"title": s.get("title"), "open_events": len(evs), "markets": len(ms),
        "examples": [{k: m.get(k) for k in ("ticker", "title", "subtitle", "yes_sub_title", "floor_strike", "strike_type", "yes_bid", "yes_ask", "yes_bid_dollars", "yes_ask_dollars", "liquidity", "liquidity_dollars", "volume", "open_interest", "close_time", "last_price")} for m in ms[:4]]}
# orderbook sample
for t, v in summary["series_events"].items():
    if v["examples"]:
        get(K + f"/markets/{v['examples'][0]['ticker']}/orderbook", save=f"k_ob_{t}"); break
# Polymarket: NFL week slate list via sports endpoints
get(P + "/v1/sports/nfl/events", {"limit": 50}, save="p_nfl_events_a")
get(P + "/v1/sports/events", {"limit": 50, "league": "nfl"}, save="p_nfl_events_b")
get(P + "/v1/events", {"limit": 50, "seriesSlug": "nfl-2025", "active": "true", "closed": "false"}, save="p_nfl_events_c")
json.dump(summary, open("probe/out3/_summary.json", "w"), indent=1)
json.dump(out, open("probe/out3/_calls.json", "w"), indent=1)
print(json.dumps(summary, indent=1)[:5000])
