"""Mirror (docs/ENGINE.md language: mirror), found in the program, never guessed: two pad/pocket features of the
same op and axis that are mirror images across the plane halfway between them (their sketch mirrored across a
plane parallel to the axis, or their extent mirrored along it). The weaker copy is replaced by the exact mirror of
the stronger one and labelled as a mirror; exact J decides which way, ties go to the mirror (the shorter
description: the owner asked for mirror features on part 3).
"""
import copy
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tree"))
import tree as T                                       # noqa: E402

PLANE = {0: "YZ", 1: "XZ", 2: "XY"}


def _poly(f):
    g = Polygon(T.loop_polygon(f["loops"][0])).buffer(0)
    for lp in f["loops"][1:]:
        g = g.difference(Polygon(T.loop_polygon(lp)).buffer(0))
    return g


def _flip_loops(loops, i, c):
    """Sketch loops mirrored across u_i = c (i = 0 or 1 in tree (u, v))."""
    def fp(p):
        q = list(p)
        q[i] = round(2 * c - q[i], 4)
        return q
    out = []
    for lp in loops:
        nl = []
        for s in lp:
            if s["t"] == "circle":
                nl.append({"t": "circle", "c": fp(s["c"]), "r": s["r"]})
            else:
                nl.append({**s, "p": [fp(p) for p in s["p"]]})
        out.append(nl)
    return out


def _span(f):
    L = f["length"]
    return (-1e9, 1e9) if L == "through" else tuple(sorted((f["at"], f["at"] + float(L))))


def mirrored(src, dst, tol, planes=()):
    """The mirror of feature src that stands where dst stands -> (feature, plane normal index) or None.
    planes: candidate mirror-plane positions per axis ({axis index: [c, ...]}) from the part's symmetry."""
    if src["op"] != dst["op"] or src.get("axis") != dst.get("axis") or "revolve" in src or "revolve" in dst \
            or "loops" not in src or "loops" not in dst:
        return None
    axis = src["axis"]
    k, (mu, mv) = T.AX[axis], T.UV[axis]
    ps, pd = _poly(src), _poly(dst)
    if ps.is_empty or pd.is_empty or abs(ps.area - pd.area) > 0.1 * max(ps.area, pd.area):
        return None
    (s0, s1), (d0, d1) = _span(src), _span(dst)
    # across a plane parallel to the axis: sketch flipped in u or v, same extent
    if abs(s0 - d0) <= tol and abs(s1 - d1) <= tol:
        cs, cd = np.array(ps.centroid.coords[0]), np.array(pd.centroid.coords[0])
        for i, n in ((0, mu), (1, mv)):
            if abs(cs[1 - i] - cd[1 - i]) > tol or abs(cs[i] - cd[i]) <= tol:
                continue
            c = (cs[i] + cd[i]) / 2
            f = dict(copy.deepcopy(src), loops=_flip_loops(src["loops"], i, c))
            if _poly(f).symmetric_difference(pd).area <= 0.1 * pd.area:
                return f, n
    # across a plane perpendicular to the axis: same sketch, extent mirrored. The counterpart may run longer
    # than the mirror (through material another feature already gives: Andrea on parts 3 and 4, "F3 like F2"),
    # so the mirror only has to lie inside it; the plane is the pair's midpoint when lengths agree, else the
    # part's symmetry planes. J confirms nothing is lost.
    if src["length"] != "through" and dst["length"] != "through" and ps.symmetric_difference(pd).area <= 0.1 * pd.area \
            and abs(s0 - d0) > tol:
        cs = [(s0 + s1 + d0 + d1) / 4] if abs((s1 - s0) - (d1 - d0)) <= tol else []
        for c in cs + list(planes.get(k, ())):
            m0, m1 = 2 * c - s1, 2 * c - s0
            if m0 >= d0 - tol and m1 <= d1 + tol:
                f = copy.deepcopy(src)
                f["at"], f["length"] = round(m0, 4), round(m1 - m0, 4)
                return f, k
    return None


def candidates(tree, tol, bounds=None):
    """Trees with one feature replaced by the mirror of another -> [(tree, description)]. bounds (the part's
    lo, hi) give the symmetry planes: the box centre on each axis, plus the plane of every mirror already found."""
    fs = tree["features"]
    planes = {}
    if bounds is not None:
        for k in range(3):
            planes.setdefault(k, []).append((float(bounds[0][k]) + float(bounds[1][k])) / 2)
    for f in fs:
        src = next((g for g in fs if g["id"] == f.get("mirror_of")), None)
        if src is not None and f.get("axis") == src.get("axis") and f["length"] != "through" and src["length"] != "through":
            k = T.AX[f["axis"]]
            planes.setdefault(k, []).append((_span(f)[0] + _span(f)[1] + _span(src)[0] + _span(src)[1]) / 4)
    mirrored_src = {f["mirror_of"] for f in fs if "mirror_of" in f}   # a mirror's source stays as drawn
    out = []
    for i, a in enumerate(fs):
        for j, b in enumerate(fs):
            if i == j or a["op"] not in ("pad", "pocket") or "mirror_of" in b or b["id"] in mirrored_src:
                continue
            r = mirrored(a, b, tol, planes)
            if r is None:
                continue
            f, n = r
            f.update(id=b["id"], mirror_of=a["id"], label=f"Mirror of {a['id']} across {PLANE[n]}")
            t = copy.deepcopy(tree)
            t["features"][j] = f
            out.append((t, f"{b['id']} = mirror of {a['id']}"))
    return out
