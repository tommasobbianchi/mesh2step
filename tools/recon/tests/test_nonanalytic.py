"""A face that is not exact analytic geometry is reported, fed back, and blocks convergence and acceptance."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import trimesh

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

FAKE = r'''#!/usr/bin/env python3
import os, re, sys
n = len(open(os.environ["FAKE_COUNTER"]).read()); open(os.environ["FAKE_COUNTER"], "a").write("x")
m = re.findall(r"(\S+recon_\d+\.py)", sys.argv[-1])
body = os.environ["FAKE_BODY_%d" % min(n, 1)]
open(m[-1], "w").write(body); print("done")
'''
LOFT = 'result = cq.Workplane("XY").workplane(offset=-5).rect(10, 10).workplane(offset=10).rect(10.4, 10.4).loft()\n'
BOX = 'result = cq.Workplane("XY").box(10, 10, 10)\n'


def _run(tmp_path, first, second, rounds):
    stl = tmp_path / "cube.stl"; trimesh.creation.box(extents=[10, 10, 10]).export(stl)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-5] * 3, "bbox_max": [5] * 3, "levels": []}))
    (tmp_path / "r").mkdir(exist_ok=True)
    fake = tmp_path / "fake"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    counter = tmp_path / "count"; counter.write_text("")
    env = dict(os.environ, CLAUDE_BIN=str(fake), FAKE_COUNTER=str(counter), FAKE_BODY_0=first, FAKE_BODY_1=second,
               RECON_BACKOFF_S="0", RECON_MESH_JUNCTIONS="0", RECON_STOP_REL="0.05")
    p = subprocess.run([sys.executable, str(HERE / "recon_loop.py"), str(stl), str(facts), str(tmp_path / "r"),
                        str(tmp_path / "wd"), "opus", str(rounds)], env=env, capture_output=True, text=True, timeout=600)
    return p, json.loads((tmp_path / "wd" / "history.json").read_text()), len(counter.read_text())


def test_a_lofted_face_is_reported_and_does_not_converge(tmp_path):
    p, hist, calls = _run(tmp_path, LOFT, BOX, 2)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    r1 = hist[0]["report"]
    assert r1["nonanalytic"] >= 1 and {"type", "area", "centre"} <= set(r1["nonanalytic_faces"][0])
    assert calls == 2                                    # round 1 was close enough but not exact: no stop
    assert hist[1]["report"]["nonanalytic"] == 0


def test_select_best_prefers_the_exact_round_on_a_tie():
    import recon_loop
    base = {"valid": True, "p95_mesh_to_solid": 0.01, "p95_solid_to_mesh": 0.01, "features": {"curved": 3}}
    a = {"py": "a", "report": dict(base, nonanalytic=2)}
    b = {"py": "b", "report": dict(base, nonanalytic=0)}
    assert recon_loop.select_best([a, b], 100.0)["py"] == "b"
