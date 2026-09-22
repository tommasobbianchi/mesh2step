"""junction_tree: signature -> tool; the brief lists the mesh's junctions with their tool, and the gate
names the tool for every missed feature (spec specs/junction-tree.md)."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import junction_shapes as js  # noqa: E402

LOOP = Path(__file__).resolve().parents[1] / "recon_loop.py"


def test_every_tree_tool_exists():
    import junction_tree
    import recon_tools as rt
    assert junction_tree.TREE
    for sig, e in junction_tree.TREE.items():
        assert e["tool"].startswith("rt.") and callable(getattr(rt, e["tool"][3:])), sig
        assert e["how"]


def test_every_blend_in_the_test_shapes_has_a_tool(tmp_path):
    import junction_tree
    import junctions
    for name in ("rounded_box", "boss_with_base_fillet", "boss_with_top_round"):
        for b in junctions.extract(js.step(getattr(js, name)(), tmp_path / f"{name}.step"))["blends"]:
            assert b["sig"] in junction_tree.TREE, b["sig"]


def test_advise_names_tool_and_radius(tmp_path):
    import junction_tree
    import junctions
    lines = junction_tree.advise(junctions.extract(js.step(js.boss_with_base_fillet(), tmp_path / "b.step")))
    assert any(("rt.boss" in l or "rt.ring_fillet" in l) and "1.5" in l for l in lines), lines


FAKE = r'''#!/usr/bin/env python3
import os, re, sys
open(os.environ["FAKE_PROMPTS"], "a").write(sys.argv[-1] + "\n=====\n")
m = re.findall(r"(\S+recon_\d+\.py)", sys.argv[-1])
open(m[-1], "w").write(os.environ["FAKE_PROGRAM"]); print("done")
'''


def _loop(tmp_path, program):
    stl = js.stl(js.boss_with_base_fillet(), tmp_path / "boss.stl")
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-15, -15, -2], "bbox_max": [15, 15, 10], "levels": []}))
    (tmp_path / "vis").mkdir()
    fake = tmp_path / "fake"; fake.write_text(FAKE); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    prompts = tmp_path / "prompts.txt"
    env = dict(os.environ, CLAUDE_BIN=str(fake), FAKE_PROMPTS=str(prompts), FAKE_PROGRAM=program, RECON_BACKOFF_S="0")
    p = subprocess.run([sys.executable, str(LOOP), str(stl), str(facts), str(tmp_path / "vis"), str(tmp_path / "wd"),
                        "opus", "1"], env=env, capture_output=True, text=True, timeout=900)
    return p, prompts.read_text(), tmp_path / "wd"


def test_brief_lists_junctions_and_programs_can_use_rt(tmp_path):
    prog = ('result = rt.boss(cq.Workplane("XY").box(30, 30, 4), cq.Plane(origin=(0, 0, 2), xDir=(1, 0, 0), '
            'normal=(0, 0, 1)), (0, 0), 5.0, 8.0, base_fillet=1.5)\n')
    p, prompt, wd = _loop(tmp_path, prog)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    assert "JUNCTIONS" in prompt and "rt.boss" in prompt
    best = json.loads((wd / "best.json").read_text())
    # not curved == patches: the patch detector sees a false r=15 "cylinder" on this flat 30x30 plate
    # (even the exact CAD scores 1/2), so check the thing itself: a valid solid with the torus fillet
    assert best["report"]["valid"] and best["report"]["tori"] >= 1


def test_a_missed_feature_names_its_tool(tmp_path):
    p, _, wd = _loop(tmp_path, 'result = cq.Workplane("XY").box(30, 30, 4)\n')       # no boss at all
    hist = json.loads((wd / "history.json").read_text())
    misses = hist[0]["report"]["feature_misses"]
    assert misses and any("rt." in m for m in misses), misses
