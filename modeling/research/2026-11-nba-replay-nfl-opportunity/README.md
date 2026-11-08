# NBA historical-report replay and NFL opportunity experiments (Nov 2026)

Analysis only: nothing here is used by the site. Results and conclusions: the Model Room doc
"NBA Playing-Time Fix & NFL Savant Integration".

- Historical official NBA injury reports: harvested on the `injury-probe` branch (harvest.py; hist/, hist2/, hist3/).
- Replays: `python -m modelroom.audit.props_audit nba --params modelroom/nba/props/params_<v>.json --tag <tag> --avail hist`
  with MODELROOM_HIST_REPORTS pointing at those folders (tags v021hist, v022ahist, v022hist; 0.2.0 = v020).
- analyze_hist.py: four-version comparison on identical rows, per season and combined (final_cmp.json).
- timing_check.py: lookahead / pregame-timestamp checks (timing_check.json).
- pplay*.py: play probability by report status and role (fit 2023-24).
- nfl_*.py: walk-forward NFL experiments on NFL props 0.1.1 audit rows (results in the matching .json).

Scripts were run from modeling/ with PYTHONPATH=. ; some read scratch paths and need those paths adjusted to rerun.
