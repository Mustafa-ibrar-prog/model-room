import urllib.request, re, os, io, csv
UA = {"User-Agent": "Mozilla/5.0 (compatible; ModelRoom research)"}
os.makedirs("savant", exist_ok=True)
def get(u, limit=None):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60)
        b = r.read(limit) if limit else r.read()
        return r.status, b
    except Exception as e:
        return str(e), b""
for name, u in [("home", "http://nflsavant.com/"), ("about", "http://nflsavant.com/about.php"), ("terms", "http://nflsavant.com/terms.php"),
                ("privacy", "http://nflsavant.com/privacy.php"), ("robots", "http://nflsavant.com/robots.txt")]:
    st, b = get(u)
    print(name, st, len(b))
    open(f"savant/{name}.html", "wb").write(b)
html = open("savant/about.html", "rb").read().decode("utf-8", "ignore") + open("savant/home.html", "rb").read().decode("utf-8", "ignore")
links = sorted(set(re.findall(r'href="([^"]+)"', html)))
open("savant/links.txt", "w").write("\n".join(links))
csvs = [l for l in links if l.lower().endswith(".csv") or "csv" in l.lower()]
print("csv links", csvs[:40])
for l in csvs[:3]:
    u = l if l.startswith("http") else "http://nflsavant.com/" + l.lstrip("/")
    st, b = get(u, 200000)
    open("savant/sample_" + re.sub(r"\W", "_", l)[-60:] + ".txt", "wb").write(b[:20000])
    print(u, st, b[:300])
