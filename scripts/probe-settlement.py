"""One-off probe: what do settled markets look like on each provider? Prints FIELD NAMES and STATUS
values only (no prices, no outcomes), so nothing restricted is published in the CI log."""
import json
import sys
import urllib.request
from datetime import date, timedelta


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "model-room-probe/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


SAFE = ("status", "ep3Status", "active", "closed", "archived", "marketType", "sportsMarketType", "sportsMarketTypeV2", "strike_type",
        "market_type", "can_close_early", "settlement_timer_seconds")

print("== Kalshi")
K = "https://api.elections.kalshi.com/trade-api/v2"
for series in ["KXNFLRECYDS", "KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL", "KXNBAPTS"]:
    for status in ["settled", "closed"]:
        try:
            d = get(f"{K}/events?series_ticker={series}&status={status}&with_nested_markets=true&limit=2")
        except Exception as e:  # noqa: BLE001
            print(series, status, "error", type(e).__name__, str(e)[:80]); continue
        evs = d.get("events") or []
        if not evs:
            print(series, status, "no events"); continue
        m = (evs[0].get("markets") or [{}])[0]
        print(series, status, "events:", len(evs), "market keys:", sorted(m.keys()))
        print("   ", {k: m.get(k) for k in SAFE if k in m}, "| result present:", bool(m.get("result")),
              "| settlement_ts present:", bool(m.get("settlement_ts")), "| settlement_value fields:", [k for k in m if "settlement" in k or "expiration_value" in k])
        break

print("== Polymarket US")
P = "https://gateway.polymarket.us"
seen = 0
for back in range(1, 8):
    d0 = (date.today() - timedelta(days=back)).isoformat()
    for slug in [f"nfl-buf-bal-{d0}", f"nfl-bal-buf-{d0}", f"nba-okc-cle-{d0}"]:
        pass
# find a settled event via the events listing
for path in ["/v1/events?closed=true&limit=3", "/v1/events?status=closed&limit=3", "/v1/markets?closed=true&limit=3"]:
    try:
        d = get(P + path)
    except Exception as e:  # noqa: BLE001
        print(path, "error", type(e).__name__, str(e)[:100]); continue
    items = d.get("events") or d.get("markets") or (d if isinstance(d, list) else [])
    print(path, "top keys:", sorted(d.keys()) if isinstance(d, dict) else type(d).__name__, "items:", len(items))
    for it in items[:2]:
        ms = it.get("markets") or [it]
        for m in ms[:2]:
            print("   keys:", sorted(m.keys()))
            print("   ", {k: m.get(k) for k in SAFE if k in m}, "| resolution-like keys:", [k for k in m if any(s in k.lower() for s in ("resol", "settle", "winner", "outcome"))])
            seen += 1
sys.exit(0)
