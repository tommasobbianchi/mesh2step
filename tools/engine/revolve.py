"""Revolve candidates (docs/ENGINE.md language: revolve), from evidence axes: every coaxial group of curved
surfaces, and every lone torus or cone, on a principal axis. The profile is read off the scan in (r, h):

  material at every angle -> a revolve pad (the axisymmetric core)
  air at every angle, inside the part's radius and height -> a revolve cut (a groove, a countersink, a cone)

Masks are voxel centres tested in (r, h). The ILP (cells.py) mixes them with the extrusion candidates; J decides.
"""
import math
import sys
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cells as C                                      # noqa: E402
import evidence as E                                   # noqa: E402

PR = C.PR
ANGLES = 24                                           # half-plane sections per axis


def axes(shape, tol):
    """Revolve axes on principal directions: (axis index, point on the axis line), deduplicated."""
    recs = E.surfaces(shape)
    out = []
    for r in recs:
        if r["kind"] not in ("torus", "cone", "cylinder"):
            continue
        d = np.array(r["axis"])
        a = int(np.argmax(np.abs(d)))
        if abs(d[a]) < 0.999:
            continue
        o = np.array(r["origin"])
        if r["kind"] == "cylinder":                    # a lone cylinder is an extrusion's wall: needs a coaxial partner
            partners = [q for q in recs if q is not r and q["kind"] in ("torus", "cone", "cylinder")
                        and abs(np.array(q["axis"])[a]) > 0.999
                        and np.linalg.norm(np.delete(np.array(q["origin"]) - o, a)) <= tol
                        and (q["kind"] != "cylinder" or abs(q["radius"] - r["radius"]) > tol)]
            if not partners:
                continue
        if not any(b == a and np.linalg.norm(np.delete(p - o, a)) <= tol for b, p in out):
            out.append((a, o))
    return out


def _halfplane(m, a, p, th, tol):
    """The scan's section by the half-plane through the axis at angle th, in (r, h), r >= 0."""
    u, v = [k for k in range(3) if k != a]
    d = np.zeros(3)
    d[u], d[v] = math.cos(th), math.sin(th)            # radial direction
    n = np.zeros(3)
    n[u], n[v] = -math.sin(th), math.cos(th)           # plane normal
    sec = m.section(plane_origin=p, plane_normal=n)
    if sec is None:
        return Polygon()
    lines = []
    for pl in sec.discrete:
        q = np.asarray(pl) - p
        lines.append(LineString(np.c_[q @ d, np.asarray(pl)[:, a]]))
    merged = shapely.union_all(lines, grid_size=tol / 100)
    parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    shells = sorted({Polygon(g.exterior) for g in shapely.polygonize(parts).geoms}, key=lambda g: -g.area)
    out = Polygon()
    for g in shells:
        out = out.symmetric_difference(g) if not out.is_empty else g
    lo, hi = m.bounds
    return out.buffer(0).intersection(box(0, lo[a] - 1, 1e6, hi[a] + 1))


def profiles(m, a, p, tol):
    mat = union = None
    for th in np.linspace(0, 2 * math.pi, ANGLES, endpoint=False):
        g = _halfplane(m, a, p, th, tol)
        mat = g if mat is None else C._op(shapely.intersection, mat, g, tol)
        union = g if union is None else C._op(shapely.union, union, g, tol)
    lo, hi = m.bounds
    rmax = max(np.linalg.norm(np.delete(c - p, a)) for c in (lo, hi, np.array([lo[0], hi[1], lo[2]]),
                                                              np.array([hi[0], lo[1], hi[2]])))
    frame = box(0, lo[a], rmax, hi[a])
    return mat, C._op(shapely.difference, frame, union, tol) if union is not None else Polygon()


def _loops(g, tol):
    """A profile polygon -> revolve loops (lines/arcs; a full circle is kept as its polygon)."""
    g = g.simplify(tol / 20, preserve_topology=True)
    out = []
    for ring in [g.exterior] + list(g.interiors):
        P = np.asarray(ring.coords)[:-1]
        lp = PR.loop_prims("Z", P, native=True)
        if len(lp) == 1 and lp[0]["t"] == "circle":
            lp = [{"t": "line", "p": [[round(float(x), 4) for x in P[i]], [round(float(x), 4) for x in P[(i + 1) % len(P)]]]}
                  for i in range(len(P))]
        out.append(lp)
    return out


def candidates(shape, m, tol):
    out = []
    for a, p in axes(shape, tol):
        mat, air = profiles(m, a, p, tol)
        for op, reg in (("pad", mat), ("pocket", air)):
            for g in PR._polys(reg):
                if g.area < 4 * tol * tol:
                    continue
                try:
                    loops = _loops(g, tol)
                except Exception:                        # noqa: BLE001 -- an unfittable profile is no candidate
                    continue
                lo, hi = g.bounds[1], g.bounds[3]
                feat = {"op": op, "label": f"{'Revolve' if op == 'pad' else 'Revolved cut'} about {'XYZ'[a]}",
                        "axis": "XYZ"[a], "at": round(float(lo), 4), "length": round(float(hi - lo), 4),
                        "revolve": {"axis": "XYZ"[a], "point": [round(float(x), 4) for x in p]}, "loops": loops}
                cd = C.SE.Cand(op=op, a=a, reg=g, mask=None, k0=0, k1=0, z0=float(lo), z1=float(hi), cost=1,
                               label=feat["label"], circle=None)
                cd.feat = feat
                out.append(cd)
    return out


def mask(cd, c):
    """Voxel centres inside the revolve (flat, x-y-z order like cells.masks)."""
    a = cd.a
    p = np.array(cd.feat["revolve"]["point"], float)
    X, Y, Z = np.meshgrid(c[0], c[1], c[2], indexing="ij")
    P = [X, Y, Z]
    u, v = [k for k in range(3) if k != a]
    r = np.sqrt((P[u] - p[u]) ** 2 + (P[v] - p[v]) ** 2)
    return shapely.contains_xy(cd.reg, r.ravel(), P[a].ravel())
