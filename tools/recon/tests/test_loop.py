"""Acceptance tests for recon_loop.py robustness. Run: python3 -m pytest -q tests/test_loop.py

Contract (see the spec loop-robust.md):
  - the model CLI is taken from $CLAUDE_BIN (default: the real claude)
  - a usage/rate-limit failure retries the SAME round up to $RECON_QUOTA_RETRIES times with
    $RECON_BACKOFF_S between tries, consumes no round, and if still failing the loop records the
    error and exits 75 (so a driver can resume the part later)
  - any other CLI failure is recorded WITH the CLI's own output (not just 'no file') and the loop
    moves to the next round without retrying
  - exit 0 when at least one valid round exists, 2 when none does, 75 on quota exhaustion
  - importing recon_loop does not run anything; select_best(history, diag) is a pure function
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import trimesh

HERE = Path(__file__).resolve().parents[1]
LOOP = HERE / "recon_loop.py"

FAKE = r'''#!/usr/bin/env python3
import os, re, sys
open(os.environ["FAKE_COUNTER"], "a").write("x\n")
mode = os.environ["FAKE_MODE"]
prompt = sys.argv[-1]
if mode == "ok":
    m = re.search(r"(\S+recon_\d+\.py)", prompt.split("Write the")[-1]) or re.search(r"(\S+recon_\d+\.py)", prompt)
    open(m.group(1), "w").write('result = cq.Workplane("XY").box(10, 10, 10)\n')
    print("done")
elif mode == "quota":
    print("Claude AI usage limit reached|1790000000")
    sys.exit(1)
else:
    print("boom: something else went wrong", file=sys.stderr)
    sys.exit(1)
'''


@pytest.fixture
def case(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(stl)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-5, -5, -5], "bbox_max": [5, 5, 5], "levels": []}))
    renders = tmp_path / "renders"; renders.mkdir()
    fake = tmp_path / "fake_claude"; fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    counter = tmp_path / "count"; counter.write_text("")
    return tmp_path, stl, facts, renders, fake, counter


def run(case, mode, iters):
    tmp, stl, facts, renders, fake, counter = case
    env = dict(os.environ, CLAUDE_BIN=str(fake), FAKE_MODE=mode, FAKE_COUNTER=str(counter),
               RECON_BACKOFF_S="0", RECON_QUOTA_RETRIES="2")
    wd = tmp / "wd"
    p = subprocess.run([sys.executable, str(LOOP), str(stl), str(facts), str(renders), str(wd), "fake", str(iters)],
                       env=env, capture_output=True, text=True, timeout=900)
    hist = json.loads((wd / "history.json").read_text()) if (wd / "history.json").exists() else None
    return p, hist, len(counter.read_text().splitlines()), wd


def test_program_written_converges(case):
    p, hist, calls, wd = run(case, "ok", 2)
    assert p.returncode == 0, p.stderr[-2000:]
    assert hist and hist[0]["report"] and hist[0]["report"]["valid"]
    assert (wd / "best.json").exists()


def test_quota_retries_same_round_then_exits_75(case):
    p, hist, calls, wd = run(case, "quota", 3)
    assert p.returncode == 75, (p.returncode, p.stdout[-800:], p.stderr[-800:])
    assert calls == 3                       # first try + 2 retries, all on round 1
    assert hist is not None and len(hist) == 1
    assert "usage limit" in hist[0]["error"].lower()


def test_other_failure_records_cli_output_and_moves_on(case):
    p, hist, calls, wd = run(case, "error", 2)
    assert p.returncode == 2, (p.returncode, p.stderr[-800:])
    assert calls == 2                       # no retry storm on non-quota failures
    assert hist is not None and len(hist) == 2
    assert all("boom" in h["error"] for h in hist)


def _h(valid, p95a, p95b, curved, patches=50):
    return {"py": f"r{curved}.py", "report": {"valid": valid, "p95_mesh_to_solid": p95a, "p95_solid_to_mesh": p95b,
                                              "features": {"curved": curved, "patches": patches}}}


def test_select_best_is_importable_and_fidelity_gated():
    sys.path.insert(0, str(HERE))
    import recon_loop                      # must not run the loop
    sb = recon_loop.select_best
    diag = 200.0                          # fidelity bound = 0.5 % of diag = 1.0 mm
    a, b = _h(True, 0.2, 0.3, 40), _h(True, 0.05, 0.06, 45)
    far = _h(True, 8.2, 8.0, 50)          # most features but 8 mm off: must never win (part 17)
    assert sb([a, b, far], diag) is b
    t1, t2 = _h(True, 0.4, 0.4, 45), _h(True, 0.1, 0.1, 45)
    assert sb([t1, t2], diag) is t2        # tie on features -> better fidelity
    x, y = _h(True, 3.0, 3.0, 10), _h(True, 2.0, 2.5, 5)
    assert sb([x, y], diag) is y          # none within bound -> lowest distance among valid
    assert sb([_h(False, 0.01, 0.01, 50)], diag) is None
