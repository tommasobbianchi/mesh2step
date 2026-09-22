"""Round 0 is reverse.py's design history: accepted with no model call when it passes the gate, otherwise the
model's starting program (Tommaso 2026-09-22: sketch -> extrude -> modify, never final faces)."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import junction_shapes as js  # noqa: E402
from test_reverse import _plate  # noqa: E402

HERE = Path(__file__).resolve().parents[1]

FAKE = r'''#!/usr/bin/env python3
import os, re, sys
open(os.environ["FAKE_PROMPTS"], "a").write(sys.argv[-1] + "\n=====\n")
m = re.findall(r"(\S+recon_\d+\.py)", sys.argv[-1])
open(m[-1], "w").write('result = cq.Workplane("XY").box(10, 10, 10)\n'); print("done")
'''


def _fake(tmp_path):
    fake = tmp_path / "fake"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    prompts = tmp_path / "prompts.txt"; prompts.write_text("")
    return fake, prompts


def test_a_prismatic_part_is_accepted_without_any_model_call(tmp_path):
    stl = js.stl(_plate(), tmp_path / "plate.stl", tol=0.01, ang=0.1)
    fake, prompts = _fake(tmp_path)
    env = dict(os.environ, CLAUDE_BIN=str(fake), FAKE_PROMPTS=str(prompts), RECON_BACKOFF_S="0",
               RECON_MESH_JUNCTIONS="0")
    p = subprocess.run([sys.executable, str(HERE / "recon_part.py"), str(stl), str(tmp_path / "wd"),
                        "--models", "opus", "--rounds", "2"], env=env, capture_output=True, text=True, timeout=1200)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    res = json.loads((tmp_path / "wd" / "recon_result.json").read_text())
    assert res["status"] == "accepted" and res["model"] == "reverse"
    assert prompts.read_text() == ""                          # no model was asked anything


def test_an_imperfect_seed_is_the_models_starting_program(tmp_path):
    stl = tmp_path / "cube.stl"; trimesh.creation.box(extents=[10, 10, 10]).export(stl)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-5] * 3, "bbox_max": [5] * 3, "levels": []}))
    (tmp_path / "r").mkdir()
    seed = tmp_path / "seed.py"; seed.write_text('result = cq.Workplane("XY").box(10, 10, 9.8)\n')  # 0.1 mm off each cap
    fake, prompts = _fake(tmp_path)
    env = dict(os.environ, CLAUDE_BIN=str(fake), FAKE_PROMPTS=str(prompts), RECON_BACKOFF_S="0",
               RECON_MESH_JUNCTIONS="0", RECON_SEED_PROGRAM=str(seed))
    p = subprocess.run([sys.executable, str(HERE / "recon_loop.py"), str(stl), str(facts), str(tmp_path / "r"),
                        str(tmp_path / "wd"), "opus", "1"], env=env, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    hist = json.loads((tmp_path / "wd" / "history.json").read_text())
    assert hist[0]["py"].endswith("recon_0.py") and hist[0].get("seed")
    prompt = prompts.read_text()
    assert "recon_0.py" in prompt and "reversing the design history" in prompt
