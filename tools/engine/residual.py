"""Which class of geometry the program cannot represent: the ILP program's residual (voxels it gets wrong),
attributed to the evidence solid's faces by proximity, summarised by face kind and axis. An engine diagnostic
(language/candidate gaps), run over the corpus, never a per-part patch.

usage: residual.py <part.step>...
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cells as C                                      # noqa: E402
import evidence as E                                   # noqa: E402
import jfast as JF                                     # noqa: E402
import solve as S                                      # noqa: E402
import undo as U                                       # noqa: E402

for step in sys.argv[1:]:
    shape = E.read(step)
    bm = S.mesh_of(shape, 0.05)
    tol = max(3e-3 * float(np.linalg.norm(bm.extents)), 0.05)
    tree, info = C.program(bm, tol)
    V, c, h = C.SE.voxels(bm)
    W = JF.rasterize(tree, c)
    R = V ^ W
    idx = np.argwhere(R)
    pts = np.c_[c[0][idx[:, 0]], c[1][idx[:, 1]], c[2][idx[:, 2]]]
    # the nearest mesh triangle of each residual voxel, then the solid face that triangle came from (by centroid)
    fs = U.faces(shape)
    desc = [U.describe(f) for f in fs]
    _, dist, tri = bm.nearest.on_surface(pts) if len(pts) else (None, [], [])
    cent = bm.triangles_center[tri] if len(pts) else np.zeros((0, 3))
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    hist = {}
    uniq, inv = np.unique(np.round(cent / h).astype(int), axis=0, return_inverse=True)
    for ui, q in enumerate(uniq * h):
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, q))).Vertex()
        best, bi = 1e9, None
        for i, f in enumerate(fs):
            d = BRepExtrema_DistShapeShape(v, f)
            if d.IsDone() and d.Value() < best:
                best, bi = d.Value(), i
        k, dvec, span, _ = desc[bi]
        ax = "-" if dvec is None else ("XYZ"[int(np.argmax(np.abs(dvec)))] if np.abs(dvec).max() > 0.999 else "oblique")
        key = f"{k} {'normal' if k == 'plane' else 'axis'} {ax}"
        hist[key] = hist.get(key, 0) + int((inv.ravel() == ui).sum())
    tot = max(1, sum(hist.values()))
    print(Path(step).stem, json.dumps({"ilp": info, "residual_share": round(R.sum() / V.sum(), 4),
                                       "by_face": {k: round(v / tot, 3) for k, v in sorted(hist.items(),
                                                                                            key=lambda x: -x[1])}}),
          flush=True)
