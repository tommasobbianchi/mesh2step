"""The engine, end to end (docs/ENGINE.md), the same for every part:

  evidence solid (production STEP) -> exact undo of the local features the base planes cannot explain
  -> minimal pad/pocket program by cells + ILP, on the solid as served and on the undone base
  -> each with and without the finishing pass (rounds/chamfers)
  -> the program with the best exact J on the mesh.

usage: run.py <part.stl> <part.step> [out_tree.json]
"""
import copy
import json
import os
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):   # before numpy: forked workers deadlock
    os.environ.setdefault(_v, "1")                                          # on a threaded BLAS

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cells as C                                      # noqa: E402
import evidence as E                                   # noqa: E402
import finish as FN                                    # noqa: E402
import revolve as RV                                   # noqa: E402
import solve as S                                      # noqa: E402
import undo as U                                       # noqa: E402

PR = C.PR
FINISH_TOP = 2         # raw programs that get the finishing passes
BUDGET = 2100.0        # seconds for the whole part (the fleet kills at 2400)


def j_exact(tree, m, tol):
    sc = PR._forked(PR.pick_score, tree, m, tol, default=-1.0)
    return sc - C.STEP_COST * len(tree["features"]), sc


def run(m, step, tol, ilp_s=60.0):
    t0 = time.time()
    s = E.read(step)
    b = U.base_kind(s)
    sets = U.unexplained_sets(s, b[3])
    base = U.defeature(s, [f for x in sets for f in x]) if sets else None
    rc = RV.candidates(s, m, tol)                      # revolve or not is a hypothesis too (finishes may do it)
    solids = [("as served", s, False, ()), ("as served, sharp outlines", s, True, ())] + \
        ([("as served, revolves", s, False, rc), ("as served, sharp outlines, revolves", s, True, rc)] if rc else []) + \
        ([("undone base", base, False, ())] if base is not None else [])
    log, best = [], None
    end = t0 + BUDGET

    def gen(sh, sharp, extra):
        """One hypothesis's program and its raw exact J (runs in a fork)."""
        t1 = time.time()
        if sh is s:
            tree, info = C.program(m, tol, ilp_s, sharp=sharp, extra=extra)
        else:
            tree, info = C.program(S.mesh_of(sh, tol / 10), tol, ilp_s, shape=sh)
        info["program_s"] = round(time.time() - t1, 1)
        if tree is None:
            return None, info, None, None
        j, sc = j_exact(tree, m, tol)
        return tree, info, j, sc

    def fin_measured(tree):
        """The measured finishing pass, then the evidence finishes on top (runs in a fork)."""
        ft = copy.deepcopy(tree)
        PR.edge_mods(ft, m, tol)
        PR.prune(ft, m, tol)
        bt, _, _ = FN.apply(ft, s, m, tol, lambda t: j_exact(t, m, tol))
        return [("finished", ft, *j_exact(ft, m, tol)), ("finished + evidence finishes", bt, *j_exact(bt, m, tol))]

    def fin_evidence(tree):
        et, _, _ = FN.apply(tree, s, m, tol, lambda t: j_exact(t, m, tol))
        return [("evidence finishes", et, *j_exact(et, m, tol))]

    def note(name, vn, t, info, j, sc):
        nonlocal best
        log.append({"solid": name, "variant": vn, "ops": len(t["features"]), "score": round(sc, 4),
                    "J": round(j, 4), "ilp": info, "t": round(time.time() - t0, 1)})
        # J ties (within 1e-4) go to the program with fewer revolves: a round is one radius on existing edges, a
        # revolve an axis and a whole profile (the longer description; the owner graded pad + round on part 7)
        nrev = sum("revolve" in f for f in t["features"])
        if best is None or j > best[0] + 1e-4 or (abs(j - best[0]) <= 1e-4 and nrev < best[4]):
            best = (j, t, sc, f"{name}, {vn}", nrev)

    # the hypotheses in parallel (independent: same decisions as one after another, a third of the wall time).
    # Sections of the served solid come from the scan itself (watertight; the solid's per-face tessellation cracks
    # and its exact sections can drop edges within its tolerance); the undone base has no scan: its exact sections.
    # "sharp": pads take each band's widest outline, for the finishes to trim (a full round leaves no wall for
    # defeaturing to extend, so the undone base cannot give that outline)
    hs = [(name, PR._fork_start(gen, sh, sharp, extra)) for name, sh, sharp, extra in solids]
    raws = []
    for name, h in hs:
        tree, info, j, sc = PR._fork_collect(h, end, (None, {"error": "died or over budget"}, None, None))
        if tree is None:
            log.append({"solid": name, **info})
            continue
        note(name, "raw", tree, info, j, sc)
        raws.append((j, name, tree, info))
    # finishing costs most of the time (every trial is an exact compile): the FINISH_TOP best raw programs, their
    # two finishing chains all in parallel
    jobs = []
    rev = lambda t: any("revolve" in f for f in t["features"])
    ranked = sorted(raws, key=lambda r: -r[0])
    pick = [r for r in ranked if not rev(r[2])][:FINISH_TOP] + [r for r in ranked if rev(r[2])][:1]
    for _, name, tree, info in pick:                   # the best of each family: finishes vs revolves
        jobs += [(name, info, PR._fork_start(fin_measured, tree)), (name, info, PR._fork_start(fin_evidence, tree))]
    for name, info, h in jobs:
        for vn, t, j, sc in PR._fork_collect(h, end, []):
            note(name, vn, t, info, j, sc)
    out = {"undo_sets": len(sets), "base_planes": list(b[1]), "log": log, "seconds": round(time.time() - t0, 1)}
    if best is None:
        return None, out
    out.update(program=best[3], score=round(best[2], 4), steps=len(best[1]["features"]), merit=round(best[0], 4))
    return best[1], out


if __name__ == "__main__":
    m = trimesh.load(sys.argv[1], force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree, info = run(m, sys.argv[2], tol)
    print(json.dumps(info))
    for f in (tree or {}).get("features", []):
        print(f["id"], f["op"], f.get("axis", ""), f.get("at", ""), f.get("length", f.get("size", "")), f["label"])
    if tree is not None and len(sys.argv) > 3:
        json.dump(tree, open(sys.argv[3], "w"), indent=1)
