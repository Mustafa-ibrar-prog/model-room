"""One-off, read-only probe of the Polymarket US public market-data API (no auth). Round 2."""
import json, time, urllib.request, urllib.parse, os, collections
BASE = "https://gateway.polymarket.us"
out = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "calls": []}
os.makedirs("probe/out2", exist_ok=True)

def get(path, params=None, save=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    rec = {"url": url}
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "model-room-probe/1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode(); rec["status"] = r.status
            rec["headers"] = dict(r.headers.items())
    except urllib.error.HTTPError as e:
        rec["status"] = e.code; body = e.read().decode()[:2000]
    except Exception as e:
        rec["status"] = None; body = repr(e)
    rec["bytes"] = len(body); out["calls"].append(rec)
    if save: open(f"probe/out2/{save}.json", "w").write(body)
    time.sleep(1.0)
    try: return json.loads(body)
    except Exception: return None

games = {"nfl-chi-sea-2026-11-02": 19574, "nfl-jax-bal-2026-11-05": 19576, "nba-okc-cle-2026-11-02": 20024035, "nba-mia-lal-2026-11-02": 20024049}
summary = {}
for slug, gid in games.items():
    for p in [f"/v1/events/slug/{slug}", f"/v1/event/slug/{slug}"]:
        get(p, save=("ev_" + p.split("/")[2] + "_" + slug))
    allm = []
    for off in range(0, 2000, 100):
        d = get("/v1/markets", {"gameId": gid, "limit": 100, "offset": off}, save=f"gm_{slug}_{off}")
        items = (d or {}).get("markets") or []
        allm += items
        if len(items) < 100: break
    summary[slug] = {"n": len(allm), "types": collections.Counter((m.get("sportsMarketType"), m.get("sportsMarketTypeV2"), m.get("marketType")) for m in allm).most_common(),
                     "examples": [{k: m.get(k) for k in ("question", "slug", "sportsMarketType", "line", "bestBid", "bestAsk", "lastTradePrice", "liquidityNum", "volumeNum", "updatedAt")} for m in allm if "player" in str(m.get("sportsMarketType"))][:40]}
for t in ["SPORTS_MARKET_TYPE_PROP", "SPORTS_MARKET_TYPE_PLAYER_PROP", "SPORTS_MARKET_TYPE_TOTAL", "SPORTS_MARKET_TYPE_SPREAD"]:
    d = get("/v1/markets", {"limit": 100, "sportsMarketTypes": t, "closed": "false"}, save=f"type_{t}")
    summary[t] = len((d or {}).get("markets") or [])
get("/v1/sports/players", {"limit": 5, "league": "nfl"}, save="players_nfl")
# BBO and book on first player market found
pm = [e for s in summary.values() if isinstance(s, dict) for e in s["examples"]]
for m in pm[:3]:
    get(f"/v1/markets/{m['slug']}/bbo", save=f"bbo_{m['slug']}"[:100]); get(f"/v1/markets/{m['slug']}/book", save=f"book_{m['slug']}"[:100])
json.dump(summary, open("probe/out2/_summary.json", "w"), indent=1)
json.dump(out, open("probe/out2/_calls.json", "w"), indent=1)
print(json.dumps(summary, indent=1)[:6000])
