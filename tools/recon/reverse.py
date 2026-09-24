#!/usr/bin/env python3
"""Reverse the design history of a prismatic part: silhouette sketch -> extrude -> edge rounds.

Tommaso, 2026-09-22: an engineer does not model the final faces. He projects the part's maximum extents onto
a plane (the sketch), extrudes it, then applies the modifiers (fillets, holes). A full round (half pipe) is the
case that exposes the difference: the final faces are tori and 0.1 mm slivers, the history is one sketch, one
extrude, one fillet.

  1. axis: the one along which sections change least (facts.py's measure);
  2. sketch: every triangle projected on the plane normal to the axis, unioned -> the silhouette (max extents);
     outer loop and holes fitted as exact lines/arcs (auto2d.segment_loop);
  3. extrude: the part's extent along the axis;
  4. rounds: how the cross-section shrinks near the top and bottom caps. A round of radius r insets the section
     by d(h) = r - sqrt(r^2 - (r - h)^2) at depth h from the cap; d is measured as 2 (A_silhouette - A(h)) / (P_silhouette + P(h)).
usage: reverse.py <stl> <out.py> [--json out.json]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feature_recon"))
from auto2d import loop_area, section2d, segment_loop  # noqa: E402
from slice import dedupe, loops  # noqa: E402


def pick_axis(tri, lo, hi):
    """The extrusion axis: the one along which the most surface area is a wall (normal perpendicular to it) or a
    cap (normal parallel), among axes that HAVE caps (>= 5% of the area: the rounds along a plate's straight side are
    cylinders about X, but only Z has the flat top/bottom). Ties (within 1%) go to the axis whose sections change least (facts.py's measure) --
    alone, that measure picked Y for a flange with a round boss on Z."""
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(n, axis=1); ok = area > 1e-12
    n = n[ok] / area[ok, None]; area = area[ok]

    def aligned(ax):
        c = np.abs(n[:, ax])
        return float(area[(c < 0.02) | (c > 0.999)].sum() / area.sum())

    def var(ax):
        ps = [sum(float(np.linalg.norm(b - a)) for a, b in section2d(tri, ax, lo[ax] + f * (hi[ax] - lo[ax])))
              for f in (0.3, 0.5, 0.7)]
        return (max(ps) - min(ps)) / max(np.mean(ps), 1e-9)
    caps = [float(area[np.abs(n[:, a]) > 0.999].sum() / area.sum()) for a in range(3)]
    cand = [a for a in range(3) if caps[a] >= 0.05] or [0, 1, 2]   # an extrusion axis has caps (flat ends)
    sc = {a: aligned(a) for a in cand}
    top = [a for a in cand if sc[a] >= max(sc.values()) - 0.01]
    return top[0] if len(top) == 1 else min(top, key=var)


def plane_axes(ax):
    return [i for i in range(3) if i != ax]


def silhouette(tri, ax):
    u, v = plane_axes(ax)
    polys = []
    for t in tri[:, :, [u, v]]:
        p = Polygon(t)
        if p.area > 1e-9:
            polys.append(p)
    diag = float(np.linalg.norm(np.ptp(tri.reshape(-1, 3), axis=0)))
    eps = 1e-4 * diag                                           # close the hairline gaps between projections
    return unary_union(polys).buffer(eps, join_style=2).buffer(-eps, join_style=2)


def section_area_perimeter(mesh, ax, h):
    n = np.zeros(3); n[ax] = 1.0; o = np.zeros(3); o[ax] = h
    sec = mesh.section(plane_origin=o, plane_normal=n)
    if sec is None:
        return 0.0, 0.0
    planar, _ = sec.to_2D()
    return float(planar.area), float(planar.length)            # area with holes subtracted


def cap_round(mesh, ax, lo, hi, sil, cap):
    """Round radius from the flat cap face: an exact round is tangent to the cap, so the flat region ends where
    the round starts and its inset from the silhouette IS the radius (robust to coarse tessellation, which biases
    section insets low by ~30% on part 16). None when the part has no flat cap."""
    tri = np.asarray(mesh.triangles, float)
    z = hi[ax] if cap > 0 else lo[ax]
    H = float(hi[ax] - lo[ax])
    facing = mesh.face_normals[:, ax] * cap > 0.999
    on_cap = np.abs(tri[:, :, ax].mean(axis=1) - z) < 1e-4 * max(H, 1.0)
    sel = np.logical_and(facing, on_cap)
    if not sel.any():
        return None
    u, v = plane_axes(ax)
    region = unary_union([Polygon(t[:, [u, v]]) for t in tri[sel]]).buffer(0)
    if region.area < 1e-3 * sil.area:
        return None
    if region.geom_type != "Polygon":
        region = max(region.geoms, key=lambda g: g.area)
    # outer boundary and holes separately: a sharp hole's perimeter must not dilute the outer inset (part 16:
    # unrounded r22 holes are 32% of the perimeter -> the round read 6.7 instead of 9.95)
    so, ro = Polygon(sil.exterior), Polygon(region.exterior)
    d_out = 2 * (so.area - ro.area) / (so.length + ro.length)
    holes = []
    for hs in sil.interiors:
        hp = Polygon(hs); match = [Polygon(h) for h in region.interiors if Polygon(h).contains(hp.representative_point())]
        if match:
            holes.append(2 * (match[0].area - hp.area) / (match[0].length + hp.length))
    snap = lambda d: 0.0 if d < 1e-3 * H else float(d)
    return {"outer": snap(d_out), "holes": snap(max(holes)) if holes else 0.0}


def fit_round(mesh, ax, lo, hi, A_sil, P_sil, cap):
    """Fallback when there is no flat cap: fit the round model to section insets (biased low when coarse)."""
    H = hi[ax] - lo[ax]
    hs = np.linspace(0.01, 0.5, 25) * H
    ds = []
    for h in hs:
        z = hi[ax] - h if cap > 0 else lo[ax] + h
        A, P = section_area_perimeter(mesh, ax, z)
        ds.append(max(0.0, 2 * (A_sil - A) / max(P + P_sil, 1e-9)))   # parallel offset: mean perimeter
    ds = np.array(ds)
    if ds[0] < 1e-3 * H:                                        # the section at the cap is the silhouette: sharp
        return 0.0
    best = (1e18, 0.0)
    for r in np.linspace(0.02 * H, 0.5 * H, 200):              # least squares over the round model
        model = np.where(hs < r, r - np.sqrt(np.maximum(0.0, r * r - (r - hs) ** 2)), 0.0)
        err = float(np.sum((model - ds) ** 2))
        if err < best[0]:
            best = (err, float(r))
    return best[1]


TOL = 0.02


def _line_dev(P):
    a, b = P[0], P[-1]; ab = b - a; lab = np.linalg.norm(ab)
    if lab < 1e-9:
        return 1e9
    return float(np.abs((P[:, 0] - a[0]) * ab[1] - (P[:, 1] - a[1]) * ab[0]).max() / lab)


def _circle(P):
    A = np.c_[2 * P, np.ones(len(P))]; b = (P ** 2).sum(1)
    (cx, cy, k), *_ = np.linalg.lstsq(A, b, rcond=None)
    c = np.array([cx, cy]); r = float(np.sqrt(max(k + cx * cx + cy * cy, 0.0)))
    dev = float(np.abs(np.linalg.norm(P - c, axis=1) - r).max())
    # chord midpoints too: a straight side has only its 2 end vertices, which any circle can pass near, but its
    # midpoint is far off; a tessellated arc's chords sag by at most the export tolerance (5 TOL = 0.1 mm)
    mids = (P[1:] + P[:-1]) / 2
    sag = float(np.abs(np.linalg.norm(mids - c, axis=1) - r).max()) if len(mids) else 0.0
    return c, r, dev if sag <= 5 * TOL else 1e9


def segment(L):
    """Closed polyline -> ('line', i0, i1) / ('arc', i0, i1, centre, r), longest fit first.

    auto2d.segment_loop tests a line first and an arc only from 4 points on, so on a coarse mesh (3 points on a
    large arc already bow past the 0.02 mm line tolerance) every arc became 1-segment lines (part 16: 210 lines).
    Here, from each start, the longest run fitting a line OR a circle (>= 4 points) within TOL wins."""
    n = len(L)
    turn = [abs(math.atan2(*(lambda u, v: (u[0] * v[1] - u[1] * v[0], u @ v))(L[k] - L[k - 1], L[(k + 1) % n] - L[k])))
            for k in range(n)]
    s = int(np.argmax(turn)); L = np.r_[L[s:], L[:s], L[s:s + 1]]; n = len(L)
    prims, i = [], 0
    while i < n - 1:
        jl = i + 1
        while jl + 1 < n and _line_dev(L[i:jl + 2]) <= TOL:
            jl += 1
        ja, arc = i + 1, None
        j = i + 3
        while j < n:
            c, r, dev = _circle(L[i:j + 1])
            if dev > TOL or r > 1e4:
                break
            ja, arc = j, (c, r); j += 1
        if arc is not None and ja > jl:
            c, r, _ = _circle(L[i:ja + 1]); prims.append(("arc", i, ja, c, r)); i = ja
        else:
            prims.append(("line", i, jl)); i = jl
    return L, prims


def loop_program(L):
    L2, prims = segment(L)
    out, first = [], True
    for p in prims:
        a, b = L2[p[1]], L2[p[2] if p[2] < len(L2) else 0]
        if first:
            out.append(f".moveTo({a[0]:.4f}, {a[1]:.4f})"); first = False
        if p[0] == "line":
            out.append(f".lineTo({b[0]:.4f}, {b[1]:.4f})")
        else:                                                   # arc through its midpoint on the circle
            c, r = np.asarray(p[3], float), float(p[4])
            m = (np.asarray(a) + np.asarray(b)) / 2 - c
            # the arc's own midpoint: the loop vertex halfway along the primitive
            i0, i1 = p[1], p[2] if p[2] < len(L2) else len(L2)
            if np.linalg.norm(np.asarray(a) - np.asarray(b)) < 1e-6:   # a full circle: two half arcs
                q1, q2, q3 = (L2[i0 + k * (i1 - i0) // 4] for k in (1, 2, 3))
                out.append(f".threePointArc(({q1[0]:.4f}, {q1[1]:.4f}), ({q2[0]:.4f}, {q2[1]:.4f}))")
                out.append(f".threePointArc(({q3[0]:.4f}, {q3[1]:.4f}), ({b[0]:.4f}, {b[1]:.4f}))")
                continue
            mid = L2[(i0 + i1) // 2] if i1 - i0 > 1 else c + m / max(np.linalg.norm(m), 1e-12) * r
            out.append(f".threePointArc(({mid[0]:.4f}, {mid[1]:.4f}), ({b[0]:.4f}, {b[1]:.4f}))")
    return "".join(out) + ".close()", [p[0] for p in prims]


def level_heights(mesh, ax, lo, hi, min_area):
    """Heights of the flat faces normal to the axis (floors, shoulders, tops): the level boundaries of a stack of
    extrusions. Clustered within 0.1% of the height, weighted by area; always includes the bottom and the top."""
    n = mesh.face_normals[:, ax]
    tri = np.asarray(mesh.triangles, float)
    flat = np.abs(n) > 0.999
    H = float(hi[ax] - lo[ax])
    z = tri[flat][:, :, ax].mean(axis=1)
    a = mesh.area_faces[flat]
    hs = {}
    for zi, ai in zip(z, a):
        key = round(float(zi) / (1e-3 * H))
        hs[key] = hs.get(key, 0.0) + float(ai)
    out = sorted({float(lo[ax]), float(hi[ax])} |
                 {k * 1e-3 * H for k, area in hs.items() if area >= min_area})
    merged = [out[0]]
    for v in out[1:]:
        if v - merged[-1] > 2e-3 * H:
            merged.append(v)
    merged[-1] = float(hi[ax])
    return merged


def level_section(mesh, ax, h):
    """Outer loop and hole loops of the section at height h, as 2D point arrays in the plane axes."""
    n = np.zeros(3); n[ax] = 1.0; o = np.zeros(3); o[ax] = h
    sec = mesh.section(plane_origin=o, plane_normal=n)
    if sec is None:
        return []
    u, v = plane_axes(ax)
    polys = []
    for ent in sec.discrete:                                   # 3D polylines of the section
        P = np.asarray(ent)[:, [u, v]]
        if len(P) >= 4:
            pg = Polygon(P)
            if pg.is_valid and pg.area > 1e-6:
                polys.append(pg)
    # nest: a loop inside another is a hole of it
    polys.sort(key=lambda g: -g.area)
    shapes = []
    for pg in polys:
        host = next((sh for sh in shapes if sh["outer"].contains(pg.representative_point())), None)
        if host is not None and not any(hp.contains(pg.representative_point()) for hp in host["holes"]):
            host["holes"].append(pg)
        else:
            shapes.append({"outer": pg, "holes": []})
    return [{"outer": np.asarray(sh["outer"].exterior.coords)[:-1],
             "holes": [np.asarray(hp.exterior.coords)[:-1] for hp in sh["holes"]]} for sh in shapes]


def reverse(stl, axis=None):
    m = trimesh.load(stl, force="mesh")
    tri = np.asarray(m.triangles, float)
    lo, hi = m.bounds
    ax = pick_axis(tri, lo, hi) if axis is None else axis     # tools/tree/propose.py picks its own
    sil = silhouette(tri, ax)
    if sil.geom_type != "Polygon":                              # several islands: keep the largest (report it)
        sil = max(sil.geoms, key=lambda g: g.area)
    # only drop collinear/duplicate points: a coarser simplify turns arcs into chords before they are fitted
    sil = sil.simplify(1e-6 * float(np.linalg.norm(hi - lo)), preserve_topology=True)
    A_sil, P_sil = sil.area, sil.length
    outer = np.asarray(sil.exterior.coords)[:-1]
    holes = [np.asarray(i.coords)[:-1] for i in sil.interiors if Polygon(i).area > 1e-3 * A_sil]
    r_top, r_bot = (cap_round(m, ax, lo, hi, sil, c) for c in (+1, -1))
    if r_top is None:
        r_top = {"outer": fit_round(m, ax, lo, hi, A_sil, P_sil, +1), "holes": 0.0}
    if r_bot is None:
        r_bot = {"outer": fit_round(m, ax, lo, hi, A_sil, P_sil, -1), "holes": 0.0}
    H = float(hi[ax] - lo[ax])
    plane = {0: "YZ", 1: "XZ", 2: "XY"}[ax]
    R = {"axis": "XYZ"[ax], "plane": plane, "z0": float(lo[ax]), "height": H, "outer": outer, "holes": holes,
         "r_top": r_top, "r_bottom": r_bot, "silhouette_area": A_sil, "levels": []}
    zs = level_heights(m, ax, lo, hi, 1e-3 * A_sil)
    if len(zs) > 2:                                           # a stack of extrusions: one sketch per level
        for z0, z1 in zip(zs[:-1], zs[1:]):
            shapes = level_section(m, ax, (z0 + z1) / 2)
            if not shapes:
                continue
            prev = R["levels"][-1] if R["levels"] else None
            if prev and abs(prev["z1"] - z0) < 1e-9 and same_shapes(prev["shapes"], shapes):
                prev["z1"] = z1                               # the same sketch continues: one extrusion, no slivers
            else:
                R["levels"].append({"z0": z0, "z1": z1, "shapes": shapes})
        if len(R["levels"]) == 1:                             # it was one prism after all: the silhouette path
            R["levels"] = []
    return R


def _region(shapes):
    from shapely.geometry import Polygon as P
    out = None
    for sh in shapes:
        g = P(sh["outer"], [h for h in sh["holes"]]).buffer(0)
        out = g if out is None else out.union(g)
    return out


def same_shapes(a, b, tol=0.05):
    """Two level sections are one sketch when their regions differ by a mean offset under tol (mm). Near-equal
    outlines stacked as separate extrusions leave 0.02-0.08 mm2 sliver faces that the STEP round trip breaks
    far from the origin (part 8 at x ~8900)."""
    ra, rb = _region(a), _region(b)
    if ra is None or rb is None:
        return False
    per = max(ra.length, rb.length, 1e-9)
    return ra.symmetric_difference(rb).area / per < tol


def program(R):
    lines = ["# reverse.py: silhouette sketch -> extrude -> edge rounds (design history, not final faces)",
             "def _round(solid, edges, r):",
             "    # OCCT refuses some fillets (a round that would consume a whole face): try slightly smaller, else",
             "    # keep the sharp edge so the sketch and extrude still stand",
             "    for f in (1.0, 0.97, 0.9, 0.75):",
             "        try:",
             "            out = solid.newObject(edges(solid)).fillet(r * f)",
             "            if out.val().isValid():",
             "                return out",
             "        except Exception:",
             "            pass",
             "    return solid"]
    ax, z0, H = R["axis"], R["z0"], R["height"]
    # workplane normal must point along +axis; XZ's normal is -Y, so extrude negative there
    sign = -1.0 if R["plane"] == "XZ" else 1.0
    origin = {"X": f"({z0:.4f}, 0, 0)", "Y": f"(0, {z0:.4f}, 0)", "Z": f"(0, 0, {z0:.4f})"}[ax]
    if R.get("levels"):                                       # stacked levels: sketch -> extrude per level, union
        return program_levels(R, sign), ["level"] * len(R["levels"])
    body, kinds = loop_program(R["outer"])
    lines.append(f"sketch = cq.Workplane('{R['plane']}', origin={origin}){body}")
    lines.append(f"result = sketch.extrude({sign * H:.4f})")
    for h in R["holes"]:
        hb, _ = loop_program(h)
        lines.append(f"result = result.cut(cq.Workplane('{R['plane']}', origin={origin}){hb}.extrude({sign * H:.4f}))")
    # a full round (r = H/2) cannot be filleted exactly; the part itself keeps a sliver, so stay just below
    for cap, rr in ((">", R["r_top"]), ("<", R["r_bottom"])):
        r = min(rr["outer"], H / 2 - 0.05)
        if r > 0:                                               # the outer boundary of the cap face
            lines.append(f"result = _round(result, lambda s: s.faces('{cap}{ax}').val().outerWire().Edges(), {r:.4f})")
        r = min(rr["holes"], H / 2 - 0.05)
        if r > 0:                                               # the hole mouths on that cap
            lines.append(f"result = _round(result, lambda s: [e for w in s.faces('{cap}{ax}').val().innerWires() "
                         f"for e in w.Edges()], {r:.4f})")
    return "\n".join(lines) + "\n", kinds


def program_levels(R, sign):
    ax = R["axis"]
    org = lambda z: {"X": f"({z:.4f}, 0, 0)", "Y": f"(0, {z:.4f}, 0)", "Z": f"(0, 0, {z:.4f})"}[ax]
    lines = ["# reverse.py: stacked levels, each a section sketch extruded between its two flat faces",
             "result = None"]
    for k, lv in enumerate(R["levels"]):
        for j, sh in enumerate(lv["shapes"]):
            body, _ = loop_program(sh["outer"])
            h = lv["z1"] - lv["z0"]
            lines.append(f"lv = cq.Workplane('{R['plane']}', origin={org(lv['z0'])}){body}.extrude({sign * h:.4f})")
            for hole in sh["holes"]:
                hb, _ = loop_program(hole)
                lines.append(f"lv = lv.cut(cq.Workplane('{R['plane']}', origin={org(lv['z0'])}){hb}"
                             f".extrude({sign * h:.4f}))")
            lines.append("result = lv if result is None else result.union(lv)")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    R = reverse(sys.argv[1])
    src, kinds = program(R)
    Path(sys.argv[2]).write_text(src)
    info = {k: (v if not isinstance(v, np.ndarray) else len(v)) for k, v in R.items() if k not in ("holes", "levels")}
    info["holes"] = len(R["holes"]); info["outer_primitives"] = kinds
    info["levels"] = [{"z0": lv["z0"], "z1": lv["z1"], "shapes": len(lv["shapes"])} for lv in R["levels"]]
    print(json.dumps(info, default=float))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(info, default=float, indent=1))
