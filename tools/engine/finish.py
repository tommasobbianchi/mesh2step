"""Finishes from evidence (docs/ENGINE.md section 3): every round/chamfer the production solid carries becomes a
candidate with its exact size, applied to the program's edges that lie along that face (tree.py "near" selector).
Candidates are grouped by kind and size; each group is kept only if the exact J improves. No guessing of sizes
from mesh sections.

  torus                          -> round, r = minor radius
  cylinder whose axis is not parallel to any pad axis of the program -> round, r = radius (any span)
  cone                           -> chamfer, size = its generatrix length / sqrt 2 (45 deg)
"""
import copy
import math
import sys
from pathlib import Path

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Torus

sys.path.insert(0, str(Path(__file__).resolve().parent))
import undo as U                                       # noqa: E402

from cells import STEP_COST                           # noqa: E402  (the one step cost)
SAME = 0.05            # finish sizes within 5% of each other are one finish
MISSES = 5             # consecutive rejected finish groups before the rest are skipped


def _samples(face, n=6):
    """Points on the face: a UV grid inside its bounds (tori/cones/cylinders here are untrimmed in v or nearly)."""
    s = BRepAdaptor_Surface(face)
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    nu = max(n, int((u1 - u0) / (math.pi / 12)) + 1)
    out = []
    for u in np.linspace(u0, u1, nu):
        for v in np.linspace(v0, v1, 3):
            p = s.Value(float(u), float(v))
            out.append([p.X(), p.Y(), p.Z()])
    return out


def _cylinders(solid, tol):
    """The cylindrical faces a program's solid already has: (axis index, point on the axis line, radius)."""
    out = []
    if solid is None:
        return out
    for f in U.faces(solid):
        s = BRepAdaptor_Surface(f)
        if s.GetType() != GeomAbs_Cylinder:
            continue
        q = s.Cylinder()
        d = U.E._v(q.Axis().Direction())
        a = int(np.argmax(np.abs(d)))
        if abs(d[a]) > 0.999:
            out.append((a, U.E._v(q.Axis().Location()), q.Radius()))
    return out


def groups(shape, pad_axes, solid=None, tol=0.1):
    """Evidence finish faces -> [(op, size, reach, points)], grouped by op and size. A cylinder is a sketch arc
    (not a finish) only if the program's solid already has that face: same axis line and radius. Axis direction
    alone is not enough (part 6: pads along X, Y and Z made every one of its fillet cylinders look like an arc, so
    no fillet was ever tried and the structure imitated them with cuts)."""
    have = _cylinders(solid, tol)
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    bb = Bnd_Box()
    BRepBndLib.Add_s(shape, bb)
    x0, y0, z0, x1, y1, z1 = bb.Get()
    rmax = min(x1 - x0, y1 - y0, z1 - z0) / 2          # a round cannot exceed a full round of the thinnest dimension
    g = {}
    for f in U.faces(shape):
        s = BRepAdaptor_Surface(f)
        t = s.GetType()
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        if t == GeomAbs_Torus:
            op, size = "round", s.Torus().MinorRadius()
        elif t == GeomAbs_Cylinder:
            q = s.Cylinder()
            d, o, r = U.E._v(q.Axis().Direction()), U.E._v(q.Axis().Location()), q.Radius()
            a = int(np.argmax(np.abs(d)))
            if solid is None:
                if any(abs(float(d[b])) > 0.999 for b in pad_axes):
                    continue                            # no solid to compare: a wall along a pad axis is an arc
            elif abs(d[a]) > 0.999 and any(b == a and abs(rr - r) <= tol and np.linalg.norm(np.delete(p - o, a)) <= tol
                                           for b, p, rr in have):
                continue                                # the program already has this face: a sketch arc
            # any other cylinder cannot come from the program's extrusions: a round, whatever its span (a full
            # round's half cylinder spans 180 deg)
            op, size = "round", s.Cylinder().Radius()
        elif t == GeomAbs_Cone:
            op, size = "chamfer", abs(v1 - v0) / math.sqrt(2)
        else:
            continue
        if size <= 0 or (op == "round" and size > rmax + tol):
            continue                                    # a near-flat arc of an outline, not a round
        g.setdefault((op, round(size, 3)), []).extend(_samples(f))
    # one finish, one size: sizes within SAME of each other are one group (the scan's fit scatters one radius
    # over its faces: 2.00 and 2.05 mm on part 9 made two jagged rounds), sized by their samples' weighted mean
    merged = []
    for (op, size), pts in sorted(g.items()):
        if merged and merged[-1][0] == op and size <= merged[-1][1] * (1 + SAME):
            o, s0, p0 = merged[-1]
            merged[-1] = (o, (s0 * len(p0) + size * len(pts)) / (len(p0) + len(pts)), p0 + pts)
        else:
            merged.append((op, size, pts))
    return [(op, size, size, pts) for op, size, pts in sorted(merged, key=lambda x: -len(x[2]))]


def apply(tree, shape, m, tol, j_of):
    """Add evidence finishes to `tree` one group at a time, keeping each only if J improves. -> (tree, J, log)."""
    import tree as T
    pad_axes = {"XYZ".index(f["axis"]) for f in tree["features"] if f["op"] in ("pad", "pocket")}
    cur = copy.deepcopy(tree)
    j, sc = j_of(cur)
    log = []
    solid, _ = T.compile_tree(cur, tol)
    for op, size, reach, pts in groups(shape, pad_axes, solid, tol):
        trial = copy.deepcopy(cur)
        fid = f"F{len(trial['features']) + 1}"
        trial["features"].append({"id": fid, "op": op, "label": f"{'Rounded' if op == 'round' else 'Chamfered'} "
                                  f"edges ({size:.3g} mm, from the scan's faces)", "size": round(size, 4),
                                  "on": trial["features"][0]["id"], "near": [[round(x, 4) for x in p] for p in pts],
                                  "reach": round(reach, 4)})
        j2, sc2 = j_of(trial)
        log.append({"op": op, "size": round(size, 3), "J": round(j2, 4), "kept": j2 > j})
        if j2 > j:
            cur, j, sc, misses = trial, j2, sc2, 0
        else:
            misses = locals().get("misses", 0) + 1
            if misses >= MISSES:                        # groups come most-evidenced first: the rest are the scan's
                break                                   # fit noise (search budget, not a shape rule)
    return cur, j, log


def ground(tree, shape, tol):
    """Every finish not already from evidence (the measured pass guesses edges from mesh sections) re-expressed on
    the evidence: the nearest evidence group of the same op gives its points and exact size, so edges with no round
    or chamfer face next to them drop out (part 1: 2 of 8 rounded edges were 12.8 mm from any round face); a finish
    with no evidence of its kind is removed. -> (tree, changed)"""
    import tree as T
    pad_axes = {"XYZ".index(f["axis"]) for f in tree["features"] if f["op"] in ("pad", "pocket")}
    solid, _ = T.compile_tree({"units": "mm", "features": [f for f in tree["features"]
                                                            if f["op"] in ("pad", "pocket")]}, tol)
    G = groups(shape, pad_axes, solid, tol)
    out = copy.deepcopy(tree)
    feats, changed = [], 0
    for i, f in enumerate(out["features"]):
        if f["op"] not in ("round", "chamfer") or f.get("near"):
            feats.append(f)
            continue
        cands = [g for g in G if g[0] == f["op"]]
        if not cands:
            changed += 1                                # no evidence for this kind of finish: dropped
            continue
        sofar, _ = T.compile_tree({"units": "mm", "features": feats}, tol)
        es = T.modifier_edges(sofar, out, f, tol) if sofar is not None else []
        mids = np.array([T._mid(e) for e in es]) if es else None
        best = min(cands, key=lambda g: np.inf if mids is None else
                   float(np.median(np.min(np.linalg.norm(mids[:, None] - np.array(g[3])[None], axis=2), axis=1))))
        op, size, reach, pts = best
        feats.append({**f, "size": round(size, 4), "near": [[round(x, 4) for x in p] for p in pts],
                      "reach": round(reach, 4), "label": f"{f['label']} (on the scan's faces)"})
        changed += 1
    out["features"] = feats
    return out, changed
