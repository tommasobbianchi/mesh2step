#!/usr/bin/env python3
"""One upload -> renders + facts -> reflective loop over a model cascade (spec specs/recon-part.md).

usage: recon_part.py <stl> <workdir> --models M1 [M2 ...] [--rounds N] [--timeout S]

Cheaper models first; the first ACCEPTED result stops the cascade. ACCEPTED = valid solid, max p95
<= 0.5% of the mesh diagonal, every mesh cylinder patch represented. Exit: accepted 0, best_effort 3,
unavailable 75 (every model hit quota), failed 2.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
RENDER = Path.home() / ".claude/skills/deepseek-vision/scripts/render.py"


def p95(rep):
    return max(rep["p95_mesh_to_solid"], rep["p95_solid_to_mesh"])


def run_loop(cmd, timeout):
    """Run one model's loop in its own process group; on timeout kill the whole group (model call too)."""
    p = subprocess.Popen(cmd, start_new_session=True)
    try:
        return p.wait(timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.wait()
        return 124


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl"); ap.add_argument("workdir")
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=2700)
    a = ap.parse_args()
    t0 = time.time()
    stl, wd = os.path.abspath(a.stl), Path(a.workdir).resolve()
    wd.mkdir(parents=True, exist_ok=True)
    vis = wd / "vis"
    r = subprocess.run([sys.executable, str(RENDER), stl, "--out", str(vis), "--crops", "2"],
                       capture_output=True, text=True)
    vis.mkdir(exist_ok=True)                        # the loop runs without images if rendering failed
    if r.returncode:
        print(f"render failed (continuing without images): {(r.stdout + r.stderr)[-300:]}", flush=True)
    subprocess.run([sys.executable, str(HERE / "facts.py"), stl, str(wd / "facts.json"), "auto"],
                   capture_output=True, text=True)

    mesh = trimesh.load(stl, force="mesh")
    diag = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))
    tried, results, winner = [], [], None
    for i, model in enumerate(a.models, 1):
        md = wd / f"m{i}_{re.sub(r'[^A-Za-z0-9]', '_', model)}"
        rc = run_loop([sys.executable, str(HERE / "recon_loop.py"), stl, str(wd / "facts.json"), str(vis),
                       str(md), model, str(a.rounds)], a.timeout - (time.time() - t0))
        best, ok = None, False
        if (md / "best.json").exists():
            best = json.loads((md / "best.json").read_text())
            rep, rp = best["report"], best["represent"]
            ok = bool(rep["valid"] and p95(rep) <= 0.005 * diag and rp["curved"] == rp["patches"])
            if rep["valid"]:
                results.append((model, md, best))
        tried.append({"model": model, "exit": rc, "accepted": ok})
        if ok:
            winner = (model, md, best); break
        if time.time() - t0 >= a.timeout:
            break

    if winner:
        status = "accepted"
    elif results:
        status = "best_effort"
        winner = max(results, key=lambda r: (r[2]["represent"]["curved"], -p95(r[2]["report"])))
    elif tried and all(t["exit"] == 75 for t in tried):
        status = "unavailable"
    else:
        status = "failed"
    model, md, best = winner or (None, None, None)
    res = {"status": status, "model": model,
           "best_step": str(md / "best.step") if md else None,
           "report": best["report"] if best else None, "represent": best["represent"] if best else None,
           "models_tried": tried, "seconds": round(time.time() - t0, 1)}
    (wd / "recon_result.json").write_text(json.dumps(res, indent=1))
    rp = res["represent"] or {}
    print(f"RECON status={status} model={model} seconds={res['seconds']} "
          f"curved={rp.get('curved')}/{rp.get('patches')} p95={p95(best['report']) if best else None}")
    return {"accepted": 0, "best_effort": 3, "unavailable": 75, "failed": 2}[status]


if __name__ == "__main__":
    sys.exit(main())
