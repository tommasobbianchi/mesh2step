"""Which class of geometry the engine's chosen programs get wrong: each program rasterized against its scan, the
wrong voxels attributed to the nearest face of the evidence solid, summed by face kind and axis over the parts
given. An engine diagnostic (language/candidate gaps), read over many parts, never a per-part patch.

usage: residual.py <run_dir> <part>...
"""
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence as E                                   # noqa: E402
import jfast as JF                                     # noqa: E402
import undo as U                                       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
run = Path(sys.argv[1])
total = {}
for n in sys.argv[2:]:
    tree = json.load(open(run / f"{n}.json"))
    m = trimesh.load(f"/home/tommaso/corpora/mechparts/{n}.stl", force="mesh")
    step = ROOT / f"runs/engine/steps/{n}.step"
    shape = E.read(step)
    V, c, h = JF.SE.voxels(m)
    W = JF.rasterize(tree, c)
    miss, extra = V & ~W, W & ~V
    fs = U.faces(shape)
    desc = [U.describe(f) for f in fs]
    hist = {}
    for tag, R in (("missing", miss), ("extra", extra)):
        idx = np.argwhere(R)
        if not len(idx):
            continue
        pts = np.c_[c[0][idx[:, 0]], c[1][idx[:, 1]], c[2][idx[:, 2]]]
        q = np.unique(np.round(pts / (2 * h)).astype(int), axis=0, return_inverse=True)
        for ui, p in enumerate(q[0] * 2 * h):
            v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()
            best, bi = 1e18, 0
            for i, f in enumerate(fs):
                d = BRepExtrema_DistShapeShape(v, f)
                if d.IsDone() and d.Value() < best:
                    best, bi = d.Value(), i
            k, dv, _, _ = desc[bi]
            ax = "-" if dv is None else ("XYZ"[int(np.argmax(np.abs(dv)))] if np.abs(dv).max() > 0.999 else "oblique")
            key = f"{tag}: {k} {'normal' if k == 'plane' else 'axis'} {ax}"
            w = int((q[1].ravel() == ui).sum())
            hist[key] = hist.get(key, 0) + w
    share = {k: round(v / V.sum(), 4) for k, v in sorted(hist.items(), key=lambda x: -x[1])}
    print(n, json.dumps({"wrong": round((miss.sum() + extra.sum()) / V.sum(), 4), "by_face": share}), flush=True)
    for k, v in share.items():
        total[k] = total.get(k, 0) + v
print("TOTAL", json.dumps({k: round(v, 4) for k, v in sorted(total.items(), key=lambda x: -x[1])[:10]}))
