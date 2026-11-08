import os, urllib.request
os.makedirs("out2", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (model-room probe)"}
def head(u):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20); b = r.read()
        print("OK ", len(b), u); return b
    except Exception as e:
        print("ERR", u, str(e)[:80])
B = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_"
for d in ("2021-11-10", "2022-01-15", "2022-11-01", "2023-01-15", "2023-11-08", "2024-02-01", "2024-12-10", "2025-03-05", "2025-11-20"):
    for t in ("05_30PM", "06_00PM", "05PM", "06PM", "01_30PM", "07_00PM"):
        b = head(f"{B}{d}_{t}.pdf")
        if b:
            open(f"out2/{d}_{t}.pdf", "wb").write(b); break
for page in ("nba-injury-report-2021-22", "nba-injury-report-2022-23", "nba-injury-report-2023-24", "nba-injury-report-2024-25"):
    b = head(f"https://official.nba.com/{page}/")
    if b: open(f"out2/{page}.html", "wb").write(b)
