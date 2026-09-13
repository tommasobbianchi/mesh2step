"""Multi-axis milled blocks (category E), feature route:
  base  = the outer outline of the mid section along a candidate axis, extruded over the full extent
          (no holes; every axis is tried, the smallest base volume that still contains the mesh wins)
  cuts  = feature-map patches that are not on the base surface:
          HOLE cylinders (any direction) -> cylinder cut over the patch span (extended past both ends)
          facing plane pairs -> slot box between the walls, bounded by a floor plane if one lies between them
          unpaired planes parallel to the base end faces, strictly inside the extent -> pocket/step floors:
            the patch's 2D footprint (bounding box in the section plane) is cut from the floor to the end face
            its normal points at
usage: python3 autoblock.py <stl> <out.step> [axis]"""
import sys, time, random, math, os
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, loops, dedupe
from auto2d import section2d, loop_area, segment_loop, build_wire
import auto2d as _a2
from features import patches
from OCP.gp import gp_Pnt, gp_Vec, gp_Dir, gp_Ax2, gp_Ax3, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeBox
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.ShapeFix import ShapeFix_Face
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
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

def vol(s):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); return g.Mass()

def frame_box(origin, xdir, zdir, x0, x1, y0, y1, z0, z1):
    """axis-aligned box in a local frame (X = xdir, Z = zdir, Y = Z x X), placed at origin"""
    fr = gp_Ax2(gp_Pnt(*origin), gp_Dir(*zdir), gp_Dir(*xdir))
    t = gp_Trsf(); t.SetTransformation(gp_Ax3(fr))
    b = BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()
    return BRepBuilderAPI_Transform(b, t.Inverted(), True).Shape()

t0 = time.time()
tri = load(sys.argv[1]); lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0)
diag = float(np.linalg.norm(hi - lo)); TOL = max(0.05, 2e-4 * diag)
_a2.LINE_TOL = _a2.ARC_TOL = max(0.02, 2e-4 * diag)
mvol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
cent = tri.mean(1); nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)

# 1. base: outer outline of the mid section along each axis, full extent
cands = []
axes = [int(sys.argv[3])] if len(sys.argv) > 3 else [0, 1, 2]
for ax in axes:
    Ls = [dedupe(l) for l in loops(section2d(tri, ax, 0.5 * (lo[ax] + hi[ax]))) if len(l) > 3]
    Ls = [l for l in Ls if abs(loop_area(np.r_[l, l[:1]])) > 1e-3]
    if not Ls: continue
    outer = max(Ls, key=lambda l: abs(loop_area(np.r_[l, l[:1]])))
    try:
        f = BRepBuilderAPI_MakeFace(build_wire(*segment_loop(outer), ax, lo[ax]), True).Face()
        sff = ShapeFix_Face(f); sff.FixOrientation(); sff.Perform(); f = sff.Face()
        d = [0.0, 0.0, 0.0]; d[ax] = hi[ax] - lo[ax]
        base = BRepPrimAPI_MakePrism(f, gp_Vec(*d)).Shape(); bv = vol(base)
    except Exception as e:
        print("axis %s base failed: %s" % ("XYZ"[ax], e)); continue
    print("axis %s base volume %.1f (mesh %.1f, excess %+.1f%%)" % ("XYZ"[ax], bv, mvol, 100 * (bv - mvol) / mvol), flush=True)
    if bv >= mvol * 0.995: cands.append((bv, ax, base, outer))
bv, ax, base, outer2d = min(cands, key=lambda c: c[0])
o = [i for i in range(3) if i != ax]
print("base axis %s" % "XYZ"[ax], flush=True)

# 2. triangles on the base surface: end faces (coordinate at lo/hi along axis, normal along axis) or side walls
#    (normal perpendicular to the axis and centroid on the outer outline in 2D)
from matplotlib.path import Path
outline = np.r_[outer2d, outer2d[:1]]
seg_a = outline[:-1]; seg_b = outline[1:]
def dist_to_outline(P):
    ab = seg_b - seg_a; L2 = np.maximum((ab ** 2).sum(1), 1e-18)
    best = np.full(len(P), np.inf)
    for k in range(0, len(seg_a), 512):
        A = seg_a[k:k + 512]; B = ab[k:k + 512]; l2 = L2[k:k + 512]
        t = np.clip(((P[:, None, :] - A[None]) * B[None]).sum(2) / l2[None], 0, 1)
        d = np.linalg.norm(P[:, None, :] - (A[None] + t[:, :, None] * B[None]), axis=2).min(1)
        best = np.minimum(best, d)
    return best
on_end = ((np.abs(cent[:, ax] - lo[ax]) < TOL) | (np.abs(cent[:, ax] - hi[ax]) < TOL)) & (np.abs(nrm[:, ax]) > 0.999)
side = np.abs(nrm[:, ax]) < 0.02
on_wall = np.zeros(len(tri), bool)
if side.any():
    on_wall[side] = dist_to_outline(cent[side][:, o]) < 3 * TOL
feat = ~(on_end | on_wall)
print("feature triangles %d of %d" % (feat.sum(), len(tri)), flush=True)
P = patches(tri, feat, TOL, min_share=0.005)
holes = [p for p in P if p["kind"] == "cylinder" and p["hole"]]
planes = [p for p in P if p["kind"] == "plane"]
print("patches: %d holes, %d planes, %d bosses, %d other" % (len(holes), len(planes), sum(1 for p in P if p["kind"] == "cylinder" and not p["hole"]), sum(1 for p in P if p["kind"] == "other")), flush=True)

shape = base; ext = diag
# 3a. holes
for h in holes:
    start = h["axis_pt"] + (h["tmin"] - TOL) * h["axis"]
    cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*start), gp_Dir(*h["axis"])), float(h["radius"]), float(h["tmax"] - h["tmin"] + 2 * TOL)).Shape()
    shape = BRepAlgoAPI_Cut(shape, cyl).Shape()
    print("  hole R %.3f axis %s span %.2f" % (h["radius"], np.round(h["axis"], 2).tolist(), h["tmax"] - h["tmin"]), flush=True)
# 3b. slots: facing plane pairs
paired = set()
for i, p in enumerate(planes):
    for j in range(i + 1, len(planes)):
        q = planes[j]
        if p["normal"] @ q["normal"] < -0.999 and -(q["offset"] + p["offset"]) > TOL:
            n = np.array(p["normal"]); Pp = np.vstack([p["points"], q["points"]])
            zz = np.zeros(3); zz[ax] = 1.0
            zz = zz - (zz @ n) * n
            if np.linalg.norm(zz) < 1e-6: zz = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0])
            zz /= np.linalg.norm(zz); yy = np.cross(zz, n)
            ly = Pp @ yy; lz = Pp @ zz; x0, x1 = p["offset"], -q["offset"]
            ylo, yhi = ly.min() - ext, ly.max() + ext
            for fl in planes:
                m = np.array(fl["normal"])
                if abs(abs(m @ yy) - 1) > 1e-3: continue
                fx = fl["points"] @ n
                if fx.min() < min(x0, x1) - TOL or fx.max() > max(x0, x1) + TOL: continue
                fy = float(np.median(fl["points"] @ yy))
                if m @ yy > 0: ylo = fy
                else: yhi = fy
                break
            shape = BRepAlgoAPI_Cut(shape, frame_box([0, 0, 0], n, zz, min(x0, x1), max(x0, x1), ylo, yhi, lz.min() - TOL, lz.max() + TOL)).Shape()
            paired.update((i, j))
            print("  slot width %.3f normal %s" % (abs(x1 - x0), np.round(n, 2).tolist()), flush=True)
# 3c. pocket / step floors parallel to the end faces
for i, p in enumerate(planes):
    if i in paired: continue
    n = np.array(p["normal"])
    if abs(abs(n[ax]) - 1) > 1e-3: continue
    lev = float(np.median(p["points"][:, ax]))
    if abs(lev - lo[ax]) < 2 * TOL or abs(lev - hi[ax]) < 2 * TOL: continue
    fp = p["points"][:, o]; u0, v0 = fp.min(0) - TOL; u1, v1 = fp.max(0) + TOL
    end = hi[ax] + TOL if n[ax] > 0 else lo[ax] - TOL
    bmin = [0.0, 0.0, 0.0]; bmax = [0.0, 0.0, 0.0]
    bmin[o[0]], bmin[o[1]], bmin[ax] = u0, v0, min(lev, end)
    bmax[o[0]], bmax[o[1]], bmax[ax] = u1, v1, max(lev, end)
    shape = BRepAlgoAPI_Cut(shape, BRepPrimAPI_MakeBox(gp_Pnt(*bmin), gp_Pnt(*bmax)).Shape()).Shape()
    print("  floor at %.3f (normal %+d) footprint %.1f x %.1f" % (lev, int(np.sign(n[ax])), u1 - u0, v1 - v0), flush=True)
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
verts = np.unique(tri.reshape(-1, 3).round(6), axis=0); random.seed(12); dd = []
for i in random.sample(range(len(verts)), min(500, len(verts))):
    ds = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*verts[i])).Vertex(), comp); ds.Perform()
    if ds.IsDone(): dd.append(ds.Value())
if dd:
    dd = np.array(dd); print("mesh->model faces: mean %.4f p95 %.4f max %.4f" % (dd.mean(), np.percentile(dd, 95), dd.max()), flush=True)
Interface_Static.SetCVal_s("write.step.schema", "AP214")
w = STEPControl_Writer(); w.Transfer(shape, STEPControl_AsIs); ok = w.Write(sys.argv[2]) == IFSelect_RetDone
rb = STEPControl_Reader(); rb.ReadFile(sys.argv[2]); rb.TransferRoots()
print("STEP %s; re-read valid %s" % (ok, BRepCheck_Analyzer(rb.OneShape(), True).IsValid()), flush=True)
