import sys, numpy as np
sys.path[:0] = ["/home/tommaso/projects/mesh2step/src"]
from mesh2step.feature import _mesh, _read
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS_Compound
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.gp import gp_Pnt

step = sys.argv[1]; stl = sys.argv[2]
sh = _read(step)
fm = TopTools_IndexedMapOfShape(); TopExp.MapShapes_s(sh, TopAbs_FACE, fm)
comp = TopoDS_Compound(); b = BRep_Builder(); b.MakeCompound(comp)
for i in range(1, fm.Extent()+1):
    b.Add(comp, fm.FindKey(i))
tri = _mesh(stl)
verts = np.unique(tri.reshape(-1,3), axis=0)
pick = verts[np.linspace(0, len(verts)-1, min(2000, len(verts))).astype(int)]
dd = []
for p in pick:
    v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float,p))).Vertex()
    ds = BRepExtrema_DistShapeShape(v, comp); ds.Perform()
    dd.append(ds.Value() if ds.IsDone() else 0.0)
dd = np.array(dd)
order = np.argsort(-dd)
print("worst 15 sampled vertices (dist to solid):")
for i in order[:15]:
    print(f"  {np.round(pick[i],3).tolist()}  dist={dd[i]:.4f}")
print(f"p95={np.percentile(dd,95):.4f}  p99={np.percentile(dd,99):.4f}  max={dd.max():.4f}  n={len(dd)}")
