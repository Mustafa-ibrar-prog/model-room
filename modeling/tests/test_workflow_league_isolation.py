"""The TEST refresh keeps NBA and NFL independent: one league's data failing never blocks the other, and a failed
league's predictions are never rebuilt. Runs the workflow's real 'Download, validate and project' script with the
modelroom commands stubbed out."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "preview.yml"
STUB = """#!/bin/bash
echo "$*" >> "$SIMLOG"
if [ "$3" = sources ] && [ "$4" = validate ]; then
  if echo ",$FAIL," | grep -q ",$5,"; then echo "     FAIL  every final game has play-by-play  1 missing"; exit 1; fi
  exit 0
fi
[ "$3" = odds-store ] && exit 1
exit 0
"""


def _run(tmp_path, fail):
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["deploy"]["steps"]
    script = next(s for s in steps if s.get("id") == "data")["run"]
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("python", STUB), ("pip", "#!/bin/bash\nexit 0\n")):
        f = bin_ / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "s.sh").write_text(script)
    log, out = tmp_path / "calls.txt", tmp_path / "out.txt"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAIL": fail, "SIMLOG": str(log), "GITHUB_OUTPUT": str(out),
           "KINDS": "pregame", "ODDS_STORE": "off"}
    r = subprocess.run(["bash", "-e", str(tmp_path / "s.sh")], cwd=tmp_path, env=env, capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines()) if out.exists() else {}
    return r.returncode, calls, outputs, r.stdout


def _ran(calls, cmd):
    return any(c == f"-m modelroom {cmd}" or c.startswith(f"-m modelroom {cmd} ") for c in calls)


def test_both_leagues_ok_runs_everything(tmp_path):
    code, calls, out, _ = _run(tmp_path, "")
    assert code == 0 and out["nba_ok"] == "1" and out["nfl_ok"] == "1"
    for cmd in ("nba project", "nba props", "nfl project", "nfl props", "nba props-shadow", "nfl props-monitor"):
        assert _ran(calls, cmd), cmd
    assert "-m modelroom history --league nfl,nba" in calls


def test_nfl_failure_does_not_block_nba(tmp_path):
    code, calls, out, stdout = _run(tmp_path, "nfl")
    assert code == 0 and out["nba_ok"] == "1" and out["nfl_ok"] == "0" and "play-by-play" in out["nfl_why"]
    for cmd in ("nba project", "nba props", "nba props-monitor", "nba props-shadow", "markets settle nba"):
        assert _ran(calls, cmd), cmd
    for cmd in ("nfl project", "nfl props", "nfl props-monitor", "nfl starters", "markets settle nfl"):
        assert not _ran(calls, cmd), cmd          # no NFL prediction is built on incomplete data
    assert "-m modelroom history --league nba" in calls
    assert "::warning::NFL data not ready" in stdout


def test_nba_failure_does_not_block_nfl(tmp_path):
    code, calls, out, _ = _run(tmp_path, "nba")
    assert code == 0 and out["nfl_ok"] == "1" and out["nba_ok"] == "0"
    assert _ran(calls, "nfl project") and _ran(calls, "nfl props") and not _ran(calls, "nba props") and not _ran(calls, "nba project")


def test_both_failing_fails_the_refresh(tmp_path):
    code, calls, _, _ = _run(tmp_path, "nba,nfl")
    assert code != 0
    assert not any(_ran(calls, c) for c in ("nba project", "nfl project", "nba props", "nfl props", "history"))


def test_every_modelroom_command_in_the_step_is_accepted_by_the_real_cli(monkeypatch):
    """The stubs above accept anything; this checks each `python -m modelroom ...` line against the real parser."""
    import re
    import shlex
    from modelroom import cli

    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["deploy"]["steps"]
    script = next(s for s in steps if s.get("id") == "data")["run"]
    seen = []
    script = re.sub(r'"\$\(.*?paste -sd, -\)"', "nfl,nba", script)       # the history league list
    for m in re.finditer(r"python -m modelroom ((?:[^|&;>\n]|\|\|)+?)(?=\s*(?:\|\||&&|[|;>]|$))", script, re.M):
        argv = ["nba" if a.startswith("$") else a for a in shlex.split(m.group(1).replace("$lg", "nba"))]
        seen.append(argv)
        p = _parser(cli)
        try:
            parsed = p.parse_args(argv)
        except SystemExit:
            raise AssertionError(f"workflow command not accepted by the CLI: modelroom {' '.join(argv)}")
        assert parsed.group
    assert any(a[:3] == ["sources", "validate", "nba"] for a in seen)


def _parser(cli):
    """Build the CLI parser without running a command."""
    import argparse
    captured = {}
    orig = argparse.ArgumentParser.parse_args

    def grab(self, args=None, namespace=None):
        captured["p"] = self
        raise SystemExit(0)
    argparse.ArgumentParser.parse_args = grab
    try:
        try:
            cli.main([])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = orig
    return captured["p"]
