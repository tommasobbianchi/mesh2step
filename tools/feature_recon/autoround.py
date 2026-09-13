"""Plates whose side edges are full rounds (or rounds with a flat band).
Measure: the section perimeter along the thickness axis is constant only over the flat band [a, b];
rho = (T - (b - a)) / 2. Build: inset the widest (mid) profile by rho, extrude it over the flat band
(height T - 2 rho, a tiny minimum when the band is empty), then offset the solid by rho with arc joins,
which adds radius-rho rounds on every edge of the core. Validate like auto2d.
usage: python3 autoround.py <stl> <out.step>"""
import sys, time, random
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, loops, dedupe
from auto2d import section2d, loop_area, segment_loop, build_wire
from OCP.gp import gp_Pnt, gp_Vec
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Cone
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset, BRepOffsetAPI_MakeOffsetShape
from OCP.BRepOffset import BRepOffset_Skin
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.ShapeFix import ShapeFix_Face
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

def main():
    t0 = time.time()
    tri = load(sys.argv[1]); lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0); size = hi - lo
    ax = int(np.argmin(size)); T = size[ax]; z0 = lo[ax]
    hs = z0 + np.linspace(0.02, 0.98, 49) * T
    per = np.array([sum(np.linalg.norm(b - a) for a, b in section2d(tri, ax, h)) for h in hs])
    pmax = per.max(); flat = hs[per >= pmax * (1 - 2e-4)]
    band = (flat.min(), flat.max()) if len(flat) else (z0 + T / 2, z0 + T / 2)
    rho = max((T - (band[1] - band[0])) / 2, 0.0)
    # refine the band edges to the sampling step: with a full round the band is a single sample
    step = hs[1] - hs[0]
    if band[1] - band[0] <= step: rho = T / 2
    print("thickness axis %s T %.3f flat band %.3f..%.3f -> rho %.3f" % ("XYZ"[ax], T, band[0], band[1], rho), flush=True)
    hm = z0 + T / 2
    Ls = [dedupe(l) for l in loops(section2d(tri, ax, hm)) if len(l) > 3]
    Ls = [l for l in Ls if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]
    Ls.sort(key=lambda l: -abs(loop_area(np.r_[l, l[:1]])))
    wires = [build_wire(*segment_loop(l), ax, z0 + rho) for l in Ls]
    mf = BRepBuilderAPI_MakeFace(wires[0], True)
    for w in wires[1:]: mf.Add(w)
    face = mf.Face(); sff = ShapeFix_Face(face); sff.FixOrientation(); sff.Perform(); face = sff.Face()
    # inset the whole profile (outer shrinks, holes grow) by rho
    off = BRepOffsetAPI_MakeOffset(face, GeomAbs_Arc); off.Perform(-rho)
    ws = []
    ex = TopExp_Explorer(off.Shape(), TopAbs_WIRE)
    while ex.More():
        ws.append(TopoDS.Wire_s(ex.Current())); ex.Next()
    print("inset wires %d (from %d loops)" % (len(ws), len(Ls)), flush=True)
    mf2 = BRepBuilderAPI_MakeFace(ws[0], True)
    for w in ws[1:]: mf2.Add(w)
    core_face = mf2.Face(); sff = ShapeFix_Face(core_face); sff.FixOrientation(); sff.Perform(); core_face = sff.Face()
    h0 = max(T - 2 * rho, 1e-3)
    d = [0.0, 0.0, 0.0]; d[ax] = h0
    core = BRepPrimAPI_MakePrism(core_face, gp_Vec(*d)).Shape()
    mk = BRepOffsetAPI_MakeOffsetShape()
    mk.PerformByJoin(core, rho * (1 - 1e-6), 1e-5, BRepOffset_Skin, False, False, GeomAbs_Arc)
    shape = mk.Shape()
    census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
        census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
        ex.Next()
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
    mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    print("model valid %s volume %.3f mesh %.3f delta %.3f%% faces %s  [%.1fs]" % (
        BRepCheck_Analyzer(shape, True).IsValid(), g.Mass(), mvol, 100 * (g.Mass() - mvol) / mvol, census, time.time() - t0), flush=True)
    b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        b.Add(comp, ex.Current()); ex.Next()
    verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(7); dd = []
    for i in random.sample(range(len(verts)), min(600, len(verts))):
        ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform(); dd.append(ds.Value())
    dd = np.array(dd)
    print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); ok = w.Write(sys.argv[2]) == IFSelect_RetDone
    r = STEPControl_Reader(); r.ReadFile(sys.argv[2]); r.TransferRoots()
    print("STEP %s; re-read valid %s" % (ok, BRepCheck_Analyzer(r.OneShape(), True).IsValid()), flush=True)

if __name__ == "__main__":
    main()
