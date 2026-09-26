"""The engine, end to end (docs/ENGINE.md), the same for every part:

  evidence solid (production STEP) -> exact undo of the local features the base planes cannot explain
  -> minimal pad/pocket program by cells + ILP, on the solid as served and on the undone base
  -> each with and without the finishing pass (rounds/chamfers)
  -> the program with the best exact J on the mesh.

usage: run.py <part.stl> <part.step> [out_tree.json]
"""
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cells as C                                      # noqa: E402
import evidence as E                                   # noqa: E402
import solve as S                                      # noqa: E402
import undo as U                                       # noqa: E402

PR = C.PR


def j_exact(tree, m, tol):
    sc = PR._forked(PR.pick_score, tree, m, tol, default=-1.0)
    return sc - C.STEP_COST * len(tree["features"]), sc


def run(m, step, tol, ilp_s=60.0):
    t0 = time.time()
    s = E.read(step)
    b = U.base_kind(s)
    sets = U.unexplained_sets(s, b[3])
    base = U.defeature(s, [f for x in sets for f in x]) if sets else None
    solids = [("as served", s, False), ("as served, sharp outlines", s, True)] + \
        ([("undone base", base, False)] if base is not None else [])
    log, best = [], None
    for name, sh, sharp in solids:
        # sections of the served solid come from the scan itself (watertight; the solid's per-face tessellation
        # cracks and its exact sections can drop edges within its tolerance); the undone base has no scan: its
        # exact sections. "sharp": pads take each band's widest outline, for the finishes to trim (a full round
        # leaves no wall for defeaturing to extend, so the undone base cannot give that outline)
        if sh is s:
            tree, info = C.program(m, tol, ilp_s, sharp=sharp)
        else:
            tree, info = C.program(S.mesh_of(sh, tol / 10), tol, ilp_s, shape=sh)
        if tree is None:
            log.append({"solid": name, **info})
            continue
        variants = [("raw", tree)]
        ft = copy.deepcopy(tree)
        PR.edge_mods(ft, m, tol)
        PR.prune(ft, m, tol)
        variants.append(("finished", ft))
        for vn, t in variants:
            j, sc = j_exact(t, m, tol)
            log.append({"solid": name, "variant": vn, "ops": len(t["features"]), "score": round(sc, 4),
                        "J": round(j, 4), "ilp": info})
            if best is None or j > best[0]:
                best = (j, t, sc, f"{name}, {vn}")
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
