"""A hung or killed model call must not lose the rounds already measured (hotend, 2026-09-21).

- $RECON_CALL_TIMEOUT_S bounds each model call; a timeout is recorded as that round's error and
  the loop moves on instead of crashing.
- best.json/best.step are rewritten after every measured round, so a loop killed from outside
  (recon_part's budget) still leaves the best round so far.
"""
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import trimesh

LOOP = Path(__file__).resolve().parents[1] / "recon_loop.py"

FAKE = r'''#!/usr/bin/env python3
import os, re, sys, time
n = len(open(os.environ["FAKE_COUNTER"]).read()); open(os.environ["FAKE_COUNTER"], "a").write("x")
if n >= 1:
    time.sleep(3600)                                   # every call after the first hangs
m = re.findall(r"(\S+recon_\d+\.py)", sys.argv[-1])
open(m[-1], "w").write('result = cq.Workplane("XY").box(10, 10, 9.5)\n'); print("done")
'''


def _setup(tmp_path):
    stl = tmp_path / "cube.stl"; trimesh.creation.box(extents=[10, 10, 10]).export(stl)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-5, -5, -5], "bbox_max": [5, 5, 5], "levels": []}))
    renders = tmp_path / "r"; renders.mkdir()
    fake = tmp_path / "fake"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    counter = tmp_path / "count"; counter.write_text("")
    env = dict(os.environ, CLAUDE_BIN=str(fake), FAKE_COUNTER=str(counter), RECON_BACKOFF_S="0")
    return [sys.executable, str(LOOP), str(stl), str(facts), str(renders), str(tmp_path / "wd"), "opus"], env


def test_a_hung_call_times_out_and_the_loop_keeps_its_best(tmp_path):
    cmd, env = _setup(tmp_path)
    env["RECON_CALL_TIMEOUT_S"] = "3"
    p = subprocess.run(cmd + ["2"], env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    best = json.loads((tmp_path / "wd" / "best.json").read_text())
    assert best["best"].endswith("recon_1.py") and best["report"]["valid"]
    hist = json.loads((tmp_path / "wd" / "history.json").read_text())
    assert "timed out" in hist[1]["error"]


def test_a_killed_loop_leaves_the_best_round_so_far(tmp_path):
    cmd, env = _setup(tmp_path)
    p = subprocess.Popen(cmd + ["3"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    counter = tmp_path / "count"
    t0 = time.time()
    while len(counter.read_text()) < 2 and time.time() - t0 < 240:   # round 2's call has started
        time.sleep(0.2)
    os.killpg(p.pid, signal.SIGKILL); p.wait()
    wd = tmp_path / "wd"
    assert (wd / "best.step").exists()
    assert json.loads((wd / "best.json").read_text())["best"].endswith("recon_1.py")


EMPTY_THEN_BOX = r'''#!/usr/bin/env python3
import os, re, sys
n = len(open(os.environ["FAKE_COUNTER"]).read()); open(os.environ["FAKE_COUNTER"], "a").write("x")
body = 'result = cq.Workplane("XY")\n' if n == 0 else 'result = cq.Workplane("XY").box(10, 10, 9.5)\n'
m = re.findall(r"(\S+recon_\d+\.py)", sys.argv[-1]); open(m[-1], "w").write(body); print("done")
'''


def test_an_empty_solid_is_round_feedback_not_a_crash(tmp_path):
    cmd, env = _setup(tmp_path)
    (tmp_path / "fake").write_text(EMPTY_THEN_BOX)      # muse, part 6: a STEP with 0 faces crashed the gate
    p = subprocess.run(cmd + ["2"], env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    hist = json.loads((tmp_path / "wd" / "history.json").read_text())
    assert hist[0]["report"] is None and hist[0]["error"]
    assert hist[1]["report"]["valid"]
