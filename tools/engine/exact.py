"""The owner's reverse logic done exactly on the B-rep (docs/ENGINE.md section 4, backward):

  while the solid needs more than one sketch plane:
      keep a plane p; the faces p cannot explain split into edge-connected sets; defeature them (exact undo)
      each undo's effect = the boolean difference between before and after, an exact solid:
          a prism along some axis  -> one pad (the undo removed it) or pocket (the undo filled it)
          a prism along no axis    -> a finish (round/chamfer: the only ops of L that make one)
  the one-plane solid left      -> differential extrusions along p
  program = base extrusions + the undone ops in reverse order; every decision between branches by exact J.

usage: exact.py <part.stl> <part.step> [out_tree.json]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tree"))
import evidence as E                                   # noqa: E402
import search as SE                                    # noqa: E402
import solve as S                                      # noqa: E402
import tree as T                                       # noqa: E402
import undo as U                                       # noqa: E402

PR = SE.PR
MAX_UNDO = 40


def explained_by(shape, planes, ang=None):
    """Mask of the faces an extrusion along any of `planes` explains (undo.base_kind's rule, fixed planes)."""
    import math
    ang = ang or math.radians(0.5)
    out = []
    for f in U.faces(shape):
        k, d, _, _ = U.describe(f)
        ok = False
        if d is not None:
            for a in planes:
                c = abs(float(d @ U.AXES[a]))
                ok |= (k == "plane" and (c > math.cos(ang) or c < math.sin(ang))) or (k == "cylinder" and c > math.cos(ang))
        out.append(ok)
    return np.array(out, bool)


def prism_axis(solid):
    """The axis along which every face of the solid is explained (a prism along it), or None."""
    for a in range(3):
        if explained_by(solid, (a,)).all():
            return a
    return None


def volume(sh):
    try:
        return T.volume(sh)
    except Exception:                                    # noqa: BLE001
        return 0.0


def reverse_exact(s, keep, tol):
    """Undo everything plane `keep` cannot explain. -> (one-plane solid, [(op, axis, delta solid)] in undo order)."""
    ops, state = [], s
    for _ in range(MAX_UNDO):
        ex = explained_by(state, (keep,))
        if ex.all():
            break
        sets = U.unexplained_sets(state, ex)
        # the biggest set first: undo whole features before their details; a refused set is kept for later
        sets.sort(key=lambda x: -sum(U.describe(f)[3] for f in x))
        done = False
        for fs in sets:
            after = U.defeature(state, fs)
            if after is None:
                continue
            filled = BRepAlgoAPI_Cut(after, state).Shape()     # material the undo put back: the op was a cut
            removed = BRepAlgoAPI_Cut(state, after).Shape()    # material the undo took away: the op was a pad
            for op, delta in (("pocket", filled), ("pad", removed)):
                if volume(delta) > tol ** 3:
                    ops.append((op, prism_axis(delta), delta))
            state, done = after, True
            break
        if not done:
            break                                        # nothing more can be undone: the base keeps the rest
    return state, ops


def op_cands(op, a, delta, tol):
    """One undone op as sketch candidates along its axis: the delta's projection over its extent."""
    dm = S.mesh_of(delta, tol / 10)
    lo, hi = dm.bounds
    reg = PR.slab_region(dm, a, float(lo[a]), float(hi[a]))
    out = []
    z0, z1 = float(lo[a]), float(hi[a])
    if op == "pocket":                                   # a cut may reach past the part's faces: never short
        z0, z1 = z0 - tol / 2, z1 + tol / 2
    S.cand(op, a, reg, z0, z1, "undone " + ("cut" if op == "pocket" else "pad"), tol, out)
    return out


def programs(s, tol):
    """One program per kept plane (the planes the solid's faces use), built backwards exactly."""
    b = U.base_kind(s)
    keeps = sorted(set(b[1]) | {a for a in range(3) if explained_by(s, (a,)).mean() > 0.3})
    out = []
    for keep in keeps:
        base, ops = reverse_exact(s, keep, tol)
        bm = S.mesh_of(base, tol / 10)
        lv = S.cap_levels(base, keep, tol)
        if len(lv) < 2:
            continue
        undone = []
        finishes = 0
        for op, a, delta in reversed(ops):              # forward order: the last undo is the first op after the base
            if a is None:
                finishes += 1                            # a finish: left to the finishing pass (round/chamfer by J)
                continue
            undone += op_cands(op, a, delta, tol)
        for share in ("bottom", "top"):
            cands = S.extrusions(bm, keep, lv, tol, share) + undone
            out.append((f"keep {'XYZ'[keep]}, extrude from {share}, {len(ops)} undos ({finishes} finishes)", cands))
    return out


def solve(m, step, tol, budget=300.0):
    t0 = time.time()
    s = E.read(step)
    res = []
    for name, cands in programs(s, tol):
        if not cands:
            continue
        tree = SE.to_tree(cands, list(range(len(cands))), tol)
        sc = PR._forked(PR.pick_score, tree, m, tol, default=-1.0)
        res.append((sc - S.STEP_COST * len(tree["features"]), name, tree, sc))
    res.sort(key=lambda r: -r[0])
    info = {"candidates": [(r[1], round(r[3], 4), len(r[2]["features"])) for r in res]}
    best = None
    for _, name, tree, _ in res[:2]:
        if best is not None and time.time() - t0 > budget:
            break
        PR.edge_mods(tree, m, tol)
        PR.prune(tree, m, tol)
        sc = PR._forked(PR.pick_score, tree, m, tol, default=-1.0)
        j = sc - S.STEP_COST * len(tree["features"])
        if best is None or j > best[0]:
            best = (j, name, tree, sc)
    if best is None:
        return None, info
    info.update(program=best[1], score=round(best[3], 4), steps=len(best[2]["features"]), merit=round(best[0], 4),
                seconds=round(time.time() - t0, 1))
    return best[2], info


if __name__ == "__main__":
    m = trimesh.load(sys.argv[1], force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree, info = solve(m, sys.argv[2], tol)
    print(json.dumps(info))
    for f in (tree or {}).get("features", []):
        print(f["id"], f["op"], f.get("axis", ""), f.get("at", ""), f.get("length", f.get("size", "")), f["label"])
    if tree is not None and len(sys.argv) > 3:
        json.dump(tree, open(sys.argv[3], "w"), indent=1)
