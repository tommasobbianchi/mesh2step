"""Probe: what do classic decimators do to a mechanical STL, and to the quad signal quads.py relies on?
arms:  exact-planar = vtkDecimatePro, absolute error 1e-6 * diag (only vertices lying in their neighbours'
                      plane go: the exact recursive planar merge), topology and boundaries preserved;
       qem-10%      = fast_simplification (Garland-Heckbert quadric edge collapse) to 10% of the triangles.
reports triangles, volume change, and the cylinders quads.classify still finds.
usage: python3 decimate_probe.py <stl> [...]"""
import sys, time
import numpy as np
import pyvista as pv
import vtk
import fast_simplification
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from quads import classify


def tris_of(mesh):
    f = mesh.faces.reshape(-1, 4)[:, 1:]
    return mesh.points[f].astype(float)


def vol(tri):
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def report(label, tri, v0, t0):
    _, nq, out = classify(tri)
    cyl = sorted(round(o[2], 2) for o in out if o[0] == "cylinder")
    print(f"  {label:13} tris {len(tri):7}  dV {100 * (vol(tri) - v0) / v0:+.4f}%  quad-cyl {len(cyl):3}"
          f"  radii {cyl[:10]}{'...' if len(cyl) > 10 else ''}  [{time.time() - t0:.1f}s]", flush=True)


for p in sys.argv[1:]:
    m = pv.read(p).clean(tolerance=1e-9).triangulate()
    tri0 = tris_of(m); v0 = vol(tri0)
    diag = float(np.linalg.norm(tri0.reshape(-1, 3).max(0) - tri0.reshape(-1, 3).min(0)))
    print(p.rsplit("/", 1)[-1], flush=True)
    report("input", tri0, v0, time.time())
    t0 = time.time()
    d = vtk.vtkDecimatePro()
    d.SetInputData(m)
    d.SetTargetReduction(0.999)
    d.PreserveTopologyOn(); d.SplittingOff(); d.BoundaryVertexDeletionOff()
    d.SetErrorIsAbsolute(1); d.SetAbsoluteError(1e-6 * diag)
    d.SetFeatureAngle(1.0)
    d.Update()
    report("exact-planar", tris_of(pv.wrap(d.GetOutput())), v0, t0)
    t0 = time.time()
    f = m.faces.reshape(-1, 4)[:, 1:]
    pts, faces = fast_simplification.simplify(m.points, f, target_reduction=0.9)
    report("qem-10%", pts[faces].astype(float), v0, t0)
