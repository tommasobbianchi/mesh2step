"""Why does a shape that is valid in memory come back invalid from STEP? Try write/read variants.
usage: python3 stepexp.py <shape.brep> <workdir>"""
import sys, os, collections
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.gp import gp_Trsf, gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

def census(sh):
    an = BRepCheck_Analyzer(sh, True); bad = collections.Counter(); ns = 0
    e = TopExp_Explorer(sh, TopAbs_SOLID)
    while e.More(): ns += 1; e.Next()
    e = TopExp_Explorer(sh, TopAbs_FACE)
    while e.More():
        r = an.Result(e.Current())
        if r is not None:
            for x in r.Status():
                n = str(x).split(".")[-1]
                if n != "BRepCheck_NoError": bad[n] += 1
        e.Next()
    return an.IsValid(), ns, dict(bad)

def roundtrip(sh, path, **opts):
    for k, v in opts.items():
        (Interface_Static.SetIVal_s if isinstance(v, int) else Interface_Static.SetCVal_s)(k, v)
    w = STEPControl_Writer(); w.Transfer(sh, STEPControl_AsIs); ok = w.Write(path) == IFSelect_RetDone
    r = STEPControl_Reader(); r.ReadFile(path); r.TransferRoots()
    return ok, census(r.OneShape())

sh = TopoDS_Shape(); BRepTools.Read_s(sh, sys.argv[1], BRep_Builder()); wd = sys.argv[2]
print("in memory (from BREP):", census(sh), flush=True)
b2 = os.path.join(wd, "rt.brep"); BRepTools.Write_s(sh, b2); s2 = TopoDS_Shape(); BRepTools.Read_s(s2, b2, BRep_Builder())
print("BREP round trip:", census(s2), flush=True)
print("STEP as-is:", roundtrip(sh, os.path.join(wd, "v0.step")), flush=True)
bb = Bnd_Box(); BRepBndLib.Add_s(sh, bb); x0, y0, z0, x1, y1, z1 = bb.Get()
t = gp_Trsf(); t.SetTranslation(gp_Vec(-x0, -y0, -z0)); shT = BRepBuilderAPI_Transform(sh, t, True).Shape()
print("translated to origin, in memory:", census(shT), flush=True)
print("STEP translated:", roundtrip(shT, os.path.join(wd, "v1.step")), flush=True)
print("STEP write.precision.mode=1 (max tol):", roundtrip(sh, os.path.join(wd, "v2.step"), **{"write.precision.mode": 1}), flush=True)
print("STEP write.surfacecurve.mode=0 (no pcurves):", roundtrip(sh, os.path.join(wd, "v3.step"), **{"write.precision.mode": 0, "write.surfacecurve.mode": 0}), flush=True)
