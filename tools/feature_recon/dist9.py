"""Two-sided surface distance between the STL and a STEP model (distance to the model's FACES, not its solid).
usage: python3 dist9.py <stl> <step>"""
import sys, struct, random
import numpy as np
from OCP.STEPControl import STEPControl_Reader
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Pnt
r = STEPControl_Reader(); r.ReadFile(sys.argv[2]); r.TransferRoots(); shape = r.OneShape()
b = BRep_Builder(); comp = TopoDS_Compound(); b.MakeCompound(comp)
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More():
    b.Add(comp, ex.Current()); ex.Next()
data = open(sys.argv[1], "rb").read(); n = struct.unpack("<I", data[80:84])[0]
tri = np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))["v"].reshape(-1, 3, 3).astype(float)
verts = np.unique(tri.reshape(-1, 3).round(6), axis=0)
random.seed(2)
samp = [verts[i] for i in random.sample(range(len(verts)), 2000)] + [tri[i].mean(0) for i in random.sample(range(len(tri)), 1000)]
d = []
for p in samp:
    ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*p)).Vertex(), comp); ds.Perform(); d.append(ds.Value())
d = np.array(d)
print("mesh -> model faces (2000 vertices + 1000 triangle centroids): mean %.4f p95 %.4f p99 %.4f max %.4f" % (
    d.mean(), np.percentile(d, 95), np.percentile(d, 99), d.max()), flush=True)
worst = np.argsort(d)[-5:]
for i in worst:
    print("  worst mesh point (%.3f, %.3f, %.3f) dist %.4f" % (*samp[i], d[i]), flush=True)
# model -> mesh: tessellate the model, distance of its nodes to the nearest mesh triangle (exact point-triangle)
BRepMesh_IncrementalMesh(shape, 0.01, False, 0.1, True)
pts = []
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More():
    f = TopoDS.Face_s(ex.Current()); loc = TopLoc_Location(); T = BRep_Tool.Triangulation_s(f, loc)
    if T is not None:
        tr = loc.Transformation()
        for i in range(1, T.NbNodes() + 1):
            q = T.Node(i).Transformed(tr); pts.append((q.X(), q.Y(), q.Z()))
    ex.Next()
pts = np.array(pts); sel = pts[np.random.default_rng(3).choice(len(pts), min(3000, len(pts)), replace=False)]
cent = tri.mean(1)
def pt_tri(p, t):
    a, b_, c = t; ab, ac, ap = b_ - a, c - a, p - a
    d1, d2 = ab @ ap, ac @ ap
    if d1 <= 0 and d2 <= 0: return np.linalg.norm(ap)
    bp = p - b_; d3, d4 = ab @ bp, ac @ bp
    if d3 >= 0 and d4 <= d3: return np.linalg.norm(bp)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0: return np.linalg.norm(p - (a + ab * d1 / (d1 - d3)))
    cp = p - c; d5, d6 = ab @ cp, ac @ cp
    if d6 >= 0 and d5 <= d6: return np.linalg.norm(cp)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0: return np.linalg.norm(p - (a + ac * d2 / (d2 - d6)))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6)); return np.linalg.norm(p - (b_ + (c - b_) * w))
    den = 1.0 / (va + vb + vc); v = vb * den; w = vc * den
    return np.linalg.norm(p - (a + ab * v + ac * w))
d2 = []
for p in sel:
    near = np.argsort(((cent - p) ** 2).sum(1))[:24]
    d2.append(min(pt_tri(p, tri[k]) for k in near))
d2 = np.array(d2)
print("model -> mesh (%d model tessellation nodes): mean %.4f p95 %.4f p99 %.4f max %.4f" % (
    len(sel), d2.mean(), np.percentile(d2, 95), np.percentile(d2, 99), d2.max()), flush=True)
