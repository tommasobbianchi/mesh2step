"""Find the circles a faceted STEP lost.

TrueForm seeds a cylinder only when adjacent facets meet at more than 5 degrees
(the engine's Phase-B seed band), so a circle drawn with 72-127 segments comes out
as one planar face per facet -- "a sum of curved lines". The information is still
there in the output: those facets share a chain of straight edges that turns by a
small, near-constant angle and closes on itself.

So we trace those chains and fit them. OCCT's ShapeAnalysis_CanonicalRecognition
does not help here -- it fits canonical geometry to an existing curve or surface
and returns status=0, gap=-1 on a polyline wire (measured) -- so the fit is a plane
by SVD plus Kasa's algebraic circle, which is exact enough: on a real 96-segment
lid the residuals come out at 5e-5 mm.

This module reports. Rebuilding the B-Rep from what it finds is a separate step.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_TURN_DEG = 20.0   # max turn between consecutive segments to stay in a chain
DEFAULT_TOL_MM = 0.05     # max radial residual for a chain to count as a circle
MIN_SEGMENTS = 6          # below this a "circle" is just a polygon
_PLANARITY = 1e-3         # third singular value / first, for the chain's points


@dataclass
class FoundCircle:
    radius: float
    centre: tuple[float, float, float]
    axis: tuple[float, float, float]
    segments: int
    max_residual_mm: float


def _load_line_edges(step_path: Path):
    from OCP.BRep import BRep_Tool
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.GeomAdaptor import GeomAdaptor_Curve
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    reader = STEPControl_Reader()
    reader.ReadFile(str(step_path))
    reader.TransferRoots()
    shape = reader.OneShape()

    emap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, emap)

    key = lambda p: (round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6))  # noqa: E731
    segs = []
    for i in range(1, emap.Extent() + 1):
        edge = TopoDS.Edge_s(emap.FindKey(i))
        curve = BRep_Tool.Curve_s(edge, 0.0, 0.0)
        if curve is None or GeomAdaptor_Curve(curve).GetType() != GeomAbs_Line:
            continue
        p1 = BRep_Tool.Pnt_s(TopExp.FirstVertex_s(edge))
        p2 = BRep_Tool.Pnt_s(TopExp.LastVertex_s(edge))
        d = (p2.X() - p1.X(), p2.Y() - p1.Y(), p2.Z() - p1.Z())
        length = math.sqrt(sum(x * x for x in d))
        if length < 1e-9:
            continue
        segs.append({
            "a": key(p1), "b": key(p2),
            "pa": (p1.X(), p1.Y(), p1.Z()), "pb": (p2.X(), p2.Y(), p2.Z()),
            "dir": tuple(x / length for x in d),
        })
    return segs


def _trace_chains(segs, max_turn_rad: float):
    """Walk segment to segment while the turn stays under max_turn -- the user's
    criterion: a small, consistent turn between straight pieces IS a curve."""
    at = defaultdict(list)
    for idx, s in enumerate(segs):
        at[s["a"]].append(idx)
        at[s["b"]].append(idx)

    def direction(i, sign):
        d = segs[i]["dir"]
        return d if sign > 0 else tuple(-x for x in d)

    used: set[int] = set()
    chains = []
    for start in range(len(segs)):
        if start in used:
            continue
        chain = [(start, 1)]
        local = {start}
        cur, sign = start, 1
        head = segs[cur]["b"]
        closed = False
        while True:
            d0 = direction(cur, sign)
            best, best_ang = None, max_turn_rad
            for j in at[head]:
                if j == cur:
                    continue
                sj = 1 if segs[j]["a"] == head else -1
                dot = sum(a * b for a, b in zip(d0, direction(j, sj), strict=True))
                ang = math.acos(max(-1.0, min(1.0, dot)))
                if ang < best_ang:
                    best, best_ang = (j, sj), ang
            if best is None:
                break
            j, sj = best
            if j in local:
                closed = j == start
                break
            chain.append((j, sj))
            local.add(j)
            cur, sign = j, sj
            head = segs[j]["b"] if sj > 0 else segs[j]["a"]
        if len(chain) >= MIN_SEGMENTS:
            used |= local
            chains.append((chain, closed))
    return chains


def _fit_circle(points: np.ndarray, tol: float):
    centre = points.mean(axis=0)
    q = points - centre
    _, sv, vt = np.linalg.svd(q, full_matrices=False)
    if sv[2] / max(sv[0], 1e-12) > _PLANARITY:
        return None
    u, v = vt[0], vt[1]
    x, y = q @ u, q @ v
    # Kasa: minimise |x^2+y^2 - (2cx*x + 2cy*y + c)| , linear in the unknowns.
    sol, *_ = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x**2 + y**2, rcond=None)
    cx, cy = float(sol[0]), float(sol[1])
    radius = math.sqrt(float(sol[2]) + cx * cx + cy * cy)
    residual = float(np.abs(np.hypot(x - cx, y - cy) - radius).max())
    if residual > tol:
        return None
    return radius, centre + cx * u + cy * v, np.cross(u, v), residual


def find_circles(step_path, *, tol_mm: float = DEFAULT_TOL_MM,
                 turn_deg: float = DEFAULT_TURN_DEG) -> list[FoundCircle]:
    """Circles hiding as closed polylines in a STEP, largest first."""
    segs = _load_line_edges(Path(step_path))
    out = []
    for chain, closed in _trace_chains(segs, math.radians(turn_deg)):
        if not closed:
            continue
        pts = np.array([segs[j]["pa" if sg > 0 else "pb"] for j, sg in chain])
        fit = _fit_circle(pts, tol_mm)
        if fit is None:
            continue
        radius, centre, axis, residual = fit
        out.append(FoundCircle(radius, tuple(centre), tuple(axis), len(chain), residual))
    return sorted(out, key=lambda c: -c.radius)
