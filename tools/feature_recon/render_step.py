"""Render a STEP model (tessellated) in iso view, faces coloured by surface type. usage: render_step.py <step> <png> [title]"""
import sys, numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from OCP.STEPControl import STEPControl_Reader
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus
r = STEPControl_Reader(); r.ReadFile(sys.argv[1]); r.TransferRoots(); s = r.OneShape()
BRepMesh_IncrementalMesh(s, 0.05, False, 0.2, True)
col = {GeomAbs_Plane: (0.75, 0.78, 0.85), GeomAbs_Cylinder: (0.95, 0.55, 0.25), GeomAbs_Torus: (0.35, 0.7, 0.4)}
polys, cols = [], []
ex = TopExp_Explorer(s, TopAbs_FACE)
while ex.More():
    f = TopoDS.Face_s(ex.Current()); loc = TopLoc_Location(); T = BRep_Tool.Triangulation_s(f, loc)
    c = col.get(BRepAdaptor_Surface(f).GetType(), (0.6, 0.3, 0.7))
    if T is not None:
        tr = loc.Transformation()
        P = np.array([[T.Node(i).Transformed(tr).X(), T.Node(i).Transformed(tr).Y(), T.Node(i).Transformed(tr).Z()] for i in range(1, T.NbNodes() + 1)])
        for i in range(1, T.NbTriangles() + 1):
            a, b, d = T.Triangle(i).Get(); tri = P[[a - 1, b - 1, d - 1]]
            n = np.cross(tri[1] - tri[0], tri[2] - tri[0]); n /= (np.linalg.norm(n) + 1e-12)
            sh = 0.35 + 0.65 * abs(n @ np.array([0.4, -0.5, 0.77]))
            polys.append(tri); cols.append(tuple(min(1, x * sh) for x in c))
    ex.Next()
polys = np.array(polys); lo = polys.reshape(-1, 3).min(0); hi = polys.reshape(-1, 3).max(0)
fig = plt.figure(figsize=(10, 10)); ax = fig.add_subplot(111, projection="3d")
ax.add_collection3d(Poly3DCollection(polys, facecolors=cols, edgecolors="none"))
c = (lo + hi) / 2; rr = (hi - lo).max() / 2
ax.set_xlim(c[0] - rr, c[0] + rr); ax.set_ylim(c[1] - rr, c[1] + rr); ax.set_zlim(c[2] - rr, c[2] + rr)
ax.view_init(30, -60); ax.set_box_aspect((1, 1, 1))
ax.set_title((sys.argv[3] if len(sys.argv) > 3 else sys.argv[1]) + "  (orange = cylinder, green = torus/fillet, grey = plane)")
fig.savefig(sys.argv[2], dpi=80, bbox_inches="tight"); print("wrote", sys.argv[2])
