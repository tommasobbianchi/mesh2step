"""Toolbox: one exact construction per junction family (docs/JUNCTIONS.md, specs/recon-tools.md).

Every tool takes and returns a cadquery Workplane holding one solid, and builds its blends from
analytic primitives (makeCylinder / makeCone / makeTorus + booleans) so that plane / cylinder /
cone / torus / sphere faces survive STEP export + `canon.canonicalize_step`. A plane argument is a
`cq.Plane` whose origin lies on the face and whose normal points OUT of the material; `center` is
given in that plane's local x/y coordinates.
"""
import math

import cqshim  # noqa: F401  (import before cadquery on this box)
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType

_ANALYTIC = {
    GeomAbs_SurfaceType.GeomAbs_Plane,
    GeomAbs_SurfaceType.GeomAbs_Cylinder,
    GeomAbs_SurfaceType.GeomAbs_Cone,
    GeomAbs_SurfaceType.GeomAbs_Torus,
    GeomAbs_SurfaceType.GeomAbs_Sphere,
}
_V = cq.Vector


def _frame(plane):
    """(origin, normal, xdir, ydir) of a cq.Plane, as cq.Vector."""
    o = _V(*plane.origin.toTuple())
    n = _V(*plane.zDir.toTuple()).normalized()
    x = _V(*plane.xDir.toTuple()).normalized()
    return o, n, x, n.cross(x)


def _at(o, x, y, center, z, n):
    """World point at plane-local (cx, cy) and signed height z along the plane normal."""
    cx, cy = center
    return o + x * cx + y * cy + n * z


def _wp(shape):
    return cq.Workplane("XY").newObject([shape])


def _cyl(o, x, y, n, center, radius, z0, z1):
    """A cylinder between plane-heights z0 and z1 (z1 > z0), axis = the plane normal."""
    base = _at(o, x, y, center, z0, n)
    return cq.Solid.makeCylinder(radius, z1 - z0, base, n)


def _torus(o, x, y, n, center, major, minor, z):
    return cq.Solid.makeTorus(major, minor, _at(o, x, y, center, z, n), n)


def _ring_minus_torus(o, x, y, n, center, r_in, r_out, major, minor, zc, z0=0.0):
    """Annular ring [r_in, r_out] from height z0 to z0+zc, minus the torus tube centred at z0+zc.
    What remains is the quarter-round wedge bounded by the torus surface: the material a concave
    fillet adds (zc > 0) or a convex round removes (zc < 0). `major` is the torus centre-circle
    radius (equals r_out for a fillet on a foot, r_in for a round on a top edge)."""
    lo, hi = (z0, z0 + zc) if zc >= 0 else (z0 + zc, z0)
    ring = _cyl(o, x, y, n, center, r_out, lo, hi).cut(_cyl(o, x, y, n, center, r_in, lo, hi))
    return ring.cut(_torus(o, x, y, n, center, major, minor, z0 + zc))


def _foot_fillet(o, x, y, n, center, radius, fillet, z0=0.0):
    """Concave torus wedge where a cylinder of `radius` meets a face (foot of a boss)."""
    return _ring_minus_torus(o, x, y, n, center, radius, radius + fillet,
                             radius + fillet, fillet, fillet, z0)


def _mouth_round(o, x, y, n, center, radius, rnd, z0=0.0):
    """Convex torus wedge that rounds a hole of `radius` where it meets a face (its mouth)."""
    return _ring_minus_torus(o, x, y, n, center, radius, radius + rnd,
                             radius + rnd, rnd, -rnd, z0)


def _extent(solid):
    """Rough size of the solid, so a through-cut really goes through."""
    bb = solid.BoundingBox()
    return math.sqrt(bb.xlen ** 2 + bb.ylen ** 2 + bb.zlen ** 2)


def boss(solid, base, center, radius, height, base_fillet=0.0, top_round=0.0):
    """Add a cylindrical boss on the face `base` at local `center`, growing along its normal.

    radius is the boss radius, height its length; base_fillet >= 0 adds a concave torus fillet
    where the boss meets the face, top_round >= 0 (< radius) rounds the top edge with a convex
    torus (major radius radius-top_round may fall below the minor one: a legitimate spindle).
    Returns the union as one Workplane.
    """
    o, n, x, y = _frame(base)
    s = solid.val().fuse(_cyl(o, x, y, n, center, radius, 0.0, height))
    if base_fillet > 0:
        s = s.fuse(_foot_fillet(o, x, y, n, center, radius, base_fillet))
    if top_round > 0:
        s = s.cut(_ring_minus_torus(o, x, y, n, center, radius - top_round, radius,
                                    radius - top_round, top_round, -top_round, height))
    return _wp(s)


def hole(solid, top, center, radius, depth=None, mouth_chamfer=0.0, mouth_round=0.0):
    """Drill a hole into `top` at local `center`, inward along the plane normal.

    radius is the hole radius; depth is measured from the face (None = through the solid).
    mouth_chamfer > 0 cuts a 45-degree cone widening the mouth to radius+mouth_chamfer;
    mouth_round > 0 rounds the mouth edge with a convex torus of that minor radius.
    Returns the cut solid as one Workplane.
    """
    o, n, x, y = _frame(top)
    span = depth if depth is not None else _extent(solid.val())
    cut = _cyl(o, x, y, n, center, radius, -span, span)
    if mouth_chamfer > 0:
        c = mouth_chamfer
        cut = cut.fuse(cq.Solid.makeCone(
            radius, radius + c, c, _at(o, x, y, center, -c, n), n))
    if mouth_round > 0:
        cut = cut.fuse(_mouth_round(o, x, y, n, center, radius, mouth_round))
    return _wp(solid.val().cut(cut))


def counterbore(solid, top, center, radius, bore_radius, bore_depth, depth=None):
    """Drill a through/blind hole of `radius` with a coaxial counterbore at the mouth.

    top is the face; center is local; radius is the pilot hole, depth its depth (None =
    through). bore_radius > radius is the counterbore radius, bore_depth its depth from the
    face. Returns the cut solid as one Workplane.
    """
    o, n, x, y = _frame(top)
    span = depth if depth is not None else _extent(solid.val())
    cut = _cyl(o, x, y, n, center, radius, -span, span).fuse(
        _cyl(o, x, y, n, center, bore_radius, -bore_depth, span))
    return _wp(solid.val().cut(cut))


def ring_fillet(solid, wall, center, radius, fillet, convex=False):
    """Blend an existing cylinder of `radius` (axis = wall normal through center) into `wall`.

    concave (default) adds a torus fillet to the inside corner where a boss of that radius
    meets the face; convex=True removes the corner to round a hole's mouth. fillet is the torus
    minor radius. Returns the blended solid as one Workplane.
    """
    o, n, x, y = _frame(wall)
    piece = _mouth_round(o, x, y, n, center, radius, fillet) if convex else \
        _foot_fillet(o, x, y, n, center, radius, fillet)
    s = solid.val()
    return _wp(s.cut(piece) if convex else s.fuse(piece))


def edge_round(solid, selector, radius):
    """Round the edges of `solid` matched by `selector` with a cadquery fillet of `radius`.

    selector is a cadquery edge selector (string like "|Z" or a Selector). Raises ValueError
    naming the edge if the fillet yields any face that is not analytic (plane/cylinder/cone/
    torus/sphere). Returns the filleted solid as one Workplane.
    """
    picked = solid.edges(selector)
    n = len(picked.vals())
    result = picked.fillet(radius)
    for face in result.faces().vals():
        st = BRepAdaptor_Surface(face.wrapped).GetType()
        if st not in _ANALYTIC:
            raise ValueError(
                f"edge_round: {selector!r} on {n} edge(s) produced a non-analytic "
                f"{str(st).split('_')[-1]} face; cannot round this edge exactly")
    return result
