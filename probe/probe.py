"""One-off, read-only probe of the Polymarket US public market-data API (no auth)."""
import json, time, urllib.request, urllib.parse, os
BASE = "https://gateway.polymarket.us"
out = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "calls": []}
os.makedirs("probe/out", exist_ok=True)

def get(path, params=None, save=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    rec = {"url": url}
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "model-room-probe/1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            rec["status"] = r.status
            rec["headers"] = {k: v for k, v in r.headers.items() if "rate" in k.lower() or "limit" in k.lower()}
    except urllib.error.HTTPError as e:
        rec["status"] = e.code; body = e.read().decode()[:2000]
    except Exception as e:
        rec["status"] = None; body = repr(e)
    rec["bytes"] = len(body)
    out["calls"].append(rec)
    if save:
        open(f"probe/out/{save}.json", "w").write(body)
    time.sleep(1.0)  # be polite: 1 request per second
    try: return json.loads(body)
    except Exception: return None

for p in ["/v1/sports", "/v1/leagues", "/v1/sports/leagues", "/v1/series", "/v1/sports/teams", "/v1/sports/players"]:
    get(p, {"limit": 100}, save=p.strip("/").replace("/", "_"))

# All active sports prop markets, paged
props = []
for off in range(0, 5000, 100):
    d = get("/v1/markets", {"limit": 100, "offset": off, "categories": "sports", "sportsMarketTypes": "SPORTS_MARKET_TYPE_PROP", "active": "true", "closed": "false"}, save=f"props_{off}")
    items = (d or {}).get("markets") if isinstance(d, dict) else d
    if not items: break
    props += items
    if len(items) < 100: break
json.dump(props, open("probe/out/props_all.json", "w"))

# Sample of all active sports markets (any type) for structure
get("/v1/markets", {"limit": 100, "categories": "sports", "active": "true", "closed": "false"}, save="sports_sample")
# Search
for q in ["passing yards", "rushing yards", "receiving yards", "points rebounds", "touchdown"]:
    get("/v1/search", {"query": q, "limit": 50}, save="search_" + q.replace(" ", "_"))
    get("/v1/search", {"q": q, "limit": 50}, save="searchq_" + q.replace(" ", "_"))
# BBO + book for first few props
for m in props[:5]:
    s = m.get("slug")
    if s:
        get(f"/v1/markets/{s}/bbo", save=f"bbo_{s}"[:120])
        get(f"/v1/markets/{s}/book", save=f"book_{s}"[:120])
get("/v1/events", {"limit": 50, "active": "true", "closed": "false", "categories": "sports"}, save="events_sample")
json.dump(out, open("probe/out/_calls.json", "w"), indent=1)
print(json.dumps(out["calls"], indent=1)[:4000]); print("props:", len(props))
