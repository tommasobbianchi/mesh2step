"""Full-round outer edge built directly (no fillet algorithm):
  core  = prism of the outline inset by rho, full thickness T
  rims  = circle of radius rho swept along the inset outline at z0+rho and z0+T-rho
  band  = prism of the widest outline between z0+rho and z0+T-rho (the flat side band)
  solid = core U rims U band, minus straight holes (mid-slice loops).
Outline from a slice inside the round (t = 0.25T) offset outward by the analytic inset d(t).
usage: SEGTOL=0.12 python3 autoround6.py <stl> <out.step>"""
import sys, os, time, random
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, loops, dedupe
from auto2d import section2d, loop_area, segment_loop, build_wire
import auto2d as _a2
_a2.LINE_TOL = _a2.ARC_TOL = float(os.environ.get("SEGTOL", "0.12"))
from OCP.gp import gp_Pnt, gp_Vec, gp_Dir, gp_Ax2, gp_Circ
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Cone
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset, BRepOffsetAPI_MakePipe
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_CompCurve
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

def first_wire(shape):
    ex = TopExp_Explorer(shape, TopAbs_WIRE)
    return TopoDS.Wire_s(ex.Current())
def offset_wire(wire, dist):
    f = BRepBuilderAPI_MakeFace(wire, True).Face()
    off = BRepOffsetAPI_MakeOffset(f, GeomAbs_Arc); off.Perform(dist)
    return first_wire(off.Shape())
def translated(shape, dz, ax):
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    v = [0.0, 0.0, 0.0]; v[ax] = dz; t = gp_Trsf(); t.SetTranslation(gp_Vec(*v))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()
def prism_of(wires, h, ax):
    mf = BRepBuilderAPI_MakeFace(wires[0], True)
    for w in wires[1:]: mf.Add(w)
    f = mf.Face(); sff = ShapeFix_Face(f); sff.FixOrientation(); sff.Perform(); f = sff.Face()
    v = [0.0, 0.0, 0.0]; v[ax] = h
    return BRepPrimAPI_MakePrism(f, gp_Vec(*v)).Shape()

t0 = time.time()
tri = load(sys.argv[1]); lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0); size = hi - lo
ax = int(np.argmin(size)); T = size[ax]; z0 = lo[ax]
hs_ = z0 + np.linspace(0.02, 0.98, 97) * T
per_ = np.array([sum(np.linalg.norm(b - a) for a, b in section2d(tri, ax, h)) for h in hs_])
band_ = hs_[per_ >= per_.max() * (1 - 1e-4)]
band_w = (band_.max() - band_.min()) + (hs_[1] - hs_[0]) if len(band_) else 0.0
rho = min(0.5 * (T - band_w), 0.499 * T)
t = 0.25 * T; d = rho - np.sqrt(rho ** 2 - (rho - t) ** 2) if t < rho else 0.0
print("axis %s T %.3f band %.3f rho %.3f inset d(t=%.2f) %.4f" % ("XYZ"[ax], T, band_w, rho, t, d), flush=True)
Lq = [dedupe(l) for l in loops(section2d(tri, ax, z0 + t)) if len(l) > 3]
Lq = [l for l in Lq if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]; Lq.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
Lm = [dedupe(l) for l in loops(section2d(tri, ax, z0 + T / 2)) if len(l) > 3]
Lm = [l for l in Lm if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]; Lm.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
outer_q = build_wire(*segment_loop(Lq[0]), ax, z0)
wide = offset_wire(outer_q, d)            # widest outline (at the band)
inset = offset_wire(outer_q, d - rho)     # outline of the core / spine of the rims
holes = [build_wire(*segment_loop(l), ax, z0) for l in Lm[1:]]
core = prism_of([inset], T, ax)
band = translated(prism_of([wide], max(T - 2 * rho, 1e-3), ax), rho, ax)
# rim: circle of radius rho in the plane containing the spine tangent, swept along the inset outline
spine_lo = translated(inset, rho, ax); spine_hi = translated(inset, T - rho, ax)
ex = TopExp_Explorer(spine_lo, TopAbs_EDGE); e0 = TopoDS.Edge_s(ex.Current())
from OCP.BRepAdaptor import BRepAdaptor_Curve
c = BRepAdaptor_Curve(e0); p0 = gp_Pnt(); tan = gp_Vec(); c.D1(c.FirstParameter(), p0, tan)
prof = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(p0, gp_Dir(tan)), rho)).Edge()).Wire()
prof_face = BRepBuilderAPI_MakeFace(prof, True).Face()
rims = []
for spine in (spine_lo, spine_hi):
    pf = prof_face if spine is spine_lo else translated(prof_face, T - 2 * rho, ax)
    pipe = BRepOffsetAPI_MakePipe(TopoDS.Wire_s(spine), pf)
    pipe.Build(); rims.append(pipe.Shape())
print("pieces built: core, band, 2 rims [%.1fs]" % (time.time() - t0), flush=True)
shape = core
for s_ in [band] + rims:
    shape = BRepAlgoAPI_Fuse(shape, s_).Shape()
for hw in holes:
    shape = BRepAlgoAPI_Cut(shape, translated(prism_of([hw], T + 2.0, ax), -1.0, ax)).Shape()
u = ShapeUpgrade_UnifySameDomain(shape, True, True, False); u.Build(); shape = u.Shape()
def cnt(sh, tp):
    n = 0; e = TopExp_Explorer(sh, tp)
    while e.More(): n += 1; e.Next()
    return n
census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More():
    ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
    census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
    ex.Next()
g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
print("model solids %d valid %s volume %.3f mesh %.3f delta %.3f%% faces %s [%.1fs]" % (cnt(shape, TopAbs_SOLID), BRepCheck_Analyzer(shape, True).IsValid(), g.Mass(), mvol, 100 * (g.Mass() - mvol) / mvol, census, time.time() - t0), flush=True)
b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More(): b.Add(comp, ex.Current()); ex.Next()
verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(9); dd = []
for i in random.sample(range(len(verts)), min(600, len(verts))):
    ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform(); dd.append(ds.Value())
dd = np.array(dd); print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
Interface_Static.SetCVal_s("write.step.schema", "AP214")
w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); ok = w.Write(sys.argv[2]) == IFSelect_RetDone
r = STEPControl_Reader(); r.ReadFile(sys.argv[2]); r.TransferRoots(); back = r.OneShape()
print("STEP %s; re-read valid %s solids %d" % (ok, BRepCheck_Analyzer(back, True).IsValid(), cnt(back, TopAbs_SOLID)), flush=True)
