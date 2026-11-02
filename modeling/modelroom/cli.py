"""Command line: python -m modelroom <group> <command>.

  sources inventory [--docs]      build the data-source inventory
  sources validate [nba|nfl|all]  profile and check every processed dataset
  nba ingest                      download hoopR schedules, team and player box scores
  nba crosscheck [--season N]     Land of Basketball score cross-check (20 s between pages)
  nba odds                        optional: current lines from The Odds API (ODDS_API_KEY)
  nba lines                       load data/manual/nba_lines.csv
  nba backtest                    provisional walk-forward validation
  nfl ingest [--from DIR]         nflverse games, play-by-play and injuries
  nfl odds | nfl lines            same as NBA
  ledger verify                   check the prediction ledgers' hash chains
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _sources(args) -> int:
    from modelroom.sources import inventory, validate

    if args.cmd == "inventory":
        path = inventory.write(docs=args.docs)
        print(f"Wrote {path}")
        return 0
    report = validate.run(args.league)
    for d in report["datasets"]:
        flag = "OK  " if d["ok"] else "FAIL"
        print(f"{flag} {d['dataset']}: {d['rows']:,} rows")
        for c in d["checks"]:
            if not c["ok"] or args.verbose:
                print(f"     {'pass' if c['ok'] else 'FAIL'}  {c['name']}  {c['detail']}")
    print("All datasets passed." if report["ok"] else "Some checks failed (see above).")
    return 0 if report["ok"] else 1


def _lines(league: str, cmd: str) -> int:
    from modelroom.sources import odds

    if league == "nba":
        from modelroom.nba.ingest import load

        games, _ = load()
    else:
        from modelroom.nfl.ingest import load_games

        games = load_games()
    if cmd == "odds":
        new = odds.collect_odds_api(league)
    else:
        new, problems = odds.load_manual(league)
        for p in problems:
            print(f"rejected {p}")
        if not len(new) and not problems:
            print(f"No manual file at {odds.manual_path(league)}. Copy modeling/templates/lines_template.csv there.")
    matched = odds.match_games(new, games, league)
    allrows = odds.store(league, matched)
    unmatched = int(matched["game_id"].isna().sum()) if len(matched) else 0
    print(f"{len(matched)} lines stored ({unmatched} not matched to a game); {len(allrows)} snapshots on file.")
    return 0


def _nba(args) -> int:
    from modelroom.nba import ingest

    if args.cmd == "ingest":
        from modelroom.nba import injuries
        from modelroom.sources import state

        summary = ingest.run()
        seasons = list(range(ingest.FIRST_SEASON, ingest.current_season() + 1))
        state.record("hoopr_schedule", seasons=summary["seasons"], latest_final=summary["latest_final"])
        state.record("hoopr_team_box", seasons=summary["seasons"])
        injuries.download(seasons)
        injuries.build(seasons)
        state.record("hoopr_player_box", seasons=summary["seasons"])
        _print(summary)
        return 0
    if args.cmd == "crosscheck":
        from modelroom.sources import land_of_basketball, reconcile

        if not args.no_fetch:
            land_of_basketball.collect(args.season or ingest.current_season())
        r = reconcile.nba_scores()
        print(f"Compared {r['compared']} games: {len(r.get('score_mismatches', []))} score mismatches, "
              f"{r.get('overtime_mismatches', 0)} overtime mismatches.")
        return 0 if r.get("ok") else 1
    if args.cmd in ("odds", "lines"):
        return _lines("nba", args.cmd)
    if args.cmd == "project":
        from modelroom.nba import pipeline

        _print(pipeline.run(days=args.days))
        return 0
    if args.cmd == "backtest":
        from modelroom.nba import backtest, injuries

        games, team_games = ingest.load()
        report = backtest.run(games, team_games, player_box=injuries.load())
        _print({"test": {k: v for k, v in report["test"]["without_injuries"].items() if k in ("games", "margin", "total", "win_probability")}})
        return 0
    return 2


def _nfl(args) -> int:
    from modelroom.nfl import ingest

    if args.cmd == "ingest":
        _print(ingest.run(local_dir=Path(args.from_dir) if args.from_dir else None))
        return 0
    if args.cmd in ("odds", "lines"):
        return _lines("nfl", args.cmd)
    return 2


def _ledger(args) -> int:
    from modelroom.common import ledger
    from modelroom.common.paths import ledger_path

    for league in ("nba", "nfl"):
        n = ledger.verify(ledger_path(league))
        print(f"{league}: {n} predictions, chain intact")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="modelroom", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="group", required=True)

    s = sub.add_parser("sources")
    s.add_argument("cmd", choices=["inventory", "validate"])
    s.add_argument("league", nargs="?", default="all", choices=["nba", "nfl", "all"])
    s.add_argument("--docs", action="store_true", help="also write docs/data-inventory.md")
    s.add_argument("--verbose", action="store_true")

    b = sub.add_parser("nba")
    b.add_argument("cmd", choices=["ingest", "crosscheck", "odds", "lines", "backtest", "project"])
    b.add_argument("--days", type=int, default=7, help="project: how many days ahead")
    b.add_argument("--season", type=int)
    b.add_argument("--no-fetch", action="store_true", help="crosscheck: use saved snapshots only")

    f = sub.add_parser("nfl")
    f.add_argument("cmd", choices=["ingest", "odds", "lines"])
    f.add_argument("--from", dest="from_dir", help="folder with play_by_play_<season>.parquet / injuries_<season>.parquet")

    sub.add_parser("ledger").add_argument("cmd", choices=["verify"])

    args = p.parse_args(argv)
    handler = {"sources": _sources, "nba": _nba, "nfl": _nfl, "ledger": _ledger}[args.group]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
