"""Full-round plates, fillet version. Outline from a slice INSIDE the round (smooth, no tangency noise),
offset outward in 2D by the analytic full-round inset d(t) = rho - sqrt(rho^2 - (rho - t)^2), rho = T/2,
prism over T, fillet every end edge with 0.495 T. usage: python3 autoround2.py <stl> <out.step> [t_frac]"""
import sys, time, random
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, loops, dedupe
from auto2d import section2d, loop_area, segment_loop, build_wire
import os, auto2d as _a2
_a2.LINE_TOL = _a2.ARC_TOL = float(os.environ.get('SEGTOL', '0.02'))  # coarser on rounded, noisier sections
from OCP.gp import gp_Pnt, gp_Vec
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Cone
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
t0 = time.time()
tri = load(sys.argv[1]); lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0); size = hi - lo
ax = int(np.argmin(size)); T = size[ax]; z0 = lo[ax]; rho = T / 2
tf = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25; t = tf * T
d = rho - np.sqrt(rho ** 2 - (rho - t) ** 2)
Ls = [dedupe(l) for l in loops(section2d(tri, ax, z0 + t)) if len(l) > 3]
Ls = [l for l in Ls if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]; Ls.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
print("axis %s T %.3f rho %.3f slice t %.3f inset d %.4f loops %d" % ("XYZ"[ax], T, rho, t, d, len(Ls)), flush=True)
wires = [build_wire(*segment_loop(l), ax, z0) for l in Ls]
mf = BRepBuilderAPI_MakeFace(wires[0], True)
for w in wires[1:]: mf.Add(w)
face = mf.Face(); sff = ShapeFix_Face(face); sff.FixOrientation(); sff.Perform(); face = sff.Face()
off = BRepOffsetAPI_MakeOffset(face, GeomAbs_Arc); off.Perform(d)
ws = []; ex = TopExp_Explorer(off.Shape(), TopAbs_WIRE)
while ex.More(): ws.append(TopoDS.Wire_s(ex.Current())); ex.Next()
print("offset wires %d" % len(ws), flush=True)
mf2 = BRepBuilderAPI_MakeFace(ws[0], True)
for w in ws[1:]: mf2.Add(w)
f2 = mf2.Face(); sff = ShapeFix_Face(f2); sff.FixOrientation(); sff.Perform(); f2 = sff.Face()
dv = [0.0, 0.0, 0.0]; dv[ax] = T
solid = BRepPrimAPI_MakePrism(f2, gp_Vec(*dv)).Shape()
fil = BRepFilletAPI_MakeFillet(solid); seen = TopTools_IndexedMapOfShape(); n = 0
ex = TopExp_Explorer(solid, TopAbs_FACE)
while ex.More():
    f = TopoDS.Face_s(ex.Current()); s = BRepAdaptor_Surface(f)
    if s.GetType() == GeomAbs_Plane:
        nd = s.Plane().Axis().Direction(); comp = [nd.X(), nd.Y(), nd.Z()][ax]
        if abs(abs(comp) - 1) < 1e-9:
            ee = TopExp_Explorer(f, TopAbs_EDGE)
            while ee.More():
                if not seen.Contains(ee.Current()):
                    seen.Add(ee.Current()); fil.Add(0.495 * T, TopoDS.Edge_s(ee.Current())); n += 1
                ee.Next()
    ex.Next()
fil.Build(); print("fillet %d edges done %s" % (n, fil.IsDone()), flush=True)
shape = fil.Shape() if fil.IsDone() else solid
census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More():
    ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
    census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
    ex.Next()
g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
print("model valid %s volume %.3f mesh %.3f delta %.3f%% faces %s [%.1fs]" % (BRepCheck_Analyzer(shape, True).IsValid(), g.Mass(), mvol, 100 * (g.Mass() - mvol) / mvol, census, time.time() - t0), flush=True)
b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More(): b.Add(comp, ex.Current()); ex.Next()
verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(8); dd = []
for i in random.sample(range(len(verts)), min(600, len(verts))):
    ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform(); dd.append(ds.Value())
dd = np.array(dd); print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
Interface_Static.SetCVal_s("write.step.schema", "AP214")
w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); ok = w.Write(sys.argv[2]) == IFSelect_RetDone
r = STEPControl_Reader(); r.ReadFile(sys.argv[2]); r.TransferRoots()
print("STEP %s; re-read valid %s" % (ok, BRepCheck_Analyzer(r.OneShape(), True).IsValid()), flush=True)
