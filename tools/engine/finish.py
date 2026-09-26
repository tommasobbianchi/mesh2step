"""Finishes from evidence (docs/ENGINE.md section 3): every round/chamfer the production solid carries becomes a
candidate with its exact size, applied to the program's edges that lie along that face (tree.py "near" selector).
Candidates are grouped by kind and size; each group is kept only if the exact J improves. No guessing of sizes
from mesh sections.

  torus                          -> round, r = minor radius
  cylinder, span < 150 deg, axis not parallel to any pad axis of the program -> round, r = radius
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

STEP_COST = 0.001


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


def groups(shape, pad_axes):
    """Evidence finish faces -> [(op, size, reach, points)], grouped by op and size (to 0.01 mm)."""
    g = {}
    for f in U.faces(shape):
        s = BRepAdaptor_Surface(f)
        t = s.GetType()
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        if t == GeomAbs_Torus:
            op, size = "round", s.Torus().MinorRadius()
        elif t == GeomAbs_Cylinder and (u1 - u0) < math.radians(150):
            d = U.E._v(s.Cylinder().Axis().Direction())
            if any(abs(float(d[a])) > 0.999 for a in pad_axes):
                continue                                # a wall along a pad axis: a sketch arc, not a finish
            op, size = "round", s.Cylinder().Radius()
        elif t == GeomAbs_Cone:
            op, size = "chamfer", abs(v1 - v0) / math.sqrt(2)
        else:
            continue
        if size <= 0:
            continue
        key = (op, round(size, 2))
        g.setdefault(key, []).extend(_samples(f))
    return [(op, size, size, pts) for (op, size), pts in sorted(g.items(), key=lambda kv: -len(kv[1]))]


def apply(tree, shape, m, tol, j_of):
    """Add evidence finishes to `tree` one group at a time, keeping each only if J improves. -> (tree, J, log)."""
    pad_axes = {"XYZ".index(f["axis"]) for f in tree["features"] if f["op"] in ("pad", "pocket")}
    cur = copy.deepcopy(tree)
    j, sc = j_of(cur)
    log = []
    for op, size, reach, pts in groups(shape, pad_axes):
        trial = copy.deepcopy(cur)
        fid = f"F{len(trial['features']) + 1}"
        trial["features"].append({"id": fid, "op": op, "label": f"{'Rounded' if op == 'round' else 'Chamfered'} "
                                  f"edges ({size:.3g} mm, from the scan's faces)", "size": round(size, 4),
                                  "on": trial["features"][0]["id"], "near": [[round(x, 4) for x in p] for p in pts],
                                  "reach": round(reach, 4)})
        j2, sc2 = j_of(trial)
        log.append({"op": op, "size": round(size, 3), "J": round(j2, 4), "kept": j2 > j})
        if j2 > j:
            cur, j, sc = trial, j2, sc2
    return cur, j, log
