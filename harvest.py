"""Historical official NBA injury reports for replay: for each game, the hourly report at or before tip-30 (ET).
Fetch (threads) -> parse (processes) -> parquet. Falls back up to 2 hours earlier when a slot is missing."""
import sys, os, io, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import timedelta
import pandas as pd
sys.path.insert(0, "inj")
import nba_official as N

T = pd.read_csv(os.environ.get("TARGETS", "targets.csv"), parse_dates=["rt"])
T["rt"] = pd.to_datetime(T["rt"], utc=True).dt.tz_convert("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (compatible; ModelRoom/0.1; research replay)"}

def get(rt):
    # rt is the hour floor of tip-30; the 15-minute format (2025-26 on) can be up to 45 minutes later and still be
    # before tip-30, but we only know tip-30 to the hour here, so the latest slot used is rt itself (conservative).
    for k in range(9):
        t = rt - timedelta(minutes=15 * k)
        fmts = ["%Y-%m-%d_%I_%M%p"] + (["%Y-%m-%d_%I%p"] if t.minute == 0 else [])
        for f in fmts:
            u = N.URL.format(t.strftime(f))
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
                return rt, t, u, b
            except Exception:
                continue
    return rt, None, None, None

def parse(args):
    rt, t, u, b = args
    try:
        rows, fil = N.parse(b, t.to_pydatetime())
        rows["target_slot"] = rt.isoformat(); rows["url"] = u
        f = pd.DataFrame(fil); f["target_slot"] = rt.isoformat(); f["report_time"] = t.isoformat()
        return rows, f, None
    except Exception as e:
        return None, None, f"{u}: {e}"

if __name__ == "__main__":
    with ThreadPoolExecutor(24) as ex:
        got = list(ex.map(get, list(T["rt"])))
    miss = [str(g[0]) for g in got if g[3] is None]
    ok = [g for g in got if g[3] is not None]
    print("fetched", len(ok), "missing", len(miss), flush=True)
    with ProcessPoolExecutor(os.cpu_count()) as ex:
        res = list(ex.map(parse, ok, chunksize=8))
    errs = [r[2] for r in res if r[2]]
    R = pd.concat([r[0] for r in res if r[0] is not None], ignore_index=True)
    F = pd.concat([r[1] for r in res if r[1] is not None], ignore_index=True)
    os.makedirs(os.environ.get("OUT", "hist"), exist_ok=True)
    R.astype({"report_time": str, "fetched_at": str}).to_parquet(os.environ.get("OUT", "hist") + "/nba_reports.parquet", index=False)
    F.to_parquet(os.environ.get("OUT", "hist") + "/nba_filings.parquet", index=False)
    json.dump({"missing": miss, "parse_errors": errs[:200], "n_parse_errors": len(errs), "rows": len(R)}, open(os.environ.get("OUT", "hist") + "/summary.json", "w"), indent=1)
    print("rows", len(R), "parse errors", len(errs))
