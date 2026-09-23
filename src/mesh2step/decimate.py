"""Opt-in pre-conversion decimation.

Runs BEFORE the triangle-count ceiling and before every conversion path, on the
raw vertices/faces io_mesh.py returned, so a mesh too dense to admit can be
brought under the ceiling instead of refused, and a mesh dense enough to cost
hours of CPU can be traded down to minutes.

Two arms, because they are not interchangeable:

"planar" is geometry-preserving. vtkDecimatePro with an absolute error of
1e-6*diag only removes a vertex that already lies in its neighbours' plane, so
it deletes redundant tessellation and nothing else. On a mechanical part -- flat
faces exported as fans of hundreds of coplanar triangles -- this is most of the
file, at a volume change of order 1e-4 %. Prefer it: it costs the reconstruction
nothing.

"ratio" is Garland-Heckbert quadric edge collapse (fast_simplification) down to a
fraction of the triangles. It is the only arm that reliably caps the cost of a
curved part, and it MOVES the surface: cylinders and fillets are exactly what a
quadric collapse spends its error budget on, so an aggressive ratio can cost the
analytic faces the reconstruction exists to find. That is a trade the caller
makes deliberately, which is why it is a UI option and never a fallback -- an
automatic decimation was measured twice and refused both times.

The volume change is measured, not assumed, and reported to the client either way.
"""
from dataclasses import dataclass

import numpy as np

# below this there is nothing to win and the decimators get unstable on tiny meshes
MIN_TRIS = 100


@dataclass
class DecimateResult:
    verts: np.ndarray  # Nx3 float64
    tris: np.ndarray   # Mx3 int64
    mode: str          # "planar" | "ratio"
    n_faces_before: int
    n_faces_after: int
    dv_pct: float      # signed volume change, % of the input volume
    fit_passes: int = 0   # extra quadric passes it took to get under max_tris (0 = the mode sufficed)


def _volume(verts: np.ndarray, tris: np.ndarray) -> float:
    """Signed volume by the divergence theorem; sign follows the winding."""
    t = verts[tris]
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)


def _quadric(verts: np.ndarray, tris: np.ndarray, keep: float):
    import fast_simplification

    nv, nt = fast_simplification.simplify(verts.astype(np.float32), tris.astype(np.int32),
                                          target_reduction=float(1.0 - keep))
    return np.asarray(nv, dtype=np.float64), np.asarray(nt, dtype=np.int64)


def decimate_mesh(verts: np.ndarray, tris: np.ndarray, *,
                  mode: str = "planar", keep: float = 0.25,
                  max_tris: int | None = None) -> DecimateResult:
    """Reduce the triangle count. `keep` is the fraction to retain, "ratio" only.

    max_tris makes the RESULT a guarantee rather than an attempt. Neither arm can promise a count
    on its own: "planar" stops at the last coplanar vertex, so a curved part barely moves, and the
    quadric collapse treats its ratio as a target it can undershoot on constrained topology. A
    reduction the user asked for and that still lands above the ceiling is a dead end -- Convert
    refuses and the panel offers nothing further. So when max_tris is given, keep collapsing until
    the count is under it. Only when the CALLER asks: an automatic decimation on an untouched
    upload was measured twice and refused both times, and this does not reintroduce it.
    """
    verts = np.asarray(verts, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64)
    v0 = _volume(verts, tris)
    n0 = len(tris)

    if n0 < MIN_TRIS or (mode == "ratio" and keep >= 1.0):
        return DecimateResult(verts, tris, mode, n0, n0, 0.0)

    # An STL is triangle soup: io_mesh.py returns it verbatim, so a 32,688-triangle
    # part arrives with 98,064 vertices -- exactly 3 per triangle, no two triangles
    # sharing one. Both decimators work on EDGES, and a soup has none: measured on
    # mechparts/16, unwelded input left vtkDecimatePro removing 0 triangles and sent
    # the quadric collapse to dV -40% (19: +224%), because it was collapsing a
    # surface whose connectivity it could not see. Welding coincident vertices is a
    # relabelling -- no position moves, dV is exactly 0 -- and it is a precondition
    # here, not an option the caller can forget.
    import trimesh

    _m = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    _m.merge_vertices()
    verts = np.asarray(_m.vertices, dtype=np.float64)
    tris = np.asarray(_m.faces, dtype=np.int64)

    if mode == "planar":
        import pyvista as pv
        import vtk

        faces = np.hstack([np.full((n0, 1), 3, dtype=np.int64), tris]).ravel()
        diag = float(np.linalg.norm(verts.max(0) - verts.min(0)))
        d = vtk.vtkDecimatePro()
        d.SetInputData(pv.PolyData(verts, faces))
        # TargetReduction is an upper bound, not a goal: with an absolute error
        # this small the filter stops at the last genuinely coplanar vertex.
        d.SetTargetReduction(0.999)
        d.PreserveTopologyOn()
        d.SplittingOff()
        d.BoundaryVertexDeletionOff()
        d.SetErrorIsAbsolute(1)
        d.SetAbsoluteError(1e-6 * diag)
        d.SetFeatureAngle(1.0)
        d.Update()
        out = pv.wrap(d.GetOutput()).triangulate()
        nv = np.asarray(out.points, dtype=np.float64)
        nt = np.asarray(out.faces, dtype=np.int64).reshape(-1, 4)[:, 1:]
    elif mode == "ratio":
        nv, nt = _quadric(verts, tris, keep)
    else:
        raise ValueError(f"unknown decimate mode {mode!r}")

    # A decimator that returns nothing usable is a no-op, never a broken mesh
    # handed on to the engine.
    if len(nt) == 0:
        return DecimateResult(verts, tris, mode, n0, n0, 0.0)

    # Overshoot the target by 2% and re-measure: one pass usually lands, a constrained mesh needs
    # two or three, and the loop is bounded so a mesh that simply cannot collapse further returns
    # its best effort instead of spinning.
    passes = 0
    while max_tris and len(nt) > max_tris > MIN_TRIS and passes < 5:
        nv, nt2 = _quadric(nv, nt, max(0.01, (max_tris / len(nt)) * 0.98))
        passes += 1
        if len(nt2) == 0 or len(nt2) >= len(nt):    # no progress: stop rather than loop or break it
            break
        nt = nt2

    if len(nt) == 0:
        return DecimateResult(verts, tris, mode, n0, n0, 0.0)
    v1 = _volume(nv, nt)
    dv = 0.0 if v0 == 0 else 100.0 * (v1 - v0) / v0
    return DecimateResult(nv, nt, mode, n0, len(nt), dv, passes)


if __name__ == "__main__":
    # A tessellated cube: each face split into a 10x10 grid of quads (1200 tris).
    # Every interior vertex is coplanar with its neighbours, so "planar" must
    # collapse it hard while holding the volume exactly; "ratio" must hit its
    # target and stay close on volume.
    import trimesh

    m = trimesh.creation.box(extents=(10.0, 10.0, 10.0)).subdivide().subdivide().subdivide()
    v, t = np.asarray(m.vertices), np.asarray(m.faces)

    r = decimate_mesh(v, t, mode="planar")
    assert r.n_faces_after < r.n_faces_before / 4, r
    assert abs(r.dv_pct) < 0.01, r.dv_pct
    print(f"planar  {r.n_faces_before} -> {r.n_faces_after} tris, dV {r.dv_pct:+.4f}%")

    r = decimate_mesh(v, t, mode="ratio", keep=0.25)
    assert r.n_faces_after <= r.n_faces_before * 0.35, r
    assert abs(r.dv_pct) < 1.0, r.dv_pct
    print(f"ratio   {r.n_faces_before} -> {r.n_faces_after} tris, dV {r.dv_pct:+.4f}%")

    # Under MIN_TRIS nothing is touched -- a single triangle must come back intact.
    r = decimate_mesh(np.eye(3), np.array([[0, 1, 2]]), mode="ratio", keep=0.5)
    assert r.n_faces_after == 1 and r.dv_pct == 0.0, r
    print("tiny mesh left alone")
