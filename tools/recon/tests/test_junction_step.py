"""Junctions for the brief can come from the pipeline's own STEP of the mesh, read exactly.

The mesh extractor scored 16.8% blend recall on the corpus; the served STEP read with junctions.extract
matched ~80% of the accepted CAD's blends (2026-09-22). RECON_JUNCTION_STEP selects it.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import junction_shapes as js  # noqa: E402

LOOP = Path(__file__).resolve().parents[1] / "recon_loop.py"

FAKE = r'''#!/usr/bin/env python3
import os, re, sys
open(os.environ["FAKE_PROMPTS"], "a").write(sys.argv[-1])
m = re.findall(r"(\S+recon_\d+\.py)", sys.argv[-1])
open(m[-1], "w").write('result = cq.Workplane("XY").box(30, 30, 4)\n'); print("done")
'''


def test_brief_reads_junctions_from_the_given_step(tmp_path):
    w = js.boss_with_base_fillet()
    stl, step = js.stl(w, tmp_path / "boss.stl"), js.step(w, tmp_path / "pipeline.step")
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-15, -15, -2], "bbox_max": [15, 15, 10], "levels": []}))
    (tmp_path / "vis").mkdir()
    fake = tmp_path / "fake"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    prompts = tmp_path / "prompts.txt"
    env = dict(os.environ, CLAUDE_BIN=str(fake), FAKE_PROMPTS=str(prompts), RECON_BACKOFF_S="0",
               RECON_MESH_JUNCTIONS="0", RECON_JUNCTION_STEP=str(step))
    p = subprocess.run([sys.executable, str(LOOP), str(stl), str(facts), str(tmp_path / "vis"), str(tmp_path / "wd"),
                        "opus", "1"], env=env, capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    prompt = prompts.read_text()
    assert "blend:torus|cylinder+plane|fillet" in prompt and "1.5" in prompt
