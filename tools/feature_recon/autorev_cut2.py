"""Turned parts, step 2: cut the non-turned features (flats, cross holes) out of the turned envelope.
1. spin axis + radial envelope r_out(z) exactly as autorev (outer loop centre, dense stations);
2. mesh triangles whose centroid lies clearly INSIDE the envelope (r < r_out(z) - tol) and whose normal is not
   radial are "cut surface" triangles;
3. cluster them: planar clusters (normals within 3 deg, coplanar within tol) -> flats; clusters whose normals are all
   perpendicular to one direction and fit a circle -> cross holes (cylinders);
4. flat cut = the envelope material on the outer side of the flat's plane, limited to the cluster's extent along the
   spin axis and across; hole cut = cylinder of the fitted radius along its axis through the part;
5. envelope minus cuts; validate like auto2d; STEP.
usage: python3 autorev_cut.py <stl> <envelope.step> <out.step>"""
import sys, time, random, math, collections
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, fit_circle, loops, dedupe
from auto2d import section2d
from OCP.gp import gp_Pnt, gp_Vec, gp_Dir, gp_Ax2, gp_Ax3, gp_Pln, gp_Trsf
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_MakeVertex
from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Torus, GeomAbs_Cone
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

t0 = time.time()
tri = load(sys.argv[1]); lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0)
diag = float(np.linalg.norm(hi - lo)); TOL = max(0.05, 2e-4 * diag)
# 1. axis + centre (outer loop fits), as autorev
best = None
for ax in range(3):
    cs = []
    for f in np.linspace(0.1, 0.9, 9):
        segs = section2d(tri, ax, lo[ax] + f * (hi[ax] - lo[ax]))
        Ls = [dedupe(l) for l in loops(segs) if len(l) > 3] if len(segs) >= 8 else []
        if not Ls: continue
        P = max(Ls, key=lambda L: abs(0.5 * np.sum(L[:-1, 0] * L[1:, 1] - L[1:, 0] * L[:-1, 1])))
        c, r, dev = fit_circle(P); cs.append((c, r))
    if len(cs) < 5: continue
    C = np.array([c for c, r in cs]); score = np.median(np.linalg.norm(C - np.median(C, 0), axis=1)) / max(np.median([r for c, r in cs]), 1e-9)
    if best is None or score < best[0]: best = (score, ax, np.median(C, 0))
_, ax, cen = best; o = [i for i in range(3) if i != ax]
env = TopoDS_Compound()
r_ = STEPControl_Reader(); r_.ReadFile(sys.argv[2]); r_.TransferRoots(); env = r_.OneShape()
# envelope radius per station from the mesh itself (max radius of the section)
zs = np.linspace(lo[ax], hi[ax], 801)
rmax = []
for z in zs[1:-1]:
    segs = section2d(tri, ax, z)
    rmax.append(np.max(np.linalg.norm(np.array([p for s in segs for p in s]) - cen, axis=1)) if segs else 0.0)
rmax = np.array([rmax[0]] + rmax + [rmax[-1]])
# 2. cut-surface triangles
cent = tri.mean(1); nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); area = np.linalg.norm(nrm, axis=1) / 2
nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
rc = np.linalg.norm(cent[:, o] - cen, axis=1); env_r = np.interp(cent[:, ax], zs, rmax)
radial = np.zeros_like(cent); radial[:, o] = (cent[:, o] - cen) / np.maximum(rc[:, None], 1e-9)
axial_n = np.abs(nrm[:, ax]); radial_n = np.abs(np.einsum("ij,ij->i", nrm, radial))
inside = rc < env_r - TOL
# turned surfaces have radial normals (cylinders/cones) or axial normals (shoulders); cuts have neither
cand = inside & (radial_n < 0.995) & (axial_n < 0.995)
print("axis %s centre (%.3f, %.3f) tol %.3f; cut-surface triangles %d of %d (area %.1f)" % (
    "XYZ"[ax], cen[0], cen[1], TOL, cand.sum(), len(tri), area[cand].sum()), flush=True)
idx = np.where(cand)[0]
# 3a. planar clusters: group by quantised normal + plane offset
used = np.zeros(len(tri), bool); flats = []
keyn = np.round(nrm[idx] * 60).astype(int)
groups = collections.defaultdict(list)
for i, k in zip(idx, map(tuple, keyn)): groups[k].append(i)
for k, g in groups.items():
    g = np.array(g); n = nrm[g].mean(0); n /= np.linalg.norm(n)
    d = cent[g] @ n
    for dv in np.unique(np.round(d / (2 * TOL))):
        sel = g[np.abs(np.round(d / (2 * TOL)) - dv) < 0.5]
        # a real flat is a sizeable cluster; 2-triangle groups are facets of a coarsely tessellated turned surface
        if len(sel) < 10 or area[sel].sum() < 0.01 * area[idx].sum(): continue
        flats.append((n, float(np.median(cent[sel] @ n)), sel)); used[sel] = True
print("flat candidates %d: %s" % (len(flats), [(np.round(f[0], 2).tolist(), round(f[1], 2), len(f[2])) for f in flats[:8]]), flush=True)
# 3b. holes from the feature map: connected patches of NON-envelope triangles fitted as cylinders (half-patches merged)
from features import patches
on_env = (np.abs(rc - env_r) <= TOL * 2) | ((radial_n > 0.995) & (np.abs(rc - env_r) <= TOL * 20)) | (axial_n > 0.995)
holes = []
for pt in patches(tri, ~on_env, TOL):
    if pt["kind"] == "cylinder" and pt["hole"]:
        start = pt["axis_pt"] + pt["tmin"] * pt["axis"]
        # an axial bore (axis parallel to the spin axis through the centre) is already in the envelope profile
        spin = np.zeros(3); spin[ax] = 1.0
        off = pt["axis_pt"] - (pt["axis_pt"] @ spin) * spin; cen3 = np.zeros(3); cen3[o] = cen
        if abs(abs(pt["axis"] @ spin) - 1) < 1e-3 and np.linalg.norm(off - cen3) < 2 * TOL:
            continue
        holes.append((pt["axis"], start, pt["radius"], pt["tmax"] - pt["tmin"]))
print("hole candidates %d: %s" % (len(holes), [(np.round(h[0], 2).tolist(), round(h[2], 3), round(h[3], 2)) for h in holes]), flush=True)
# 4. cuts
shape = env
Rmax = float(rmax.max()) * 1.05 + 1.0
for n, dplane, sel in flats:
    # keep material on the inner side (towards the axis) of the flat; remove a box outside the plane, limited along axis
    zmin, zmax = cent[sel][:, ax].min() - TOL, cent[sel][:, ax].max() + TOL
    # local frame: X = normal, Z = spin axis
    zdir = [0.0, 0.0, 0.0]; zdir[ax] = 1.0
    xd = np.array(n) - np.dot(n, zdir) * np.array(zdir); xd /= np.linalg.norm(xd)
    origin = cent[sel].mean(0); origin = origin + (dplane - origin @ n) * np.array(n)
    frame = gp_Ax2(gp_Pnt(*origin), gp_Dir(*zdir), gp_Dir(*xd))
    box = BRepPrimAPI_MakeBox(gp_Ax2(gp_Pnt(*(origin)), gp_Dir(*zdir), gp_Dir(*xd)), 1.0, 1.0, 1.0)
    # box spans x in [0, 2R] (outside the plane), y in [-2R, 2R], z in [zmin, zmax] relative to origin along axis
    t = gp_Trsf(); t.SetTransformation(gp_Ax3(frame))
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox as MB
    oz = origin[ax]
    b = MB(gp_Pnt(0, -2 * Rmax, zmin - oz), gp_Pnt(2 * Rmax, 2 * Rmax, zmax - oz)).Shape()
    b = BRepBuilderAPI_Transform(b, t.Inverted(), True).Shape()
    shape = BRepAlgoAPI_Cut(shape, b).Shape()
for hdir, start, rr, length in holes:
    cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*(start - hdir * TOL)), gp_Dir(*hdir)), float(rr), float(length + 2 * TOL)).Shape()
    shape = BRepAlgoAPI_Cut(shape, cyl).Shape()
u_ = ShapeUpgrade_UnifySameDomain(shape, True, True, False); u_.Build(); shape = u_.Shape()
census = {"plane": 0, "cylinder": 0, "torus": 0, "cone": 0, "other": 0}
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More():
    ty = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()
    census["plane" if ty == GeomAbs_Plane else "cylinder" if ty == GeomAbs_Cylinder else "torus" if ty == GeomAbs_Torus else "cone" if ty == GeomAbs_Cone else "other"] += 1
    ex.Next()
g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
print("model valid %s volume %.3f mesh %.3f delta %.3f%% faces %s [%.1fs]" % (BRepCheck_Analyzer(shape, True).IsValid(), g.Mass(), mvol, 100 * (g.Mass() - mvol) / mvol, census, time.time() - t0), flush=True)
b_ = BRep_Builder(); comp = TopoDS_Compound(); b_.MakeCompound(comp)
ex = TopExp_Explorer(shape, TopAbs_FACE)
while ex.More(): b_.Add(comp, ex.Current()); ex.Next()
verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(10); dd = []
for i in random.sample(range(len(verts)), min(500, len(verts))):
    ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform()
    if ds.IsDone(): dd.append(ds.Value())
dd = np.array(dd); print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
Interface_Static.SetCVal_s("write.step.schema", "AP214")
w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); ok = w.Write(sys.argv[3]) == IFSelect_RetDone
rb = STEPControl_Reader(); rb.ReadFile(sys.argv[3]); rb.TransferRoots()
print("STEP %s; re-read valid %s" % (ok, BRepCheck_Analyzer(rb.OneShape(), True).IsValid()), flush=True)
