"""Is the N29 solid the part, or merely near it? Two-way distance mesh <-> STEP.

The stock output is volume-exact (dV 0.000%) because it IS the triangle dump. N29 moves dV to
1.362%, which is a shape question: where does the solid leave the mesh, and by how much?
  mesh -> solid : samples on the input mesh, distance to the solid  (missing material)
  solid -> mesh : samples on the solid,      distance to the mesh   (added material)
The solid is tessellated finely (0.005 mm deflection) so tessellation error stays negligible.
"""
import sys
import numpy as np
import trimesh
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS


def step_mesh(path, defl=0.005):
    r = STEPControl_Reader()
    assert r.ReadFile(path) == 1
    r.TransferRoots()
    sh = r.OneShape()
    BRepMesh_IncrementalMesh(sh, defl, False, 0.1, True)
    V, F = [], []
    ex = TopExp_Explorer(sh, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        loc = TopLoc_Location()
        t = BRep_Tool.Triangulation_s(f, loc)
        if t is not None:
            tr = loc.Transformation()
            base = len(V)
            for i in range(1, t.NbNodes() + 1):
                p = t.Node(i).Transformed(tr)
                V.append((p.X(), p.Y(), p.Z()))
            # a REVERSED face's triangulation is wound against its outward normal; without this
            # flip the tessellated volume is garbage (measured: +20% / -19% on valid solids whose
            # OCCT volume was -1.6% / -1.0%). Distances are unsigned and were never affected.
            rev = f.Orientation() == TopAbs_REVERSED
            for i in range(1, t.NbTriangles() + 1):
                a, b, c = t.Triangle(i).Get()
                F.append((base + a - 1, base + c - 1, base + b - 1) if rev else (base + a - 1, base + b - 1, base + c - 1))
        ex.Next()
    return trimesh.Trimesh(np.array(V), np.array(F), process=False)


mesh = trimesh.load(sys.argv[1], force="mesh")
solid = step_mesh(sys.argv[2])
diag = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))
rng = np.random.default_rng(0)
N = 20000
pm, _ = trimesh.sample.sample_surface(mesh, N, seed=0)
ps, _ = trimesh.sample.sample_surface(solid, N, seed=0)
d_ms = np.abs(trimesh.proximity.closest_point(solid, pm)[1])
d_sm = np.abs(trimesh.proximity.closest_point(mesh, ps)[1])
for name, d in (("mesh -> solid (missing)", d_ms), ("solid -> mesh (added)  ", d_sm)):
    print(f"{name}: p50 {np.median(d):.4f}  p95 {np.percentile(d,95):.4f}  p99 {np.percentile(d,99):.4f}"
          f"  max {d.max():.4f} mm   (p95 = {100*np.percentile(d,95)/diag:.3f}% of diag {diag:.1f})")
for thr in (0.01, 0.05, 0.1, 0.5):
    print(f"  fraction of mesh farther than {thr} mm from the solid: {100*np.mean(d_ms > thr):.2f}%"
          f"   solid farther from mesh: {100*np.mean(d_sm > thr):.2f}%")
far = pm[d_ms > 0.1]
if len(far):
    print(f"  where the misses are (bbox of {len(far)} samples >0.1 mm): "
          f"{np.round(far.min(0),1).tolist()} .. {np.round(far.max(0),1).tolist()}")
