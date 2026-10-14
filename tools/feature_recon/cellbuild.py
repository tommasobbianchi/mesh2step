"""cellbuild: a SCANNED mesh + per-triangle surface labels -> a B-rep solid whose edges and corners come from the
surfaces, not from the mesh (bd projects-vgj7.1, owner 2026-10-13: "build the separate part for scan").

edgebuild derives a B-rep's topology from the labelled triangles (corner = a vertex touching 3 labels, edge = a run
of label boundary) and then asks the fitted surfaces to meet there. On a scan that topology is ragged or absent:
with PERFECT labels and EXACT CAD surfaces it built 8 of 30 scanbench parts (2026-10-13), the rest failing on corners
no point satisfies (parallel faces closer than a scan triangle, sub-resolution holes, fit noise).

Here the surfaces decide. Each labelled region gives one analytic surface (the parameters the user accepted, else a
fit), extended past its region; BOPAlgo_MakerVolume splits space into the closed cells those surfaces bound; a cell
belongs to the part when sample points inside it lie inside the scan. The solid is the union of those cells, with the
faces of one surface split by the arrangement merged back (ShapeUpgrade_UnifySameDomain). Corners are surface
intersections, so they always exist; a feature the scan does not resolve drops out instead of failing the build.

usage: cellbuild.py in.stl out.step --labels labels.json     (labels: {"label": [per triangle], "kinds": {id: kind},
       "params": {id: surface parameters}} as mesh2step.guide.labels writes them). Prints "RESULT {...}" or "FAIL ...".
"""

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_TRIS = 6      # a smaller region is below what a scan can fit; its triangles go to the neighbours' cells
EXT = 0.15        # each surface is extended this fraction of the diagonal past its region's box
SAMPLES = 12      # interior points per cell for the inside/outside vote


def fail(msg):
    print("FAIL " + msg, flush=True)
    sys.exit(3)


def resid(kind, p, P):
    """rms distance of the points P to the surface."""
    if kind == "plane":
        d = (P - p["point"]) @ np.asarray(p["normal"], float)
    elif kind == "sphere":
        d = np.linalg.norm(P - p["center"], axis=1) - p["radius"]
    else:
        o = p.get("point", p.get("center", p.get("apex")))
        a = np.asarray(p["axis"], float) / np.linalg.norm(p["axis"])
        q = P - o
        h = q @ a
        rho = np.linalg.norm(q - np.outer(h, a), axis=1)
        if kind == "cylinder":
            d = rho - p["radius"]
        elif kind == "cone":
            t = math.radians(p["angle"]) if "angle" in p else float(p["half_angle"])
            d = rho * math.cos(t) - np.abs(h) * math.sin(t)
        else:
            d = np.hypot(h, rho - p["major"]) - p["minor"]
    return float(np.sqrt(np.mean(d ** 2)))


def surfaces(mesh, label, kinds, params, fill=()):
    """-> [(kind, params, triangle indices)], one per labelled region of >= MIN_TRIS triangles.
    fill: regions nobody looked at (the build labels what the user left unselected from scanransac.detect). Their
    curved kind must earn its place: kept only when it fits clearly better than a plane, else the region is a plane.
    (scanbench 2026-10-13: 88 of 282 curved fill regions had the wrong kind, mostly spheres; 14 overlapping false
    spheres on one part made the cell arrangement exhaust 50 GB.)"""
    from scanprep import _noise
    from scanransac import fit

    noise = None
    out = []
    diag = float(np.linalg.norm(mesh.extents))
    for k, kind in kinds.items():
        ts = np.flatnonzero(label == int(k))
        if len(ts) < MIN_TRIS:
            continue
        P = mesh.vertices[np.unique(mesh.faces[ts])]
        c = P.mean(0)
        plane = ("plane", {"normal": np.linalg.svd(P - c)[2][-1], "point": c}, ts, k)
        if kind == "plane":   # a plane is always observable from its triangles: fit it, whatever was passed ...
            ex = params.get(k) or {}
            if ex.get("exact"):   # ... unless the user fixed it exactly (a gauge, bd projects-vgj7.4)
                plane = ("plane", {"normal": np.asarray(ex["normal"], float), "point": np.asarray(ex["point"], float),
                                   "exact": True}, ts, k)
            out.append(plane)
            continue
        p = params.get(k)
        if p is None:
            noise = _noise(mesh.vertices, mesh.faces) if noise is None else noise
            try:
                p = fit(mesh, ts, kind, noise=noise)
            except Exception:  # noqa: BLE001 - an unfittable region contributes no surface
                continue
        if k in fill:
            size = p.get("radius", p.get("major", 0.0))
            if not (resid(kind, p, P) < 0.5 * resid(*plane[:2], P) and size < diag):
                out.append(plane)
                continue
        out.append((kind, p, ts, k))
    # the user's surfaces take precedence: a fill region one of them already fits about as well as its own surface
    # does is part of that face, not a face of its own (scanbench 132345: fill "spheres" R 11.2 on the triangles of
    # the user's R 11.2 holes overrode the cylinders in the arrangement)
    user = [s for s in out if s[0] != "plane" and str(s[3]) not in fill]
    keep = []
    for s in out:
        if str(s[3]) in fill and user:
            P = mesh.vertices[np.unique(mesh.faces[s[2]])]
            own = resid(s[0], s[1], P)
            if min(resid(u[0], u[1], P) for u in user) <= 1.5 * own + 1e-4 * diag:
                continue
        keep.append(s)
    return [s[:3] for s in keep]


def _same(a, b, tol):
    """Two surfaces that are one face of the part (one face split over two labels): merged, or the arrangement makes
    sliver cells between them."""
    (ka, pa, _), (kb, pb, _) = a, b
    if ka != kb:
        return False
    cos = math.cos(math.radians(3))
    if ka == "plane":
        na, nb = np.asarray(pa["normal"]), np.asarray(pb["normal"])
        return abs(na @ nb) > cos and abs((np.asarray(pb["point"]) - np.asarray(pa["point"])) @ na) < tol
    if ka in ("sphere",):
        return (np.linalg.norm(np.subtract(pa["center"], pb["center"])) < tol
                and abs(pa["radius"] - pb["radius"]) < tol)
    aa, ab = np.asarray(pa["axis"], float), np.asarray(pb["axis"], float)
    if abs(aa @ ab) < cos:
        return False
    if ka == "cylinder":
        d = np.subtract(pb["point"], pa["point"])
        return np.linalg.norm(d - (d @ aa) * aa) < tol and abs(pa["radius"] - pb["radius"]) < tol
    if ka == "cone":
        return np.linalg.norm(np.subtract(pa["apex"], pb["apex"])) < tol and abs(pa["angle"] - pb["angle"]) < 1.0
    return (np.linalg.norm(np.subtract(pa["center"], pb["center"])) < tol
            and abs(pa["major"] - pb["major"]) < tol and abs(pa["minor"] - pb["minor"]) < tol)


def dedupe(surfs, tol):
    keep = []
    # the larger region's surface stands; an exact (gauge) plane stands over any fitted one
    for s in sorted(surfs, key=lambda s: (not s[1].get("exact", False), -len(s[2]))):
        for i, k in enumerate(keep):
            if _same(k, s, tol):
                keep[i] = (k[0], k[1], np.r_[k[2], s[2]])
                break
        else:
            keep.append(s)
    return keep


def occ_face(kind, p, lo, hi, tol):
    """The surface as a face spanning the box [lo, hi] (its region's box grown by EXT)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.Geom import Geom_ConicalSurface, Geom_CylindricalSurface, Geom_SphericalSurface, Geom_ToroidalSurface
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt

    pnt = lambda x: gp_Pnt(*map(float, x))  # noqa: E731
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    if kind == "plane":
        n = np.asarray(p["normal"], float)
        c = 0.5 * (lo + hi)
        o = c - ((c - p["point"]) @ n) * n
        h = float(np.linalg.norm(hi - lo))
        return BRepBuilderAPI_MakeFace(gp_Pln(pnt(o), gp_Dir(*map(float, n))), -h, h, -h, h).Face()
    if kind == "sphere":
        return BRepBuilderAPI_MakeFace(Geom_SphericalSurface(gp_Ax3(pnt(p["center"]), gp_Dir(0, 0, 1)),
                                                             float(p["radius"])), tol).Face()
    a = np.asarray(p["axis"], float)
    a = a / np.linalg.norm(a)
    if kind == "torus":
        return BRepBuilderAPI_MakeFace(Geom_ToroidalSurface(gp_Ax3(pnt(p["center"]), gp_Dir(*map(float, a))),
                                                            float(p["major"]), float(p["minor"])), tol).Face()
    if kind == "cylinder":
        h = (corners - p["point"]) @ a
        return BRepBuilderAPI_MakeFace(Geom_CylindricalSurface(gp_Ax3(pnt(p["point"]), gp_Dir(*map(float, a))),
                                                               float(p["radius"])),
                                       0.0, 2 * math.pi, float(h.min()), float(h.max()), tol).Face()
    # cone, OCC form with reference radius 0 at the apex: P(u, v) = apex + v sin(t) radial + v cos(t) axis
    t = math.radians(p["angle"]) if "angle" in p else float(p["half_angle"])
    h = (corners - p["apex"]) @ a
    if h.max() <= 0:
        a, h = -a, -h
    v0, v1 = max(float(h.min()), 1e-3 * float(np.linalg.norm(hi - lo))) / math.cos(t), float(h.max()) / math.cos(t)
    return BRepBuilderAPI_MakeFace(Geom_ConicalSurface(gp_Ax3(pnt(p["apex"]), gp_Dir(*map(float, a))), t, 0.0),
                                   0.0, 2 * math.pi, v0, v1, tol).Face()


def cells(faces, lo, hi, fuzzy):
    from OCP.BOPAlgo import BOPAlgo_MakerVolume
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopTools import TopTools_ListOfShape

    args = TopTools_ListOfShape()
    args.Append(BRepPrimAPI_MakeBox(gp_Pnt(*map(float, lo)), gp_Pnt(*map(float, hi))).Shape())
    for f in faces:
        args.Append(f)
    mv = BOPAlgo_MakerVolume()
    mv.SetArguments(args)
    mv.SetRunParallel(True)
    mv.SetFuzzyValue(fuzzy)
    mv.Perform()
    if mv.HasErrors():
        fail("the surfaces could not be intersected into cells")
    out, ex = [], TopExp_Explorer(mv.Shape(), TopAbs_SOLID)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def inside_cells(solids, mesh, rng, tol):
    """The cells whose interior lies inside the scan, by majority of SAMPLES interior points."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN

    keep = []
    for s in solids:
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(s, g)
        if g.Mass() <= 0:
            continue
        b = Bnd_Box()
        BRepBndLib.Add_s(s, b)
        x0, y0, z0, x1, y1, z1 = b.Get()
        cls = BRepClass3d_SolidClassifier(s)
        c = g.CentreOfMass()
        cand = np.r_[[[c.X(), c.Y(), c.Z()]], rng.uniform([x0, y0, z0], [x1, y1, z1], (40 * SAMPLES, 3))]
        pts = []
        for q in cand:
            cls.Perform(gp_Pnt(*map(float, q)), tol)
            if cls.State() == TopAbs_IN:
                pts.append(q)
                if len(pts) == SAMPLES:
                    break
        if pts and mesh.contains(np.array(pts)).mean() > 0.5:
            keep.append(s)
    return keep


def union(cells_):
    """The boundary of the kept cells (faces shared by two kept cells are interior) as one or more solids, faces of
    one surface merged back."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Compound
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    bb = BRep_Builder()
    comp = TopoDS_Compound()
    bb.MakeCompound(comp)
    for c in cells_:
        bb.Add(comp, c)
    fmap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(comp, TopAbs_FACE, TopAbs_SOLID, fmap)
    sew = BRepBuilderAPI_Sewing(1e-7)
    for i in range(1, fmap.Extent() + 1):
        if fmap.FindFromIndex(i).Extent() == 1:
            # the face as its one kept cell sees it: oriented outward from that cell
            f, cell = fmap.FindKey(i), fmap.FindFromIndex(i).First()
            ex = TopExp_Explorer(cell, TopAbs_FACE)
            while ex.More():
                if ex.Current().IsSame(f):
                    sew.Add(ex.Current())
                    break
                ex.Next()
    sew.Perform()
    shells, ex = [], TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    while ex.More():
        shells.append(TopoDS.Shell_s(ex.Current()))
        ex.Next()
    sol = TopoDS_Compound()
    bb.MakeCompound(sol)
    for sh in shells:
        ms = BRepBuilderAPI_MakeSolid(sh)
        fx = ShapeFix_Solid(ms.Solid())
        fx.Perform()
        bb.Add(sol, fx.Solid())
    try:
        u = ShapeUpgrade_UnifySameDomain(sol, True, True, True)
        u.Build()
        return u.Shape()
    except Exception:  # noqa: BLE001 - the merge is cosmetic (fewer faces); the unmerged solid is the same solid
        return sol


def census(shape):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    kinds = {}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        k = str(BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType()).split("_")[-1].lower()
        kinds[k] = kinds.get(k, 0) + 1
        ex.Next()
    n, ex = 0, TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        n += 1
        ex.Next()
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return {"solids": n, "faces": sum(kinds.values()), "valid": bool(BRepCheck_Analyzer(shape).IsValid()),
            "cylinders": kinds.get("cylinder", 0), "planes": kinds.get("plane", 0), "cones": kinds.get("cone", 0),
            "spheres": kinds.get("sphere", 0), "tori": kinds.get("torus", 0), "volume": float(g.Mass())}


def build(stl, out, labels_path):
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    t0 = time.time()
    mesh = trimesh.load(stl, process=False, force="mesh")
    mesh.merge_vertices()            # adjacency for the noise estimate; the face order (the labels' index) is kept
    lab = json.loads(Path(labels_path).read_text())
    label = np.asarray(lab["label"])
    if len(label) != len(mesh.faces):
        fail(f"{len(label)} labels for {len(mesh.faces)} triangles")
    diag = float(np.linalg.norm(mesh.extents))
    lo, hi = mesh.bounds[0] - 0.05 * diag, mesh.bounds[1] + 0.05 * diag
    surfs = dedupe(surfaces(mesh, label, lab["kinds"], lab.get("params", {}), set(lab.get("fill", []))), 2e-3 * diag)
    if not surfs:
        fail("no surface to build from")
    faces = []
    for kind, p, ts in surfs:
        P = mesh.vertices[np.unique(mesh.faces[ts])]
        rlo, rhi = np.maximum(P.min(0) - EXT * diag, lo), np.minimum(P.max(0) + EXT * diag, hi)
        try:
            faces.append(occ_face(kind, p, rlo, rhi, 1e-7))
        except Exception:  # noqa: BLE001 - a degenerate surface (zero radius, spindle) is skipped, not fatal
            continue
    cs = cells(faces, lo, hi, 1e-5 * diag)
    keep = inside_cells(cs, mesh, np.random.default_rng(0), 1e-7)
    if not keep:
        fail(f"none of {len(cs)} cells lies inside the scan")
    shape = union(keep)
    res = census(shape) | {"mesh_volume": float(mesh.volume), "surfaces": len(surfs), "cells": len(cs),
                           "kept": len(keep), "seconds": round(time.time() - t0, 1)}
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    w.Write(str(out))
    print("RESULT " + repr(res), flush=True)
    return res


if __name__ == "__main__":
    import os
    import resource

    # runs beside the web service: an arrangement that explodes must fail this process, not the node
    gb = float(os.environ.get("CELLBUILD_MEM_GB", "6"))
    resource.setrlimit(resource.RLIMIT_AS, (int(gb * 2 ** 30), int(gb * 2 ** 30)))
    a = sys.argv[1:]
    if len(a) != 4 or a[2] != "--labels":
        fail("usage: cellbuild.py in.stl out.step --labels labels.json")
    build(a[0], a[1], a[3])
