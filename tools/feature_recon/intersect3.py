"""Multi-axis blocks (category E): the part as the intersection of its stepped extrusions along X, Y and Z.
Each stepped extrusion carries the features that run along its axis (through holes, pockets, bosses as levels);
their common volume keeps every feature that is visible along some principal axis.
usage: python3 intersect3.py <stl> <stepX> <stepY> <stepZ> <out.step>"""
import sys, time, random
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load
from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Cone
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.gp import gp_Pnt
t0 = time.time()
tri = load(sys.argv[1]); mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
def rd(p):
    r = STEPControl_Reader(); r.ReadFile(p); r.TransferRoots(); return r.OneShape()
def vol(s):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); return g.Mass()
shapes = []
for p in sys.argv[2:5]:
    try:
        s = rd(p); shapes.append(s); print("  %s volume %.1f (mesh %.1f, %+.2f%%) valid %s" % (p.split("/")[-1], vol(s), mvol, 100 * (vol(s) - mvol) / mvol, BRepCheck_Analyzer(s, True).IsValid()), flush=True)
    except Exception as e:
        print("  %s unreadable: %s" % (p, e), flush=True)
shape = shapes[0]
for s in shapes[1:]:
    shape = BRepAlgoAPI_Common(shape, s).Shape()
u = ShapeUpgrade_UnifySameDomain(shape, True, True, False); u.Build(); shape = u.Shape()
census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}; ns = 0
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More():
    ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
    census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
    ex.Next()
ex = TopExp_Explorer(shape, TopAbs_SOLID)
while ex.More(): ns += 1; ex.Next()
print("model valid %s solids %d volume %.3f mesh %.3f delta %.3f%% faces %s [%.1fs]" % (BRepCheck_Analyzer(shape, True).IsValid(), ns, vol(shape), mvol, 100 * (vol(shape) - mvol) / mvol, census, time.time() - t0), flush=True)
b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More(): b.Add(comp, ex.Current()); ex.Next()
verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(11); dd = []
for i in random.sample(range(len(verts)), min(500, len(verts))):
    ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform()
    if ds.IsDone(): dd.append(ds.Value())
dd = np.array(dd); print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
Interface_Static.SetCVal_s("write.step.schema", "AP214")
w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); ok = w.Write(sys.argv[5]) == IFSelect_RetDone
rb = STEPControl_Reader(); rb.ReadFile(sys.argv[5]); rb.TransferRoots()
print("STEP %s; re-read valid %s" % (ok, BRepCheck_Analyzer(rb.OneShape(), True).IsValid()), flush=True)
