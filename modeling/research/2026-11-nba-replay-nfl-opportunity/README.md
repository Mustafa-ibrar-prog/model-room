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

## Stage 1 / Stage 4 (approved experiments, Nov 7)
- NBA 0.2.3a / 0.2.3 (params in modelroom/nba/props): usage_fit.py (freed-usage grid on 2023-24, needs MODELROOM_AUDIT_USAGE_PARTS=1 rows),
  fitcmp.py (2023-24 fit comparison, fitcmp_2024.json), validation final_cmp2.json (analyze_hist.py with v020 v022ahist v022hist v023ahist v023hist).
- NFL 0.1.2 (rejected): nfl_012_cmp.py (as-is), nfl_recal.py (calibration refit on 2021-22 for both versions).
