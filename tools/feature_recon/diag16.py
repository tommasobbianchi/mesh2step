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
ax = int(np.argmin(size)); T = size[ax]; z0 = lo[ax]
# rho from the measured flat side band: perimeter is maximal and constant only across the band
hs_ = z0 + np.linspace(0.02, 0.98, 97) * T
per_ = np.array([sum(np.linalg.norm(b - a) for a, b in section2d(tri, ax, h)) for h in hs_])
band_ = hs_[per_ >= per_.max() * (1 - 1e-4)]
band_w = (band_.max() - band_.min()) + (hs_[1] - hs_[0]) if len(band_) else 0.0
rho = min(0.5 * (T - band_w), 0.49 * T)   # keep a real flat band so the fillet result stays a solid
print("flat band width %.3f -> rho %.3f" % (band_w, rho), flush=True)
tf = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25; t = tf * T
d = rho - np.sqrt(rho ** 2 - (rho - t) ** 2)
Ls = [dedupe(l) for l in loops(section2d(tri, ax, z0 + t)) if len(l) > 3]
Ls = [l for l in Ls if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]; Ls.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
print("axis %s T %.3f rho %.3f slice t %.3f inset d %.4f loops %d" % ("XYZ"[ax], T, rho, t, d, len(Ls)), flush=True)
# the full round belongs to the OUTER boundary only; holes keep straight walls, taken from the mid slice
outer_face = BRepBuilderAPI_MakeFace(build_wire(*segment_loop(Ls[0]), ax, z0), True).Face()
off = BRepOffsetAPI_MakeOffset(outer_face, GeomAbs_Arc); off.Perform(d)
Hm = [dedupe(l) for l in loops(section2d(tri, ax, z0 + T / 2)) if len(l) > 3]
Hm = [l for l in Hm if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]; Hm.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
holes2d = Hm[1:]
hole_wires = [build_wire(*segment_loop(l), ax, z0) for l in holes2d]
ws = []; ex = TopExp_Explorer(off.Shape(), TopAbs_WIRE)
while ex.More(): ws.append(TopoDS.Wire_s(ex.Current())); ex.Next()
print("offset wires %d" % len(ws), flush=True)
mf2 = BRepBuilderAPI_MakeFace(ws[0], True)
for w in hole_wires: mf2.Add(w)
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
                    seen.Add(ee.Current())
                    from OCP.BRepAdaptor import BRepAdaptor_Curve
                    c = BRepAdaptor_Curve(TopoDS.Edge_s(ee.Current())); pm = c.Value(0.5 * (c.FirstParameter() + c.LastParameter()))
                    p2 = np.array([[pm.X(), pm.Y(), pm.Z()][i] for i in range(3) if i != ax])
                    near_hole = any(np.min(np.linalg.norm(H - p2, axis=1)) < 0.5 for H in holes2d)
                    if not near_hole:
                        fil.Add(rho, TopoDS.Edge_s(ee.Current())); n += 1
                ee.Next()
    ex.Next()
fil.Build(); print("fillet %d edges done %s" % (n, fil.IsDone()), flush=True)
shape = fil.Shape() if fil.IsDone() else solid
# the fillet can come back as a closed shell (or a compound holding one); make it a solid again
from OCP.ShapeFix import ShapeFix_Solid, ShapeFix_Shape
from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
nsol = 0; exs = TopExp_Explorer(shape, TopAbs_SOLID)
while exs.More(): nsol += 1; exs.Next()
if nsol == 0:
    shl = TopExp_Explorer(shape, TopAbs_SHELL)
    if shl.More():
        sfs = ShapeFix_Solid(); shape = sfs.SolidFromShell(TopoDS.Shell_s(shl.Current()))
        sf = ShapeFix_Shape(shape); sf.Perform(); shape = sf.Shape()
        print("shell -> solid via ShapeFix_Solid.SolidFromShell", flush=True)

from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
import collections
def count(sh, t):
    n = 0; e = TopExp_Explorer(sh, t)
    while e.More(): n += 1; e.Next()
    return n
print("fillet result type %s solids %d shells %d faces %d valid %s" % (shape.ShapeType(), count(shape, TopAbs_SOLID), count(shape, TopAbs_SHELL), count(shape, TopAbs_FACE), BRepCheck_Analyzer(shape, True).IsValid()), flush=True)
an = BRepCheck_Analyzer(shape, True); stats = collections.Counter(); bad = []
e = TopExp_Explorer(shape, TopAbs_FACE); i = 0
while e.More():
    res = an.Result(e.Current())
    if res is not None:
        st = [str(x).split(".")[-1] for x in res.Status() if str(x).split(".")[-1] != "BRepCheck_NoError"]
        if st:
            ty = BRepAdaptor_Surface(TopoDS.Face_s(e.Current())).GetType()
            stats[(str(ty).split(".")[-1], tuple(st))] += 1; bad.append(i)
    i += 1; e.Next()
print("invalid faces by (surface, status):", dict(stats), flush=True)
# the solid built from the pre-fillet prism: is the prism itself valid?
print("prism type %s valid %s solids %d" % (solid.ShapeType(), BRepCheck_Analyzer(solid, True).IsValid(), count(solid, TopAbs_SOLID)), flush=True)
