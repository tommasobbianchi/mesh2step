"""Mesh -> best feature tree: the free single-extrusion proposal first; the cheap planner only when that does not
explain the part (< 97 %). The better tree by volume IoU + surface match wins. Run it in its own process with a
memory cap (the server does): OCCT on a bad sketch can take tens of GB.
usage: analyse.py <mesh> <out_dir>      writes out_dir/tree.json and out_dir/analysis.json
"""
import os

# one thread per process, set before numpy loads: the analysis forks workers (OCCT shapes
# cannot be pickled), and a fork taken while BLAS/OpenMP threads exist deadlocked the gate's
# residual pool (19 threads, workers stuck on a futex)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import json  # noqa: E402
import multiprocessing as mp  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plan as PL                                      # noqa: E402
import propose as PR                                   # noqa: E402
import tree as T                                       # noqa: E402

GOOD = 0.97
# from the start: past it the planner is dropped and the proposal stands, so an upload is
# answered in time whatever the part (SV08 shroud: planner 6 min, and hopeless)
PLANNER_DEADLINE_S = 240


def measure(tree, m, tol, occ):
    s, notes = T.compile_tree(tree, tol)
    if s is None:
        return {"score": -1.0}
    d = T.deviation(m, s, tol)
    iou = T.volume_iou(m, s, tol, occ)
    return {"score": round(iou + 0.5 * (d["explained"] - d["extra"]), 4), "iou": round(iou, 4),
            "explained": round(d["explained"], 4), "extra": round(d["extra"], 4), "notes": notes}


def _planner_child(stl, out, q):
    os.setpgrp()                                       # its own group: a deadline kill reaches its workers too
    np.random.seed(1)
    try:
        t2, _, _, pi = PL.plan_tree(stl, out)
        info = {"cost": pi["cost"], "skipped": pi["skipped"], "hopeless": pi.get("hopeless")}
        q.put((t2, info, None))
    except Exception as e:                             # noqa: BLE001
        q.put((None, None, f"{type(e).__name__}: {e}"[:300]))


def _start_planner(stl, out):
    """The planner in a forked child: it inherits the loaded modules; results come back by queue."""
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    child = ctx.Process(target=_planner_child, args=(stl, str(out), q))
    child.start()
    return q, child


def main(stl, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    np.random.seed(0)                                  # surface sampling is random: same mesh, same decisions
    t0 = time.time()
    m = trimesh.load(stl, force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree = {"units": "mm", "features": PR.main_extrusion(m, stl)}
    PR._ids(tree)
    # a stack of thin layers traces the shape but is no designer's history: the planner runs too.
    # Known right after the extrusion pass, so it starts now, forked, while the proposal finishes
    layered = sum(f["op"] == "pad" and f.get("label", "").startswith("Level") for f in tree["features"]) > 3
    q, child = None, None
    if layered:
        q, child = _start_planner(stl, out)
    PR.finish(tree, m, tol)
    occ = T.occupancy(m, m.bounds, n=60)
    info = {"tol": tol, "proposal": measure(tree, m, tol, occ), "planner": None, "chosen": "proposal",
            "cost_usd": 0.0, "layered": layered}
    if child is None and info["proposal"].get("explained", 0) < GOOD:
        q, child = _start_planner(stl, out)
    if child is not None:
        import queue
        import signal
        try:                                           # before join: a full pipe blocks the child
            left = max(5.0, PLANNER_DEADLINE_S - (time.time() - t0))
            t2, pi, err = q.get(timeout=left)
        except queue.Empty:
            os.killpg(child.pid, signal.SIGKILL)
            t2, pi, err = None, None, f"no answer within {PLANNER_DEADLINE_S} s: dropped"
        child.join()
        if err:
            info["planner"] = {"error": err}
        else:
            info["cost_usd"] = pi["cost"]
            if pi.get("hopeless") is not None:         # its bodies cannot win: not measured
                info["planner"] = {"hopeless": pi["hopeless"], "skipped": pi["skipped"]}
            elif t2:
                info["planner"] = dict(measure(t2, m, tol, occ), skipped=pi["skipped"])
                # the history matters more than the last points of match: a planner tree that holds the volume
                # (IoU >= 0.9) replaces a layer stack even when the stack traces the surface closer
                better = info["planner"]["score"] > info["proposal"]["score"]
                if better or (layered and info["planner"].get("iou", 0) >= 0.9):
                    tree, info["chosen"] = t2, "planner"
    info["seconds"] = round(time.time() - t0, 1)
    (out / "tree.json").write_text(json.dumps(tree, indent=1))
    (out / "analysis.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
