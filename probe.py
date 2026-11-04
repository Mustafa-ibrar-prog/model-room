import json, os, urllib.request, datetime as dt
from zoneinfo import ZoneInfo
os.makedirs("out", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (model-room probe)"}
def get(name, url, binary=False):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30)
        b = r.read()
        open(f"out/{name}", "wb").write(b)
        print("OK ", r.status, len(b), name, url)
        return b
    except Exception as e:
        print("ERR", name, url, e)
S = "https://site.api.espn.com/apis/site/v2/sports"
get("nba_injuries.json", f"{S}/basketball/nba/injuries")
get("nfl_injuries.json", f"{S}/football/nfl/injuries")
get("nfl_bal_depth_site.json", f"{S}/football/nfl/teams/33/depthcharts")
get("nfl_bal_depth_core.json", "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2026/teams/33/depthcharts")
get("nfl_bal_roster.json", f"{S}/football/nfl/teams/33/roster")
get("nfl_bal_team_injuries_core.json", "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/33/injuries")
now = dt.datetime.now(ZoneInfo("America/New_York"))
for lg, sp in (("nba", "basketball/nba"), ("nfl", "football/nfl")):
    for d in (now.date() - dt.timedelta(days=1), now.date(), now.date() + dt.timedelta(days=1)):
        b = get(f"{lg}_scoreboard_{d}.json", f"{S}/{sp}/scoreboard?dates={d:%Y%m%d}")
        if not b: continue
        ev = json.loads(b).get("events", [])
        for e in ev[:2]:
            get(f"{lg}_summary_{d}_{e['id']}.json", f"{S}/{sp}/summary?event={e['id']}")
for page in ("nba-injury-report-2026-27", "nba-injury-report-2025-26", "nba-injury-report"):
    get(f"official_{page}.html", f"https://official.nba.com/{page}/")
t = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
found = 0
for i in range(0, 4 * 30):
    x = t - dt.timedelta(minutes=15 * i)
    for fmt in ("%Y-%m-%d_%I_%M%p", "%Y-%m-%d_%I%p"):
        u = f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{x.strftime(fmt)}.pdf"
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20)
            b = r.read(); open(f"out/nba_official_{x.strftime(fmt)}.pdf", "wb").write(b); print("PDF", u, len(b)); found += 1
            break
        except Exception:
            pass
    if found >= 2: break
