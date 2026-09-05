"""Group detected circles into the cylinder bands a rebuild can replace.

The circles a faceted STEP still carries (see `canonize`) are rims. Two rims of
equal radius on a common axis bound a cylinder -- but only if the faces between
them actually form a continuous wall. On a real lid, the rim of a hole through
one wall is exactly collinear with the rim of the hole through the opposite wall
41.95mm away: same axis, same radius, and no cylinder between them. Coaxiality is
necessary and nowhere near sufficient, so the band's faces decide.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .canonize import DEFAULT_TOL_MM, find_circles

MAX_AXIAL_GAP_MM = 0.5   # a wall with a hole this big in it is not one cylinder


@dataclass
class CylinderBand:
    radius: float
    base: tuple[float, float, float]      # centre of the rim the axis points away from
    axis: tuple[float, float, float]      # unit, base -> top
    height: float
    face_indices: list[int]               # 1-based, into the shape's face map


def _plane_normal(face):
    """Unit normal if the face is planar, else None."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    a = BRepAdaptor_Surface(face)
    if a.GetType() != GeomAbs_Plane:
        return None
    d = a.Plane().Axis().Direction()
    return np.array([d.X(), d.Y(), d.Z()])


def _face_points(face):
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    vm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face, TopAbs_VERTEX, vm)
    pts = []
    for i in range(1, vm.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vm.FindKey(i)))
        pts.append([p.X(), p.Y(), p.Z()])
    return np.array(pts) if pts else np.zeros((0, 3))


def find_bands(step_path, *, tol_mm: float = DEFAULT_TOL_MM) -> list[CylinderBand]:
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    step_path = Path(step_path)
    circles = find_circles(step_path, tol_mm=tol_mm)
    if len(circles) < 2:
        return []

    reader = STEPControl_Reader()
    reader.ReadFile(str(step_path))
    reader.TransferRoots()
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(reader.OneShape(), TopAbs_FACE, fm)
    faces = []
    for i in range(1, fm.Extent() + 1):
        f = TopoDS.Face_s(fm.FindKey(i))
        faces.append((i, _face_points(f), _plane_normal(f)))

    bands: list[CylinderBand] = []
    for i, a in enumerate(circles):
        for b in circles[i + 1:]:
            if abs(a.radius - b.radius) > max(0.01 * a.radius, 2 * tol_mm):
                continue
            base = np.array(a.centre)
            delta = np.array(b.centre) - base
            height = float(np.linalg.norm(delta))
            if height < tol_mm:
                continue
            axis = delta / height
            # the fitted normals are unsigned, so take the axis from the pair itself
            # and only require the rims' planes to be perpendicular to it
            if abs(abs(float(np.array(a.axis) @ axis)) - 1) > 1e-3:
                continue
            if abs(abs(float(np.array(b.axis) @ axis)) - 1) > 1e-3:
                continue

            members, covered = [], []
            for idx, pts, normal in faces:
                if len(pts) == 0 or normal is None:
                    continue
                # A wall strip's normal is perpendicular to the axis. A cap disc's
                # boundary vertices all sit at exactly the band radius, so a
                # vertex-only test swallows the caps and the band becomes the whole
                # solid -- measured: 98 of 98 faces on a plain cylinder.
                if abs(float(normal @ axis)) > 1e-3:
                    continue
                d = pts - base
                z = d @ axis
                rho = np.linalg.norm(d - np.outer(z, axis), axis=1)
                if np.abs(rho - a.radius).max() > tol_mm:
                    continue
                if z.min() < -tol_mm or z.max() > height + tol_mm:
                    continue
                members.append(idx)
                covered.append((float(z.min()), float(z.max())))
            if not members:
                continue
            # the wall must be continuous: two rims of collinear holes in opposite
            # walls pass every test above and have a 38mm hole in the middle.
            covered.sort()
            reach = covered[0][1]
            for lo, hi in covered[1:]:
                if lo - reach > MAX_AXIAL_GAP_MM:
                    reach = None
                    break
                reach = max(reach, hi)
            if reach is None or covered[0][0] > MAX_AXIAL_GAP_MM \
                    or height - reach > MAX_AXIAL_GAP_MM:
                continue
            bands.append(CylinderBand(a.radius, tuple(base), tuple(axis), height, members))
    return sorted(bands, key=lambda b: -b.radius)


ARC_VERTEX_TOL_MM = 1e-6   # rim vertices sit on the fitted circle to ~2e-7mm but carry
                           # a tighter tolerance of their own, and MakeEdge then refuses


def _is_rim_chord(p1, p2, base, axis, radius, tol):
    """A straight edge whose ends both lie on one rim circle of the band."""
    for p in (p1, p2):
        d = p - base
        z = float(d @ axis)
        if abs(np.linalg.norm(d - z * axis) - radius) > tol:
            return None
    z1 = float((p1 - base) @ axis)
    z2 = float((p2 - base) @ axis)
    if abs(z1 - z2) > tol:
        return None
    return z1


def rebuild_cylinders(step_in, step_out, *, tol_mm: float = DEFAULT_TOL_MM) -> dict:
    """Replace faceted cylinder bands with one analytic cylindrical face each.

    The band's strips are dropped and replaced by a single seamed 360 face built
    from the fitted cylinder; every neighbouring face that borders the band has
    its chain of rim chords replaced by that face's own circular edge, so the
    edge is shared by construction and sewing has nothing to bridge. No vertex
    that survives is moved.

    Merging 96 rebuilt cylindrical patches with ShapeUpgrade_UnifySameDomain was
    tried first and does not close the seam: it yields two half-cylinders and an
    open compound (measured -- volume 0, valid False).
    """
    import math

    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_Sewing,
    )
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Circle
    from OCP.gp import gp_Ax3, gp_Cylinder, gp_Dir, gp_Pnt
    from OCP.GProp import GProp_GProps
    from OCP.ShapeFix import ShapeFix_Shape, ShapeFix_Solid
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader, STEPControl_Writer
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_WIRE
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    step_in, step_out = Path(step_in), Path(step_out)
    reader = STEPControl_Reader()
    reader.ReadFile(str(step_in))
    reader.TransferRoots()
    # Coplanar facets first: with one face per triangle a strip's diagonal is a 3D
    # chord lying on no cylinder, and band membership is undefined for it.
    unify = ShapeUpgrade_UnifySameDomain(reader.OneShape(), True, True, True)
    unify.Build()
    merged = Path(str(step_out) + ".merged.step")
    w0 = STEPControl_Writer()
    w0.Transfer(unify.Shape(), STEPControl_AsIs)
    w0.Write(str(merged))

    bands = find_bands(merged, tol_mm=tol_mm)
    reader2 = STEPControl_Reader()
    reader2.ReadFile(str(merged))
    reader2.TransferRoots()
    shape = reader2.OneShape()
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    if not bands:
        merged.unlink(missing_ok=True)
        return {"bands": 0, "faces_before": fmap.Extent(), "faces_after": fmap.Extent(),
                "ok": False, "reason": "no cylinder bands found"}

    pt = lambda v: np.array([BRep_Tool.Pnt_s(v).X(), BRep_Tool.Pnt_s(v).Y(),  # noqa: E731
                             BRep_Tool.Pnt_s(v).Z()])

    new_faces = []
    dropped: set[int] = set()
    # rim key (band index, rounded height) -> the circular edge of the new face
    rim_edge: dict[tuple[int, float], object] = {}
    rim_of_band: list[tuple[np.ndarray, np.ndarray, float, float]] = []
    for bi, band in enumerate(bands):
        axis, base = np.array(band.axis), np.array(band.base)
        cyl = gp_Cylinder(gp_Ax3(gp_Pnt(*base), gp_Dir(*axis)), band.radius)
        mf = BRepBuilderAPI_MakeFace(cyl, 0.0, 2 * math.pi, 0.0, band.height)
        if not mf.IsDone():
            continue
        face = mf.Face()
        new_faces.append(face)
        dropped |= set(band.face_indices)
        rim_of_band.append((base, axis, band.radius, band.height))
        emap = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(face, TopAbs_EDGE, emap)
        for i in range(1, emap.Extent() + 1):
            edge = TopoDS.Edge_s(emap.FindKey(i))
            if BRepAdaptor_Curve(edge).GetType() != GeomAbs_Circle:
                continue
            centre = BRepAdaptor_Curve(edge).Circle().Location()
            z = float((np.array([centre.X(), centre.Y(), centre.Z()]) - base) @ axis)
            rim_edge[(bi, round(z, 6))] = edge

    def rim_hit(p1, p2):
        """(band index, rim height) if this straight edge is a chord of some rim."""
        for bi, (base, axis, radius, height) in enumerate(rim_of_band):
            z = _is_rim_chord(p1, p2, base, axis, radius, tol_mm)
            if z is None:
                continue
            for zz in (0.0, height):
                if abs(z - zz) <= tol_mm and (bi, round(zz, 6)) in rim_edge:
                    return bi, round(zz, 6)
        return None

    rebuilt_n = failed_n = 0
    for idx in range(1, fmap.Extent() + 1):
        if idx in dropped:
            continue
        face = TopoDS.Face_s(fmap.FindKey(idx))
        wires, changed, bad = [], False, False
        exp = TopExp_Explorer(face, TopAbs_WIRE)
        while exp.More():
            wire = TopoDS.Wire_s(exp.Current())
            mw = BRepBuilderAPI_MakeWire()
            used_rims: set[tuple[int, float]] = set()
            eexp = TopExp_Explorer(wire, TopAbs_EDGE)
            while eexp.More():
                edge = TopoDS.Edge_s(eexp.Current())
                v1, v2 = TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)
                hit = rim_hit(pt(v1), pt(v2))
                if hit is None:
                    mw.Add(edge)
                elif hit not in used_rims:
                    # the whole chain of chords collapses to this one circle
                    used_rims.add(hit)
                    mw.Add(rim_edge[hit])
                eexp.Next()
            if not mw.IsDone():
                bad = True
                break
            wires.append(mw.Wire())
            changed |= bool(used_rims)
            exp.Next()
        if bad or not wires:
            new_faces.append(face)
            failed_n += 1
            continue
        if not changed:
            new_faces.append(face)
            continue
        mkf = BRepBuilderAPI_MakeFace(BRep_Tool.Surface_s(face), wires[0], True)
        for extra in wires[1:]:
            mkf.Add(extra)
        if mkf.IsDone():
            new_faces.append(mkf.Face())
            rebuilt_n += 1
        else:
            new_faces.append(face)
            failed_n += 1

    sew = BRepBuilderAPI_Sewing(max(10 * tol_mm, 1e-4))
    for f in new_faces:
        sew.Add(f)
    sew.Perform()
    out = sew.SewedShape()
    fix = ShapeFix_Shape(out)
    fix.Perform()
    out = fix.Shape()
    if out.ShapeType() == TopAbs_SHELL:
        out = ShapeFix_Solid().SolidFromShell(TopoDS.Shell_s(out))

    fmap2 = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(out, TopAbs_FACE, fmap2)
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(out, props)
    w2 = STEPControl_Writer()
    w2.Transfer(out, STEPControl_AsIs)
    w2.Write(str(step_out))
    merged.unlink(missing_ok=True)
    return {
        "bands": len(bands),
        "faces_before": fmap.Extent(),
        "faces_after": fmap2.Extent(),
        "faces_replaced": len(dropped),
        "faces_rebuilt": rebuilt_n,
        "faces_failed": failed_n,
        "volume": float(props.Mass()),
        "valid": bool(BRepCheck_Analyzer(out).IsValid()),
        "ok": failed_n == 0,
    }
