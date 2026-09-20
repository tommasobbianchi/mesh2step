"""Is a built cylindrical face backed by mesh material AT ITS OWN LOCATION?

`feature.support` asks a radius question: does the mesh show a cylinder *somewhere* whose radius
is within 3% of this face's? It is the immune system against confabulation and it is mostly
right, but it is blind in both directions, and part 19 of the mechparts corpus is the proof:
`extrude-z` builds one valid solid, p95 0.018 mm against a 2.30 mm limit, and puts **17 of 17**
mesh cylinder patches on analytic curved faces -- and scores `support` 0.21, so it is refused and
the user is handed a faceted block.

This module asks the question the radius test cannot: for THIS face, at THIS axis, radius and
axial extent, does the mesh carry wall there? A triangle backs a cylindrical face when

  * its centroid is within `RTOL` of the face's radius, measured from the face's own axis,
  * its centroid lies inside the face's axial extent,
  * and its normal is perpendicular to the axis within `NDOT` -- the test that keeps a cone from
    backing the staircase of cylinders a slicer cuts out of it, because a cone's wall normal is
    tilted by its half-angle while a cylinder's is exactly radial.

It is positive evidence, never an exemption (guideline 4.B.5). A face the mesh does not carry is
unbacked however plausible its radius, so the test is strictly harder to satisfy than a radius
match on the invention side -- which is the side that matters (0.3.1: absence beats confabulation).

Pure numpy over triangle centroids and normals: one vectorised pass per face. Measured cost is
in `docs/agent-loop.md`; it is a runtime-affordable counter, not a `BRepExtrema` instrument.
"""
from __future__ import annotations

import numpy as np

RTOL_REL = 0.03      # radial tolerance, as a share of the face's radius
RTOL_ABS = 0.05      # mm, so a 0.5 mm fillet is not tested to an impossible tightness
NDOT = 0.10          # |normal . axis|: a wall, not a cone flank or an end face
MIN_TRIS = 6         # a face backed by fewer triangles than this has no evidence behind it
MARGIN = 0.05        # axial extent margin, as a share of the extent


def _faces(shape):
    """(axis point, axis dir, radius, vmin, vmax) for every cylindrical face."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    out = []
    for i in range(1, fm.Extent() + 1):
        f = TopoDS.Face_s(fm.FindKey(i))
        s = BRepAdaptor_Surface(f)
        if s.GetType() != GeomAbs_Cylinder:
            continue
        cyl = s.Cylinder()
        ax = cyl.Axis()
        p, d = ax.Location(), ax.Direction()
        out.append((np.array([p.X(), p.Y(), p.Z()]), np.array([d.X(), d.Y(), d.Z()]),
                    cyl.Radius(), s.FirstVParameter(), s.LastVParameter()))
    return out


def backed_fraction(shape, tri: np.ndarray) -> tuple[float, int, int]:
    """(fraction, backed, total) of the shape's cylindrical faces the mesh carries."""
    faces = _faces(shape)
    if not faces:
        return 1.0, 0, 0
    c = tri.mean(axis=1)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1)
    keep = ln > 0
    c, n = c[keep], n[keep] / ln[keep, None]
    backed = 0
    for p, d, r, v0, v1 in faces:
        d = d / np.linalg.norm(d)
        rel = c - p
        along = rel @ d
        radial = np.linalg.norm(rel - along[:, None] * d, axis=1)
        lo, hi = min(v0, v1), max(v0, v1)
        pad = MARGIN * (hi - lo)
        ok = ((np.abs(radial - r) <= max(RTOL_REL * r, RTOL_ABS))
              & (along >= lo - pad) & (along <= hi + pad)
              & (np.abs(n @ d) <= NDOT))
        if int(ok.sum()) >= MIN_TRIS:
            backed += 1
    return backed / len(faces), backed, len(faces)
