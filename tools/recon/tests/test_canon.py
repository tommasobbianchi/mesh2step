"""canon.canonicalize_step: a circle revolved about a coplanar axis becomes an exact torus in the STEP.

Part 6 lost its last 3 of 52 features to two r2.54 rounds that Opus built by revolving an arc:
SURFACE_OF_REVOLUTION over a B-spline profile. They are tori, and for R < r only a
DEGENERATE_TOROIDAL_SURFACE can say so (OCCT's writer falls back to the revolution).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.GC import GC_MakeArcOfCircle
from OCP.GeomConvert import GeomConvert
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.gp import gp_Ax1, gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

import canon


def _revolved_spline_arc(path, R, r):
    """Half-disc of radius r centred at (R, 0, 0) in the XZ plane, its arc as a B-spline, revolved about Z."""
    arc = GC_MakeArcOfCircle(gp_Circ(gp_Ax2(gp_Pnt(R, 0, 0), gp_Dir(0, -1, 0)), r),
                             gp_Pnt(R, 0, -r), gp_Pnt(R, 0, r), True).Value()
    spl = GeomConvert.CurveToBSplineCurve_s(arc)
    w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(spl).Edge(),
                                BRepBuilderAPI_MakeEdge(gp_Pnt(R, 0, r), gp_Pnt(R, 0, -r)).Edge()).Wire()
    solid = BRepPrimAPI_MakeRevol(BRepBuilderAPI_MakeFace(w).Face(), gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))).Shape()
    wr = STEPControl_Writer(); wr.Transfer(solid, STEPControl_AsIs); wr.Write(str(path))


@pytest.mark.parametrize("R,r,entity", [(10.0, 3.0, "TOROIDAL_SURFACE("), (1.46, 2.54, "DEGENERATE_TOROIDAL_SURFACE(")])
def test_revolved_arc_becomes_a_torus(tmp_path, R, r, entity):
    p = tmp_path / "t.step"
    _revolved_spline_arc(p, R, r)
    before = canon._summary(canon._read(p))
    assert "SURFACE_OF_REVOLUTION" in p.read_text()
    assert canon.canonicalize_step(p) >= 1
    t = p.read_text()
    assert entity in t and "SURFACE_OF_REVOLUTION" not in t
    after = canon._summary(canon._read(p))
    assert after[:2] == before[:2] and abs(after[2] - before[2]) <= 1e-5 * before[2]


def test_nothing_to_do_leaves_the_file_alone(tmp_path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    p = tmp_path / "b.step"
    wr = STEPControl_Writer(); wr.Transfer(BRepPrimAPI_MakeBox(10, 10, 10).Shape(), STEPControl_AsIs); wr.Write(str(p))
    data = p.read_bytes()
    assert canon.canonicalize_step(p) == 0 and p.read_bytes() == data
