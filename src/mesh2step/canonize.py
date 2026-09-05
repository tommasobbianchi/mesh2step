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
_UNIFORMITY = 0.35        # max coefficient of variation for turn angle and chord length


@dataclass
class FoundCircle:
    radius: float
    centre: tuple[float, float, float]
    axis: tuple[float, float, float]
    segments: int
    max_residual_mm: float
    closed: bool = True
    span_deg: float = 360.0


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
    """Chain segments through vertices by pairing them, not by walking greedily.

    The first version walked forward from each unused segment and marked every
    segment it touched as consumed. Two defects followed: a chain seeded in the
    middle of a circle could only grow one way, and a walk that wandered off
    through a chamfer burned the circle's segments so nothing could find them
    again. Pairing is symmetric and order-independent: at each vertex the
    incident segments are matched to whichever partner continues straightest,
    best pair first, each end used once. Chains are then whatever the pairing
    connects, and a circle is a cycle in it.
    """
    at = defaultdict(list)
    for idx, s in enumerate(segs):
        at[s["a"]].append((idx, "a"))
        at[s["b"]].append((idx, "b"))

    def leaving(i, end):
        """Direction leaving the vertex at `end` of segment i."""
        d = segs[i]["dir"]
        return d if end == "a" else tuple(-x for x in d)

    pair: dict[tuple[int, str], tuple[int, str]] = {}
    for _vertex, incident in at.items():
        if len(incident) < 2:
            continue
        cands = []
        for x in range(len(incident)):
            for y in range(x + 1, len(incident)):
                i, ei = incident[x]
                j, ej = incident[y]
                if i == j:
                    continue
                di, dj = leaving(i, ei), leaving(j, ej)
                # straight-through means the two leaving directions oppose
                dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(di, dj, strict=True))))
                turn = math.pi - math.acos(dot)
                if turn <= max_turn_rad:
                    cands.append((turn, i, ei, j, ej))
        cands.sort()
        taken: set[tuple[int, str]] = set()
        for _turn, i, ei, j, ej in cands:
            if (i, ei) in taken or (j, ej) in taken:
                continue
            pair[(i, ei)] = (j, ej)
            pair[(j, ej)] = (i, ei)
            taken.add((i, ei))
            taken.add((j, ej))

    other = {"a": "b", "b": "a"}
    seen: set[int] = set()
    chains = []
    for start in range(len(segs)):
        if start in seen:
            continue
        # walk back to an end (or all the way round, which means a cycle)
        cur, end = start, "a"
        closed = False
        while (cur, end) in pair:
            nxt, nend = pair[(cur, end)]
            if nxt == start:
                closed = True
                break
            cur, end = nxt, other[nend]
        # then forward, collecting
        chain = []
        walk, wend = (start, "a") if closed else (cur, other[end])
        while True:
            chain.append((walk, 1 if wend == "a" else -1))
            seen.add(walk)
            nxt = pair.get((walk, other[wend]))
            if nxt is None:
                break
            nseg, nend = nxt
            if nseg in seen:
                break
            walk, wend = nseg, nend
        if len(chain) >= MIN_SEGMENTS:
            chains.append((chain, closed))
    return chains


def _fit_circle(points: np.ndarray, tol: float):
    """Plane by SVD, circle by Kasa, then one Gauss-Newton step to a geometric fit.

    Both gates are ABSOLUTE distances in mm. The first version gated planarity on
    sv[2]/sv[0], a ratio, which rejected a 1.2mm hole sitting 0.025mm off plane
    while accepting a 25mm circle with the same error -- scale-dependence of
    exactly the kind stl2step's own README records for its old area cutoff.
    """
    centre = points.mean(axis=0)
    q = points - centre
    _, _sv, vt = np.linalg.svd(q, full_matrices=False)
    if float(np.abs(q @ vt[2]).max()) > tol:
        return None
    u, v = vt[0], vt[1]
    x, y = q @ u, q @ v
    sol, *_ = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x**2 + y**2, rcond=None)
    cx, cy = float(sol[0]), float(sol[1])
    radius = math.sqrt(max(float(sol[2]) + cx * cx + cy * cy, 0.0))
    for _ in range(3):  # Gauss-Newton on the true (geometric) residual
        dx, dy = x - cx, y - cy
        d = np.hypot(dx, dy)
        d = np.where(d < 1e-12, 1e-12, d)
        r_ = d - radius
        j = np.c_[-dx / d, -dy / d, -np.ones(len(d))]
        step, *_ = np.linalg.lstsq(j, -r_, rcond=None)
        cx += float(step[0])
        cy += float(step[1])
        radius += float(step[2])
    residual = float(np.abs(np.hypot(x - cx, y - cy) - radius).max())
    if residual > tol or radius <= 0:
        return None
    # a circle turns the same way throughout; a wandering chain does not
    ang = np.unwrap(np.arctan2(y - cy, x - cx))
    steps = np.diff(ang)
    if len(steps) and not (np.all(steps > 0) or np.all(steps < 0)):
        return None
    # ...and it turns by a near-CONSTANT amount, over near-equal chords. Residual
    # alone accepts any closed polygon whose vertices happen to sit near a circle;
    # measured on 57 real CAD parts that was ~60 spurious loops. Uniformity is the
    # discriminator, and it is the same criterion as the turn gate, stated properly.
    if len(steps) >= 3:
        m = float(np.abs(steps).mean())
        if m <= 0 or float(np.abs(steps).std()) / m > _UNIFORMITY:
            return None
    chords = np.hypot(np.diff(x), np.diff(y))
    if len(chords) >= 3:
        m = float(chords.mean())
        if m <= 0 or float(chords.std()) / m > _UNIFORMITY:
            return None
    span = float(abs(ang[-1] - ang[0])) if len(ang) > 1 else 0.0
    return radius, centre + cx * u + cy * v, np.cross(u, v), residual, span


def find_circles(step_path, *, tol_mm: float = DEFAULT_TOL_MM,
                 turn_deg: float = DEFAULT_TURN_DEG,
                 min_span_deg: float = 120.0) -> list[FoundCircle]:
    """Circles hiding as closed polylines in a STEP, largest first."""
    segs = _load_line_edges(Path(step_path))
    out = []
    for chain, closed in _trace_chains(segs, math.radians(turn_deg)):
        pts = [segs[j]["pa" if sg > 0 else "pb"] for j, sg in chain]
        if closed:  # close the ring so the fit sees the last segment too
            j, sg = chain[-1]
            pts.append(segs[j]["pb" if sg > 0 else "pa"])
        fit = _fit_circle(np.array(pts), tol_mm)
        if fit is None:
            continue
        radius, centre, axis, residual, span = fit
        # an open chain is a rim split at a seam vertex; keep it if it is most of
        # a circle, so the rebuild can join the halves.
        if not closed and span < math.radians(min_span_deg):
            continue
        out.append(FoundCircle(radius, tuple(centre), tuple(axis), len(chain), residual,
                               closed, math.degrees(span)))
    return sorted(out, key=lambda c: -c.radius)
