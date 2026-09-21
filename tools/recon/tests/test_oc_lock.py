"""The opencode backend shares the machine-wide opencode lane lock (spec oc-lock.md).

Concurrent opencode runs on one box cross-attribute output through the shared session store, so
every opencode caller takes an exclusive flock on ~/.local/state/oc-orchestrate/.run.lock (path
overridable with $RECON_OC_LOCK). The loop must WAIT for it, never run beside another holder.
"""
import fcntl
import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import trimesh

HERE = Path(__file__).resolve().parents[1]
LOOP = HERE / "recon_loop.py"

FAKE = r'''#!/usr/bin/env python3
import os, re, sys, time
open(os.environ["FAKE_T"], "w").write(str(time.time()))
m = re.findall(r"(\S+recon_\d+\.py)", sys.argv[-1])
open(m[-1], "w").write('result = cq.Workplane("XY").box(10, 10, 10)\n'); print("done")
'''


def test_opencode_call_waits_for_the_lane_lock(tmp_path):
    stl = tmp_path / "cube.stl"; trimesh.creation.box(extents=[10, 10, 10]).export(stl)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-5, -5, -5], "bbox_max": [5, 5, 5], "levels": []}))
    renders = tmp_path / "r"; renders.mkdir()
    fake = tmp_path / "oc"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    lock = tmp_path / ".run.lock"; t_file = tmp_path / "t"
    held = open(lock, "w"); fcntl.flock(held, fcntl.LOCK_EX)
    released = {}

    def release():
        time.sleep(3.0); released["t"] = time.time(); fcntl.flock(held, fcntl.LOCK_UN); held.close()

    threading.Thread(target=release, daemon=True).start()
    env = dict(os.environ, OPENCODE_BIN=str(fake), FAKE_T=str(t_file), RECON_OC_LOCK=str(lock),
               RECON_BACKOFF_S="0")
    p = subprocess.run([sys.executable, str(LOOP), str(stl), str(facts), str(renders), str(tmp_path / "wd"),
                        "opencode:opencode/nemotron-3-ultra-free", "1"], env=env, capture_output=True, text=True,
                       timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    assert float(t_file.read_text()) >= released["t"] - 0.05     # called only after the lock was free
