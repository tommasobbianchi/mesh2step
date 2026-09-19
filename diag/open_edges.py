"""Diagnose why mesh-seeded bands rebuild to an invalid solid.

Applies ONE seeded band (or all), then inspects the sewn result for free edges
and per-face rebuild failures, writing findings to diag/open_edges.log.
"""
import sys, tempfile, math
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path("tools/feature_recon").resolve()))
sys.path.insert(0, str(Path("src").resolve()))

from mesh2step.feature import _mesh
from mesh2step.native import convert_native
from mesh2step import rebuild as R
from quads import classify

LOG = Path("diag/open_edges.log")
log = LOG.open("w")


def w(*a):
    print(*a, file=log, flush=True)


stl = Path.home() / "corpora/cadbench/L09_valve_body_normal.stl"
tri = _mesh(stl)
pats = [(o[2], o[3], tri[list(o[4])].reshape(-1, 3)) for o in classify(tri)[2] if o[0] == "cylinder"]

td = tempfile.TemporaryDirectory()
tdp = Path(td.name)
e = tdp / "e.step"
convert_native(stl, e, engine="trueform", timeout=600)

# Build the merged shape exactly like rebuild_cylinders does
from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.TopTools import (TopTools_IndexedMapOfShape,
                          TopTools_IndexedDataMapOfShapeListOfShape)

reader = STEPControl_Reader()
reader.ReadFile(str(e))
reader.TransferRoots()
unify = ShapeUpgrade_UnifySameDomain(reader.OneShape(), True, True, True)
unify.Build()
merged = tdp / "m.step"
w0 = STEPControl_Writer()
w0.Transfer(unify.Shape(), STEPControl_AsIs)
w0.Write(str(merged))

bands = R.bands_from_patches(merged, pats, tol_mm=R.DEFAULT_TOL_MM, known=[])
w(f"seeded bands: {len(bands)}")
for i, b in enumerate(bands):
    w(f"band {i}: r={b.radius:.4f} base={np.round(b.base,3)} axis={np.round(b.axis,3)} "
      f"h={b.height:.4f} members={len(b.face_indices)}")

# Now replicate the application for band 0 only, tracking failures.
band = bands[int(sys.argv[1]) if len(sys.argv) > 1 else 0]

reader2 = STEPControl_Reader()
reader2.ReadFile(str(merged))
reader2.TransferRoots()
shape = reader2.OneShape()
fmap = TopTools_IndexedMapOfShape()
TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire,
                                BRepBuilderAPI_Sewing)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GeomAbs import GeomAbs_Circle
from OCP.gp import gp_Ax3, gp_Cylinder, gp_Dir, gp_Pnt
from OCP.ShapeFix import ShapeFix_Shape, ShapeFix_Solid
from OCP.TopAbs import TopAbs_SHELL

pt = lambda v: np.array([BRep_Tool.Pnt_s(v).X(), BRep_Tool.Pnt_s(v).Y(), BRep_Tool.Pnt_s(v).Z()])

axis, base = np.array(band.axis), np.array(band.base)
cyl = gp_Cylinder(gp_Ax3(gp_Pnt(*base), gp_Dir(*axis)), band.radius)
mf = BRepBuilderAPI_MakeFace(cyl, 0.0, 2 * math.pi, 0.0, band.height)
face = mf.Face()
w(f"new face done={mf.IsDone()}")
emap = TopTools_IndexedMapOfShape()
TopExp.MapShapes_s(face, TopAbs_EDGE, emap)
w(f"new face edges: {emap.Extent()}")
for i in range(1, emap.Extent() + 1):
    ed = TopoDS.Edge_s(emap.FindKey(i))
    bt = BRepAdaptor_Curve(ed).GetType()
    c = BRepAdaptor_Curve(ed).Circle().Location() if bt == GeomAbs_Circle else None
    zz = float((np.array([c.X(), c.Y(), c.Z()]) - base) @ axis) if c is not None else None
    w(f"  edge {i}: type={bt} circle_z={zz} first={pt(TopExp.FirstVertex_s(ed)).round(3)} last={pt(TopExp.LastVertex_s(ed)).round(3)}")

new_faces = [face]
dropped = set(band.face_indices)
rim_of_band = [(base, axis, band.radius, band.height)]
rim_edge = {}
for i in range(1, emap.Extent() + 1):
    ed = TopoDS.Edge_s(emap.FindKey(i))
    if BRepAdaptor_Curve(ed).GetType() != GeomAbs_Circle:
        continue
    c = BRepAdaptor_Curve(ed).Circle().Location()
    z = float((np.array([c.X(), c.Y(), c.Z()]) - base) @ axis)
    rim_edge[(0, round(z, 6))] = ed
w(f"rim_edge keys: {list(rim_edge)}")

tol_mm = R.DEFAULT_TOL_MM

def rim_hit(p1, p2):
    for bi, (base_, axis_, radius, height) in enumerate(rim_of_band):
        z = R._is_rim_chord(p1, p2, base_, axis_, radius, tol_mm)
        if z is None:
            continue
        for zz in (0.0, height):
            if abs(z - zz) <= tol_mm and (bi, round(zz, 6)) in rim_edge:
                return bi, round(zz, 6)
    return None

failed = []
for idx in range(1, fmap.Extent() + 1):
    if idx in dropped:
        continue
    f = TopoDS.Face_s(fmap.FindKey(idx))
    wires, changed, bad = [], False, False
    detail = []
    exp = TopExp_Explorer(f, TopAbs_WIRE)
    while exp.More():
        wire = TopoDS.Wire_s(exp.Current())
        mw = BRepBuilderAPI_MakeWire()
        used_rims = set()
        eexp = TopExp_Explorer(wire, TopAbs_EDGE)
        while eexp.More():
            edge = TopoDS.Edge_s(eexp.Current())
            v1, v2 = TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)
            hit = rim_hit(pt(v1), pt(v2))
            if hit is None:
                mw.Add(edge)
            elif hit not in used_rims:
                used_rims.add(hit)
                mw.Add(rim_edge[hit])
            detail.append((round(float((pt(v1) - base) @ axis), 3), hit is not None))
            eexp.Next()
        if not mw.IsDone():
            bad = True
            break
        wires.append(mw.Wire())
        changed |= bool(used_rims)
        exp.Next()
    if bad or not wires:
        failed.append((idx, "wire-not-done", detail))
        new_faces.append(f)
        continue
    if not changed:
        new_faces.append(f)
        continue
    mkf = BRepBuilderAPI_MakeFace(BRep_Tool.Surface_s(f), wires[0], True)
    for extra in wires[1:]:
        mkf.Add(extra)
    if mkf.IsDone():
        new_faces.append(mkf.Face())
    else:
        failed.append((idx, "makeface-failed", detail))
        new_faces.append(f)

w(f"\nfaces touching the band rim(s) and rebuild failures: {len(failed)}")
for idx, why, detail in failed[:20]:
    w(f"  face {idx}: {why}; edges (z, is_rim_chord)={detail}")

# member faces: what do their z extents look like relative to band?
w("\nmember face z-extents vs band [0, h]:")
for idx in sorted(dropped):
    fp = R._face_points(TopoDS.Face_s(fmap.FindKey(idx)))
    z = (fp - base) @ axis
    rho = np.linalg.norm((fp - base) - np.outer(z, axis), axis=1)
    flag = ""
    if z.min() < -1e-6 or z.max() > band.height + 1e-6:
        flag = "  <-- OUTSIDE BAND EXTENT"
    if (np.abs(rho - band.radius) > 1e-6).any():
        flag += "  <-- OFF-CYLINDER VERTEX"
    w(f"  face {idx}: z[{z.min():.4f},{z.max():.4f}]{flag}")

sew = BRepBuilderAPI_Sewing(max(10 * tol_mm, 1e-4))
for f in new_faces:
    sew.Add(f)
sew.Perform()
out = sew.SewedShape()
w(f"\nsewed shape type: {out.ShapeType()}")  # 0=COMPOUND,1=COMPSOLID,2=SHELL,3=FACE

# free edges after sewing
edge_face = TopTools_IndexedDataMapOfShapeListOfShape()
TopExp.MapShapesAndAncestors_s(out, TopAbs_EDGE, TopAbs_FACE, edge_face)
free = 0
for i in range(1, edge_face.Extent() + 1):
    if edge_face.FindFromIndex(i).Extent() < 2:
        free += 1
        ed = TopoDS.Edge_s(edge_face.FindKey(i))
        v1, v2 = TopExp.FirstVertex_s(ed), TopExp.LastVertex_s(ed)
        w(f"  free edge: {pt(v1).round(3)} -> {pt(v2).round(3)}")
w(f"free edges after sewing: {free}")

fix = ShapeFix_Shape(out)
fix.Perform()
out = fix.Shape()
if out.ShapeType() == TopAbs_SHELL:
    out = ShapeFix_Solid().SolidFromShell(TopoDS.Shell_s(out))
w(f"valid after fix: {BRepCheck_Analyzer(out).IsValid()}")

# what does the neighbour at the rim look like? dump one kept face that had a rim hit
log.close()
print("wrote", LOG)
