"""Sketch arcs from evidence (docs/ENGINE.md section 3: profiles fitted with lines and arcs whose radii come from
the evidence): in every pad/pocket loop, a run of consecutive segments lying on an evidence circle (a cylinder
along the extrusion axis) becomes one exact arc of that circle. Applied to a finished program; run.py keeps it
only if J holds.
"""
import copy
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tree"))
import evidence as E                                   # noqa: E402
import tree as T                                       # noqa: E402


def circles(shape, axis):
    """Evidence circles on sketch planes across `axis`, in tree (u, v): [(centre, radius)]."""
    k, (mu, mv) = T.AX[axis], T.UV[axis]
    out = []
    for r in E.surfaces(shape):
        if r["kind"] == "cylinder" and abs(r["axis"][k]) > 0.999:
            o = r["origin"]
            out.append((np.array([o[mu], o[mv]]), r["radius"]))
    return out


def _on(p, c, r, tol):
    return abs(np.linalg.norm(np.asarray(p) - c) - r) <= tol


def snap_loop(loop, circs, tol):
    """Runs of >= 2 segments whose ends all lie on one circle -> one arc through its middle point."""
    if len(loop) < 3 or any(s["t"] == "circle" for s in loop):
        return loop
    ends = [(s["p"][0], s["p"][-1]) for s in loop]
    out, i, n = [], 0, len(loop)
    while i < n:
        best = None
        for c, r in circs:
            j = i
            while j < n and loop[j]["t"] in ("line", "arc") and _on(ends[j][0], c, r, tol) and _on(ends[j][1], c, r, tol):
                j += 1
            if j - i >= 2 and (best is None or j - i > best[0]):
                best = (j - i, c, r)
        if best is None:
            out.append(loop[i])
            i += 1
            continue
        m, c, r = best
        a, b = np.asarray(ends[i][0], float), np.asarray(ends[i + m - 1][1], float)
        mid_seg = loop[i + m // 2]["p"][0]               # a point of the run near its middle, pushed onto the circle
        q = np.asarray(mid_seg, float) - c
        q = c + r * q / (np.linalg.norm(q) or 1.0)
        rr = lambda p: [round(float(p[0]), 4), round(float(p[1]), 4)]
        out.append({"t": "arc", "p": [rr(a), rr(q), rr(b)]})
        i += m
    return out


def snap(tree, shape, tol):
    t = copy.deepcopy(tree)
    changed = 0
    for f in t["features"]:
        if f["op"] not in ("pad", "pocket") or "revolve" in f or "loops" not in f:
            continue
        cs = circles(shape, f["axis"])
        if not cs:
            continue
        new = [snap_loop(lp, cs, tol / 4) for lp in f["loops"]]
        changed += sum(len(a) != len(b) for a, b in zip(new, f["loops"]))
        f["loops"] = new
    return t, changed
