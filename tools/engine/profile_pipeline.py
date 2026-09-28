"""The whole pipeline, profiled stage by stage (tools/engine/cgprof.py): converter (a checkout's /api/convert,
in-process), design-history engine, FreeCAD export. One part at a time, nothing else of ours running.

usage: profile_pipeline.py <out_dir> <converter_checkout> <stl>...
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROF = [sys.executable, str(HERE / "cgprof.py")]

FC_SNIPPET = r'''
import json, sys, time
sys.path.insert(0, "tools/tree")
import numpy as np, trimesh, fcstd
m = trimesh.load(sys.argv[1], force="mesh"); tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
g = fcstd.gui_save
def gui(out):
    print(f"MARK fcstd.gui_save start {time.time():.2f}", flush=True)
    try:
        return g(out)
    finally:
        print(f"MARK fcstd.gui_save end {time.time():.2f}", flush=True)
fcstd.gui_save = gui
print(f"MARK fcstd.build start {time.time():.2f}", flush=True)
r = fcstd.build(json.load(open(sys.argv[2])), sys.argv[3], tol)
print(f"MARK fcstd.build end {time.time():.2f}", flush=True)
print("FCSTD " + json.dumps({k: r.get(k) for k in ("ok", "valid", "solids", "symdiff", "gui_saved")}), flush=True)
'''


def main():
    out, conv = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "fc_snippet.py").write_text(FC_SNIPPET)
    for stl in map(lambda x: Path(x).resolve(), sys.argv[3:]):
        p = stl.stem
        step = out / "conv" / f"{p}.step"
        subprocess.run([*PROF, str(out / f"{p}.conv"), "--", sys.executable, str(conv / "tools/convbench.py"),
                        str(out / "conv"), str(stl)], cwd=conv)
        if step.exists():
            subprocess.run([*PROF, str(out / f"{p}.eng"), "--", "env", "M2S_MARKS=1", sys.executable,
                            str(HERE / "run.py"), str(stl), str(step), str(out / f"{p}.tree.json")], cwd=REPO)
        tree = out / f"{p}.tree.json"
        fc = out / "fc"
        fc.mkdir(exist_ok=True)
        if tree.exists():
            subprocess.run([*PROF, str(out / f"{p}.fc"), "--", sys.executable, str(out / "fc_snippet.py"), str(stl),
                            str(tree), str(fc / f"{p}.FCStd")], cwd=REPO)
        print(json.dumps({"part": p, "step": step.exists(), "tree": tree.exists()}), flush=True)


if __name__ == "__main__":
    main()
