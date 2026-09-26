"""The engine's backward solver on exact evidence (docs/ENGINE.md section 4):

  production solid -> undo what the base planes cannot explain (exact defeaturing) -> 1-2 plane base
  -> candidate base programs (differential extrusions per plane, prisms intersected) -> + finishes/cuts
  -> exact J on the mesh; the best program wins.

No rule names a shape: candidates come from the solid's faces, decisions from J.

usage: solve.py <part.stl> <part.step> [out_tree.json]
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tree"))
import evidence as E                                   # noqa: E402
import search as SE                                    # noqa: E402
import tree as T                                       # noqa: E402
import undo as U                                       # noqa: E402
import reverse_steps as R                              # noqa: E402

PR = SE.PR
STEP_COST = 0.001


def mesh_of(shape, defl):
    v, f = T.tessellate(shape, defl)
    return trimesh.Trimesh(v, f, process=True)


def cap_levels(shape, a, tol):
    """Heights of the flat faces across axis a (exact, from the solid), merged within tol."""
    zs = []
    for f in U.faces(shape):
        k, d, _, _ = U.describe(f)
        if k == "plane" and abs(abs(float(d[a])) - 1) < 1e-6:
            s = U.BRepAdaptor_Surface(f)
            zs.append(float(E._v(s.Plane().Location())[a]))
    out = []
    for z in sorted(zs):
        if not out or z - out[-1] > tol:
            out.append(z)
    return out


def cand(op, a, reg, z0, z1, label, tol, out):
    for g in PR._polys(reg):
        if g.area > 4 * tol * tol:
            out.append(SE.Cand(op=op, a=a, reg=g, mask=None, k0=0, k1=0, z0=z0, z1=z1, cost=1, label=label,
                               circle=None))


def extrusions(bm, a, levels, tol, share):
    """Differential extrusions along a from one sketch plane: one pad per band between cap levels, from the shared
    face (bottom or top) to the band's far end, outline = the solid's section inside the band. Bands with the same
    outline merge into one pad (one sketch element)."""
    out = []
    bands = list(zip(levels[:-1], levels[1:]))
    if share == "top":
        bands = bands[::-1]
    regs = []
    for z0, z1 in bands:
        zm = (z0 + z1) / 2
        regs.append((z0, z1, PR.slab_region(bm, a, zm - tol / 4, zm + tol / 4)))
    base = levels[0] if share == "bottom" else levels[-1]
    merged = []
    for z0, z1, g in regs:
        if merged and merged[-1][2].symmetric_difference(g).area < 4 * tol * tol:
            merged[-1] = (min(merged[-1][0], z0), max(merged[-1][1], z1), merged[-1][2])
        else:
            merged.append((z0, z1, g))
    for z0, z1, g in merged:
        lo, hi = (base, z1) if share == "bottom" else (z0, base)
        cand("pad", a, g, lo, hi, "differential extrusion", tol, out)
    return out


def intersection(bm, a, b, tol):
    """Profile along a extruded through, cut by the complement of the profile along b."""
    from shapely.geometry import box
    lo, hi = bm.bounds
    out = []
    cand("pad", a, PR.slab_region(bm, a, float(lo[a]), float(hi[a])), float(lo[a]), float(hi[a]), "profile", tol,
         out)
    u, v = SE.reverse.plane_axes(b)
    outside = box(lo[u] - tol, lo[v] - tol, hi[u] + tol, hi[v] + tol).difference(
        PR.slab_region(bm, b, float(lo[b]), float(hi[b])).buffer(tol / 4, join_style=2))
    cand("pocket", b, outside, float(lo[b]) - 2 * tol, float(hi[b]) + 2 * tol, "second profile, cut through", tol, out)
    return out


def base_programs(base, planes, tol):
    """Every candidate program for the base: per plane, differential extrusions from either end; for two planes,
    each plane's extrusions intersected with the other plane's profile."""
    bm = mesh_of(base, tol / 10)
    progs = []
    for a in planes:
        lv = cap_levels(base, a, tol)
        if len(lv) >= 2:
            for share in ("bottom", "top"):
                progs.append((f"extrude {'XYZ'[a]} from {share}", extrusions(bm, a, lv, tol, share)))
    if len(planes) == 2:
        a, b = planes
        for x, y in ((a, b), (b, a)):
            progs.append((f"{'XYZ'[x]} profile cut by {'XYZ'[y]} profile", intersection(bm, x, y, tol)))
            lv = cap_levels(base, x, tol)
            if len(lv) > 2:
                for share in ("bottom", "top"):
                    ext = extrusions(bm, x, lv, tol, share)
                    progs.append((f"extrude {'XYZ'[x]} from {share}, cut by {'XYZ'[y]} profile",
                                  ext + intersection(bm, x, y, tol)[1:]))
    # the structure search on the clean base: no finishes left, so its residue levels only absorb the grid's
    # staircase; each distinct undo sequence is one more candidate
    V, c, h = SE.voxels(bm)
    seen = set()
    for lv in R.LEVELS:
        R.FINISH = lv
        r = R.reverse(V)
        if r[2] is None:
            continue
        sig = "|".join(R.describe(r)[1])
        if sig in seen:
            continue
        seen.add(sig)
        t = R.to_tree(bm, V, c, h, r, tol)
        progs.append((f"structure search ({len(t['features'])} ops)", t))
    R.FINISH = R.LEVELS[0]
    return progs


def solve(m, step, tol, budget=240.0):
    t0 = time.time()
    s = E.read(step)
    b = U.base_kind(s)
    sets = U.unexplained_sets(s, b[3])
    base = U.defeature(s, [f for x in sets for f in x]) if sets else s
    if base is None:
        base = s                                       # refused: the base carries the unexplained faces
    b2 = U.base_kind(base)
    planes = b2[1]
    occ = PR._occ(m)
    results = []
    for name, cands in base_programs(base, planes, tol):
        if not cands:
            continue
        tree = cands if isinstance(cands, dict) else SE.to_tree(cands, list(range(len(cands))), tol)
        sc = PR._forked(PR.pick_score, tree, m, tol, default=-1.0)
        results.append((sc - STEP_COST * len(tree["features"]), name, tree, sc))
    results.sort(key=lambda r: -r[0])
    info = {"base_planes": list(planes), "undo_sets": len(sets), "base_unexplained": round(b2[2], 4),
            "candidates": [(r[1], round(r[3], 4), len(r[2]["features"])) for r in results]}
    best = None
    for raw, name, tree, sc in results[:2]:            # finish the two best raw programs: J decides after finishing
        if best is not None and time.time() - t0 > budget:
            break
        PR.edge_mods(tree, m, tol)
        PR.prune(tree, m, tol)
        sc = PR._forked(PR.pick_score, tree, m, tol, default=-1.0)
        j = sc - STEP_COST * len(tree["features"])
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
