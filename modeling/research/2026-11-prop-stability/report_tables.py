"""Print compact season tables from stability JSON (research)."""
import json
import sys

d = json.load(open(sys.argv[1]))
markets = sys.argv[2].split(",") if len(sys.argv) > 2 else None
for m in (markets or list(next(iter(d["seasons"].values())).keys())):
    print(f"== {m}")
    for s, x in sorted(d["seasons"].items()):
        v = x.get(m)
        if not v:
            continue
        ou = v.get("ou") or {}
        o, u = ou.get("over_leans") or {}, ou.get("under_leans") or {}
        print(f"  {s} pg={v['player_games']:>6} mae={v['mae']} (recent {v['recent_avg_mae']}) bias={v['bias']:+} ll={v.get('log_loss')} base={v.get('baseline_log_loss')} "
              f"ece={v.get('ece')} pred/act={v.get('pred_rate')}/{v.get('actual_rate')} OU over {o.get('hit')}/{o.get('expected')} n{o.get('n')} under {u.get('hit')}/{u.get('expected')} n{u.get('n')}")
