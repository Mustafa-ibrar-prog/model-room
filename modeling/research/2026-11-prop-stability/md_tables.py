"""Markdown season tables from stability JSON (research)."""
import json
import sys


def f(x, d=2, sign=False):
    if x is None:
        return "–"
    return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}")


def tables(path, labels, seasons=None):
    d = json.load(open(path))
    S = seasons or sorted(d["seasons"])
    mk = [m for m in labels if any(m in d["seasons"][s] for s in S)]
    out = []
    hdr = "| Category | " + " | ".join(S) + " |\n| --- | " + " | ".join("---" for _ in S) + " |"
    def row(m, fn):
        cells = []
        for s in S:
            v = d["seasons"].get(s, {}).get(m)
            cells.append(fn(v) if v else "–")
        return f"| {labels[m]} | " + " | ".join(cells) + " |"
    out.append(("Player-games / MAE / bias (projected − actual)", hdr + "\n" + "\n".join(row(m, lambda v: f"{v['player_games']:,} / {f(v['mae'])} / {f(v['bias'], 2, True)}") for m in mk)))
    out.append(("Log loss (recent-form baseline) / Brier", hdr + "\n" + "\n".join(row(m, lambda v: f"{f(v.get('log_loss'),3)} ({f(v.get('baseline_log_loss'),3)}) / {f(v.get('brier'),3)}") for m in mk)))
    out.append(("Calibration error / predicted vs actual rate over the ladder", hdr + "\n" + "\n".join(row(m, lambda v: f"{f(100*v['ece'],1)}% / {f(100*v['pred_rate'],1)} vs {f(100*v['actual_rate'],1)}") for m in mk)))
    def ou(v):
        o, u = v["ou"]["over_leans"], v["ou"]["under_leans"]
        g = lambda s: "–" if s["hit"] is None else f"{100*s['hit']:.0f} vs {100*s['expected']:.0f}"
        return f"O {g(o)} · U {g(u)}"
    out.append(("Over / Under leans: % happened vs % expected", hdr + "\n" + "\n".join(row(m, ou) for m in mk)))
    return out


if __name__ == "__main__":
    lab = json.loads(sys.argv[2])
    for t, md in tables(sys.argv[1], lab, sys.argv[3].split(",") if len(sys.argv) > 3 else None):
        print("**" + t + "**\n\n" + md + "\n")
