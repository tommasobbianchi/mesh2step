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
    faces = [(i, _face_points(TopoDS.Face_s(fm.FindKey(i)))) for i in range(1, fm.Extent() + 1)]

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
            for idx, pts in faces:
                if len(pts) == 0:
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
