"""Acceptance tests for pluggable model backends. Run: python3 -m pytest -q tools/recon/tests/test_backend.py

Contract (spec model-backend.md): the <model> argument of recon_loop.py selects the backend.
  "opus", "sonnet", "claude:<alias>"   -> the claude CLI ($CLAUDE_BIN), as today
  "opencode:<provider/model>"          -> `$OPENCODE_BIN run -m <provider/model> ... <prompt>`, cwd = workdir
     - models whose name contains "vision" also get every render as `-f <png>`
     - other opencode models get NO -f flags and a prompt that says the renders are unavailable
       (the facts are complete) instead of asking to Read image files
     - the program file must be written by the agent to the path named in the prompt, as today
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

FAKE_OC = r'''#!/usr/bin/env python3
import json, os, re, sys
open(os.environ["FAKE_ARGS"], "a").write(json.dumps(sys.argv[1:]) + "\n")
a = sys.argv[1:]                      # real opencode: -f is variadic, so the message must precede it
if "-f" in a:
    assert all(x.endswith(".png") for x in a[a.index("-f"):] if x != "-f"), "prompt swallowed by -f"
prompt = [x for x in a[:a.index("-f")] if x not in ("run", "-m")][-1] if "-f" in a else a[-1]
m = re.findall(r"(\S+recon_\d+\.py)", prompt)
open(m[-1], "w").write('result = cq.Workplane("XY").box(10, 10, 10)\n')
print("done")
'''


@pytest.fixture
def case(tmp_path):
    stl = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(stl)
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"axis": "Z", "bbox_min": [-5, -5, -5], "bbox_max": [5, 5, 5], "levels": []}))
    renders = tmp_path / "renders"; renders.mkdir()
    for v in ("ISO", "PX"):
        (renders / f"cube__{v}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = tmp_path / "fake_opencode"; fake.write_text(FAKE_OC)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return tmp_path, stl, facts, renders, fake


def run(case, model):
    tmp, stl, facts, renders, fake = case
    args_log = tmp / "args.jsonl"; args_log.write_text("")
    env = dict(os.environ, OPENCODE_BIN=str(fake), FAKE_ARGS=str(args_log), RECON_BACKOFF_S="0")
    wd = tmp / "wd"
    p = subprocess.run([sys.executable, str(LOOP), str(stl), str(facts), str(renders), str(wd), model, "1"],
                       env=env, capture_output=True, text=True, timeout=900)
    calls = [json.loads(l) for l in args_log.read_text().splitlines()]
    return p, calls, wd


def test_opencode_text_model(case):
    p, calls, wd = run(case, "opencode:opencode/nemotron-3-ultra-free")
    assert p.returncode == 0, p.stderr[-2000:]
    assert len(calls) == 1
    a = calls[0]
    assert a[0] == "run" and "-m" in a and a[a.index("-m") + 1] == "opencode/nemotron-3-ultra-free"
    assert "-f" not in a                                   # a text model gets no images
    prompt = a[-1]
    assert "unavailable" in prompt.lower()                 # told the renders are unavailable
    assert "__ISO.png" not in prompt                       # and not asked to read them
    assert (wd / "best.json").exists()


def test_opencode_vision_model_gets_renders(case):
    p, calls, wd = run(case, "opencode:deepseek/deepseek-v4-flash-vision-exp")
    assert p.returncode == 0, p.stderr[-2000:]
    a = calls[0]
    files = [a[i + 1] for i, x in enumerate(a) if x == "-f"]
    assert len(files) == 2 and all(f.endswith(".png") for f in files)
    assert (wd / "best.json").exists()


def test_render_paths_given_to_a_vision_model_are_absolute(tmp_path):
    """deepseek-vision got `-f vis/16/16__CROP1.png` relative to the caller, but opencode runs in WD."""
    import stat, subprocess, sys, json, os
    import trimesh
    loop = Path(__file__).resolve().parents[1] / "recon_loop.py"
    trimesh.creation.box(extents=[10, 10, 10]).export(tmp_path / "cube.stl")
    (tmp_path / "facts.json").write_text(json.dumps({"axis": "Z", "bbox_min": [-5]*3, "bbox_max": [5]*3, "levels": []}))
    (tmp_path / "vis").mkdir(); (tmp_path / "vis" / "a.png").write_bytes(b"png")
    fake = tmp_path / "oc"
    fake.write_text("#!/usr/bin/env python3\nimport os, re, sys\n"
                    "fs = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == '-f']\n"
                    "assert fs and all(os.path.isfile(f) for f in fs), fs\n"
                    "m = re.findall(r'(\\S+recon_\\d+\\.py)', sys.argv[sys.argv.index('-m') + 2])\n"
                    "open(m[-1], 'w').write('result = cq.Workplane(\"XY\").box(10, 10, 10)\\n')\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, OPENCODE_BIN=str(fake), RECON_BACKOFF_S="0", RECON_OC_LOCK=str(tmp_path / "lock"))
    p = subprocess.run([sys.executable, str(loop), "cube.stl", "facts.json", "vis", "wd",
                        "opencode:deepseek/deepseek-v4-flash-vision-exp", "1"],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]



def test_the_model_call_never_inherits_stdin(case):
    """`opencode run` appends piped stdin to the message: an open, silent stdin hung it forever."""
    tmp, stl, facts, renders, fake = case
    fake.write_text(FAKE_OC.replace("import json, os, re, sys\n", "import json, os, re, sys\nsys.stdin.read()\n"))
    env = dict(os.environ, OPENCODE_BIN=str(fake), FAKE_ARGS=str(tmp / "a.jsonl"), RECON_BACKOFF_S="0",
               RECON_CALL_TIMEOUT_S="20")
    r, w = os.pipe()                                     # w stays open: stdin never reaches EOF
    log = tmp / "out.txt"
    p = subprocess.Popen([sys.executable, str(LOOP), str(stl), str(facts), str(renders), str(tmp / "wd"),
                          "opencode:opencode/nemotron-3-ultra-free", "1"], env=env, stdin=r,
                         stdout=open(log, "w"), stderr=subprocess.STDOUT)
    os.close(r)
    try:
        rc = p.wait(timeout=300)
    finally:
        os.close(w)
    out = log.read_text()
    assert rc == 0 and "timed out" not in out, out[-1500:]
