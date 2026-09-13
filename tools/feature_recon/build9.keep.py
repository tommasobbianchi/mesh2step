"""Feature-level reconstruction of mechparts/9 (splined ring) from the measured slice parameters.
usage: python3 build9.py <stl> <out.step>"""
import sys, math, random, time, struct
import numpy as np
from OCP.gp import gp_Pnt, gp_Vec, gp_Ax1, gp_Ax2, gp_Dir, gp_Trsf
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeBox
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_MakeVertex
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopExp import TopExp_Explorer, TopExp
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.Interface import Interface_Static

# measured (sem/slice9.out, sem/profile9.out); every value is a mesh measurement, not a guess
CX, CY, H = 3066.215, 2090.868, 20.0
R_BORE, R_ROOT = 37.338, 51.556
TOOTH_HALF, TOOTH_TOP, N_TEETH, TOOTH_PHASE_DEG = 8.89, 57.15, 10, 0.0
KEY_HALF, KEY_BOTTOM, KEY_DIR_DEG = 8.89, 40.38, 90.0
FILLET = 2.0

def rot(shape, deg):
    t = gp_Trsf(); t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), math.radians(deg))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()

t0 = time.time()
body = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), R_ROOT, H).Shape()
for k in range(N_TEETH):
    # tooth: rectangle from inside the root circle out to the flat top, full height
    tooth = BRepPrimAPI_MakeBox(gp_Pnt(R_ROOT - 3.0, -TOOTH_HALF, 0), gp_Pnt(TOOTH_TOP, TOOTH_HALF, H)).Shape()
    body = BRepAlgoAPI_Fuse(body, rot(tooth, TOOTH_PHASE_DEG + k * 360.0 / N_TEETH)).Shape()
bore = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -1), gp_Dir(0, 0, 1)), R_BORE, H + 2).Shape()
key = rot(BRepPrimAPI_MakeBox(gp_Pnt(R_BORE - 3.0, -KEY_HALF, -1), gp_Pnt(KEY_BOTTOM, KEY_HALF, H + 1)).Shape(), KEY_DIR_DEG)
body = BRepAlgoAPI_Cut(body, BRepAlgoAPI_Fuse(bore, key).Shape()).Shape()
u = ShapeUpgrade_UnifySameDomain(body, True, True, False); u.Build(); body = u.Shape()

# fillet every edge of the top and bottom planar faces
fil = BRepFilletAPI_MakeFillet(body); em = TopTools_IndexedMapOfShape(); n_edges = 0
ex = TopExp_Explorer(body, TopAbs_FACE)
while ex.More():
    f = TopoDS.Face_s(ex.Current()); s = BRepAdaptor_Surface(f)
    if s.GetType() == GeomAbs_Plane and abs(abs(s.Plane().Axis().Direction().Z()) - 1) < 1e-9:
        ee = TopExp_Explorer(f, TopAbs_EDGE)
        while ee.More():
            if not em.Contains(ee.Current()):
                em.Add(ee.Current()); fil.Add(FILLET, TopoDS.Edge_s(ee.Current())); n_edges += 1
            ee.Next()
    ex.Next()
fil.Build()
print("fillet edges %d done %s" % (n_edges, fil.IsDone()), flush=True)
solid = fil.Shape() if fil.IsDone() else body
t = gp_Trsf(); t.SetTranslation(gp_Vec(CX, CY, 0)); solid = BRepBuilderAPI_Transform(solid, t, True).Shape()

def census(s):
    c = {"plane": 0, "cylinder": 0, "torus": 0, "other": 0}
    ex = TopExp_Explorer(s, TopAbs_FACE)
    while ex.More():
        ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
        c["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "other"] += 1
        ex.Next()
    return c
g = GProp_GProps(); BRepGProp.VolumeProperties_s(solid, g)
print("model valid %s volume %.3f faces %s  [%.1fs]" % (BRepCheck_Analyzer(solid, True).IsValid(), g.Mass(), census(solid), time.time() - t0), flush=True)

# mesh volume and vertex distances
data = open(sys.argv[1], "rb").read(); n = struct.unpack("<I", data[80:84])[0]
tri = np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))["v"].reshape(-1, 3, 3).astype(float)
mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
print("mesh volume %.3f  delta %.3f%%" % (mvol, 100 * (g.Mass() - mvol) / mvol), flush=True)
verts = np.unique(tri.reshape(-1, 3).round(6), axis=0)
random.seed(1); idx = random.sample(range(len(verts)), min(1500, len(verts)))
d = []
for i in idx:
    p = verts[i]; ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*p)).Vertex(), solid)
    ds.Perform(); d.append(ds.Value())
d = np.array(d)
print("mesh-vertex -> model surface distance over %d samples: mean %.4f p95 %.4f max %.4f  (vertices inside the solid read 0)" % (
    len(d), d.mean(), np.percentile(d, 95), d.max()), flush=True)

Interface_Static.SetCVal_s("write.step.schema", "AP214")
w = STEPControl_Writer(); w.Transfer(solid, STEPControl_AsIs); ok = w.Write(sys.argv[2]) == IFSelect_RetDone
r = STEPControl_Reader(); rs = r.ReadFile(sys.argv[2]); r.TransferRoots(); back = r.OneShape()
g2 = GProp_GProps(); BRepGProp.VolumeProperties_s(back, g2)
print("STEP written %s; re-read valid %s volume %.3f faces %s" % (ok, BRepCheck_Analyzer(back, True).IsValid(), g2.Mass(), census(back)), flush=True)
