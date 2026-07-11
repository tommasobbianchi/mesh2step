"""Optional, off-by-default coplanar-face merging.

Distinct stage, distinct tolerance semantics from dedup.py's `tolerance`:
  - `angle_deg`: ANGULAR tolerance -- two adjacent triangles merge only if their
    normals differ by less than this angle. This is the number users are actually
    choosing when they ask for "reduce face count."
  - `linear_tolerance`: the geometric (distance) tolerance OCCT uses while unifying
    the underlying surfaces/curves. Defaults to the SAME value as the dedup
    tolerance, because that is the tolerance the faceted shape was already built to
    -- passing a *tighter* linear tolerance here than the shape was built with is the
    exact FreeCAD #20455 trap (a downstream unify step silently failing to merge
    because an upstream step's tolerance was smaller than this one expects). It can
    still be set independently via --merge-coplanar-linear-tol if a caller has a
    specific reason to.
"""
import math

from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shape


def merge_coplanar(shape: TopoDS_Shape, angle_deg: float, linear_tolerance: float) -> tuple[TopoDS_Shape, int, int]:
    """Returns (merged_shape, n_faces_before, n_faces_after)."""
    n_before = _count_faces(shape)

    unifier = ShapeUpgrade_UnifySameDomain(shape, True, True, True)  # unify faces, edges, concat b-splines
    unifier.SetAngularTolerance(math.radians(angle_deg))
    unifier.SetLinearTolerance(linear_tolerance)
    unifier.Build()
    merged = unifier.Shape()

    n_after = _count_faces(merged)
    return merged, n_before, n_after


def _count_faces(shape: TopoDS_Shape) -> int:
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    n = 0
    while exp.More():
        n += 1
        exp.Next()
    return n
