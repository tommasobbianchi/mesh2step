"""Acceptance tests for invalid-solid feedback and repair. Run: python3 -m pytest -q tests/test_invalid.py

Contract (spec invalid-feedback.md), module-level functions in recon_loop.py, importable:
  invalid_face_report(shape, limit=10) -> list of dicts, one per face that fails BRepCheck, each with
      "type" (one of plane/cylinder/cone/torus/sphere/bspline/other), "area" (float, mm2) and
      "centre" (3 floats, mm, the face's bounding-box centre). A valid shape -> [].
  try_repair(shape) -> (shape_out, repaired: bool)
      a valid input is returned unchanged with repaired=False; an invalid input goes through
      tools/feature_recon/auto25g.repair_step_shape and repaired=True only if the result is valid.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import recon_loop as rl  # noqa: E402

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox          # noqa: E402
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace  # noqa: E402
from OCP.BRep import BRep_Builder                        # noqa: E402
from OCP.TopoDS import TopoDS_Compound                   # noqa: E402
from OCP.gp import gp_Pnt                                # noqa: E402


def _box():
    return BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()


def _bowtie():
    # a planar face whose wire crosses itself: BRepCheck reports it invalid, deterministically
    poly = BRepBuilderAPI_MakePolygon()
    for x, y in ((0, 0), (10, 10), (10, 0), (0, 10)):
        poly.Add(gp_Pnt(x, y, 0))
    poly.Close()
    face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    c = TopoDS_Compound(); b = BRep_Builder(); b.MakeCompound(c); b.Add(c, face)
    return c


def test_valid_shape_reports_nothing():
    assert rl.invalid_face_report(_box()) == []


def test_invalid_face_is_reported_with_type_area_centre():
    rep = rl.invalid_face_report(_bowtie())
    assert len(rep) >= 1
    r = rep[0]
    assert r["type"] == "plane"
    assert isinstance(r["area"], float)
    assert len(r["centre"]) == 3 and abs(r["centre"][0] - 5.0) < 1e-6 and abs(r["centre"][1] - 5.0) < 1e-6


def test_try_repair_leaves_valid_shape_alone():
    s = _box()
    out, repaired = rl.try_repair(s)
    assert repaired is False and out.IsSame(s)
