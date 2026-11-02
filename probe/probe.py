"""One-off read-only probe round 4: order books and historical prices (Polymarket US, Kalshi)."""
import json, time, urllib.request, urllib.parse, os
os.makedirs("probe/out4", exist_ok=True)
out = {"calls": []}
P = "https://gateway.polymarket.us"; K = "https://api.elections.kalshi.com/trade-api/v2"
def get(url, params=None, save=None):
    url = url + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    rec = {"url": url}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "model-room-probe/1"}), timeout=30) as r:
            body = r.read().decode(); rec["status"] = r.status
    except urllib.error.HTTPError as e:
        rec["status"] = e.code; body = e.read().decode()[:3000]
    except Exception as e:
        rec["status"] = None; body = repr(e)
    rec["bytes"] = len(body); out["calls"].append(rec)
    if save: open(f"probe/out4/{save}.json", "w").write(body)
    time.sleep(1.5)
    try: return json.loads(body)
    except Exception: return None
ev = get(P + "/v1/events/slug/nfl-jax-bal-2026-11-05")
ev = (ev or {}).get("event", ev) or {}
pm = [m for m in ev.get("markets", []) if m.get("sportsMarketType") == "football_player_receiving_yards"][:2]
for i, m in enumerate(pm):
    get(P + f"/v1/markets/{m['slug']}/book", save=f"pm_book_{i}")
    get(P + f"/v1/markets/{m['slug']}/bbo", save=f"pm_bbo_{i}")
for j, params in enumerate(({"slug": pm[0]["slug"]}, {"marketSlug": pm[0]["slug"]}, {"market": pm[0]["slug"]}, {"slug": pm[0]["slug"], "interval": "1h"}) if pm else []):
    get(P + "/v1/price-history", params, save=f"pm_hist_{j}")
for slug in ("nfl-gb-pit-2026-10-26", "nfl-was-kc-2026-10-27", "nfl-den-dal-2026-10-26", "nfl-kc-was-2026-10-26"):
    d = get(P + f"/v1/events/slug/{slug}", save="pm_past_" + slug)
    d = (d or {}).get("event", d) or {}
    if d.get("markets"):
        ms = [m for m in d["markets"] if m.get("sportsMarketType") == "football_player_receiving_yards"][:2]
        for i, m in enumerate(ms):
            get(P + f"/v1/markets/{m['slug']}/settlement", save=f"pm_settle_{i}")
            get(P + "/v1/price-history", {"slug": m["slug"]}, save=f"pm_hist_past_{i}")
        json.dump([{k: m.get(k) for k in ("slug", "closed", "active", "status", "bestBidQuote", "bestAskQuote", "lastTradePrice", "line")} for m in ms], open("probe/out4/pm_past_markets.json", "w"), indent=1)
        break
s = get(K + "/events", {"series_ticker": "KXNFLRECYDS", "status": "settled", "with_nested_markets": "true", "limit": 3}, save="k_settled")
mk = [m for e in (s or {}).get("events", []) for m in e.get("markets", [])][:2]
for i, m in enumerate(mk):
    t = m["ticker"]; end = int(time.time()); start = end - 21 * 86400
    get(K + f"/series/KXNFLRECYDS/markets/{t}/candlesticks", {"start_ts": start, "end_ts": end, "period_interval": 60}, save=f"k_candles_{i}")
    get(K + "/markets/trades", {"ticker": t, "limit": 50}, save=f"k_trades_{i}")
o = get(K + "/events", {"series_ticker": "KXNFLRECYDS", "status": "open", "with_nested_markets": "true", "limit": 1})
for m in [m for e in (o or {}).get("events", []) for m in e.get("markets", [])][:1]:
    get(K + f"/markets/{m['ticker']}/orderbook", save="k_orderbook")
json.dump(out, open("probe/out4/_calls.json", "w"), indent=1)
