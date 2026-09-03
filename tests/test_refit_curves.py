"""F2P tests for the analytic curve constructors ported in M3c-1.

These constructors are dead code in the converter at this milestone (wiring is
M3c-2): every assertion here is closed-form geometry with absolute tolerances
derived from the construction, so no STL fixture and no golden are needed.
"""

import math

from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Vertex
from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt
from OCP.Precision import Precision
from OCP.TopExp import TopExp

from mesh2step.refit.build import (
    _Curve,
    _constructed_generator,
    _constructed_plane_cyl_cap,
    _curve_residual,
    _make_edge_from_curve,
    _pnt_of,
)
from mesh2step.refit.segment import Region, SurfType


def _cyl_region(radius=4.0, origin=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0)):
    r = Region()
    r.type = SurfType.CYLINDER
    r.ax = gp_Ax3(gp_Pnt(*origin), gp_Dir(*axis))
    r.radius = radius
    return r


def _pln_region(normal=(0.0, 0.0, 1.0), origin=(0.0, 0.0, 0.0)):
    r = Region()
    r.type = SurfType.PLANE
    r.ax = gp_Ax3(gp_Pnt(*origin), gp_Dir(*normal))
    return r


def _mk_vertex(p):
    v = TopoDS_Vertex()
    BRep_Builder().MakeVertex(v, p, Precision.Confusion_s())
    return v


def test_plane_perpendicular_to_cylinder_gives_circle():
    R = 4.0
    h = 3.0
    cyl = _cyl_region(radius=R)
    pln = _pln_region(normal=(0.0, 0.0, 1.0), origin=(0.0, 0.0, h))

    c = _constructed_plane_cyl_cap(pln, cyl)

    assert c.kind == _Curve.CIRC
    assert abs(c.circ.Radius() - R) < 1e-9
    centre = c.circ.Location()
    assert abs(centre.X()) < 1e-9
    assert abs(centre.Y()) < 1e-9
    assert abs(centre.Z() - h) < 1e-9


def test_plane_containing_axis_gives_generator_line():
    R = 4.0
    cyl = _cyl_region(radius=R)  # axis = +z through origin
    pln = _pln_region(normal=(1.0, 0.0, 0.0))  # plane x=0 contains the axis

    c = _constructed_generator(cyl, pln)

    assert c.kind == _Curve.LIN
    axis = gp_Dir(0.0, 0.0, 1.0)
    assert abs(1.0 - abs(c.lin.Direction().Dot(axis))) < 1e-9
    loc = c.lin.Location()
    dist_to_axis = math.hypot(loc.X(), loc.Y())
    assert abs(dist_to_axis - R) < 1e-9


def test_plane_neither_perpendicular_nor_parallel_declines():
    cyl = _cyl_region(radius=4.0)
    pln = _pln_region(normal=(1.0, 0.0, 1.0))  # 45 deg to the axis -> neither

    cap = _constructed_plane_cyl_cap(pln, cyl)
    assert cap.kind == _Curve.NONE

    gen = _constructed_generator(cyl, pln)
    assert gen.kind == _Curve.NONE


def test_residual_on_circle():
    R = 4.0
    cyl = _cyl_region(radius=R)
    pln = _pln_region(normal=(0.0, 0.0, 1.0), origin=(0.0, 0.0, 0.0))

    c = _constructed_plane_cyl_cap(pln, cyl)

    assert abs(_curve_residual(c, gp_Pnt(R, 0.0, 0.0))) < 1e-9
    d = 0.5
    assert abs(_curve_residual(c, gp_Pnt(R + d, 0.0, 0.0)) - d) < 1e-9


def test_circular_edge_is_buildable():
    R = 4.0
    cyl = _cyl_region(radius=R)
    pln = _pln_region(normal=(0.0, 0.0, 1.0), origin=(0.0, 0.0, 0.0))

    c = _constructed_plane_cyl_cap(pln, cyl)

    v1 = _mk_vertex(gp_Pnt(R, 0.0, 0.0))
    v2 = _mk_vertex(gp_Pnt(0.0, R, 0.0))
    edge = _make_edge_from_curve(c, v1, v2, closed_full=False)

    assert edge is not None and not edge.IsNull()
    va = TopoDS_Vertex()
    vb = TopoDS_Vertex()
    TopExp.Vertices_s(edge, va, vb, True)
    assert abs(_curve_residual(c, _pnt_of(va))) < 1e-9
    assert abs(_curve_residual(c, _pnt_of(vb))) < 1e-9
