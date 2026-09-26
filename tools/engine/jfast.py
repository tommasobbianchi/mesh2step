"""Fast objective J (docs/ENGINE.md section 2) for the solver's inner loop: a program rasterized straight onto the
part's voxel grid, no OCCT. Extrusions are exact up to the grid; rounds/chamfers are not rasterized (they count as
steps, their volume is left to the exact J of the finalists).

J_fast = IoU(program, part) - STEP_COST * steps
"""
import sys
from pathlib import Path

import numpy as np
import shapely

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tree"))
import search as SE                                    # noqa: E402
import tree as T                                       # noqa: E402

STEP_COST = 0.001


def region(f):
    """A pad/pocket's sketch as one shapely region in tree (u, v): outline minus holes."""
    from shapely.geometry import Polygon
    polys = [Polygon(T.loop_polygon(lp)) for lp in f["loops"]]
    g = polys[0].buffer(0)
    for p in polys[1:]:
        g = g.difference(p.buffer(0))
    return g


def rasterize(tree, c):
    """Tree -> occupancy on the grid with cell centres c (per axis)."""
    W = np.zeros((len(c[0]), len(c[1]), len(c[2])), bool)
    for f in tree["features"]:
        if f["op"] not in ("pad", "pocket"):
            continue
        a = T.AX[f["axis"]]
        mu, mv = T.UV[f["axis"]]
        L = f["length"]
        z0, z1 = (-T.BIG, T.BIG) if L == "through" else sorted((f["at"], f["at"] + L))
        ks = (c[a] >= z0) & (c[a] <= z1)
        if not ks.any():
            continue
        try:
            g = region(f)
        except Exception:                                # noqa: BLE001 -- an unreadable sketch adds nothing
            continue
        U, Vv = np.meshgrid(c[mu], c[mv], indexing="ij")
        M = shapely.contains_xy(g, U, Vv)              # [len(c[mu]), len(c[mv])]
        blk = np.zeros((len(c[mu]), len(c[mv]), len(c[a])), bool)   # (mu, mv, a) order
        blk[:, :, ks] = M[:, :, None]
        S = np.transpose(blk, np.argsort([mu, mv, a]))  # back to (x, y, z)
        W = (W | S) if f["op"] == "pad" else (W & ~S)
    return W


def jfast(tree, V, c):
    W = rasterize(tree, c)
    inter = int((W & V).sum())
    union = int((W | V).sum()) or 1
    iou = inter / union
    return {"iou_fast": round(iou, 4), "j_fast": round(iou - STEP_COST * len(tree["features"]), 4)}


if __name__ == "__main__":
    import json
    import trimesh
    m = trimesh.load(sys.argv[1], force="mesh")
    V, c, h = SE.voxels(m)
    print(json.dumps(jfast(json.load(open(sys.argv[2])), V, c)))
