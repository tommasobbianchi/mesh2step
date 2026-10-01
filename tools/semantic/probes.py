"""S3 probe toolbox: deterministic measurements on a trimesh.Trimesh in millimetres."""
import copy
from collections import defaultdict

import numpy as np

_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
_AXIS_NORMAL = {"X": [1, 0, 0], "Y": [0, 1, 0], "Z": [0, 0, 1]}
_AXIS_COORDS = {"Z": [0, 1], "Y": [2, 0], "X": [1, 2]}


def bbox(mesh):
    """Return bounding box as min, max, size in plain float lists."""
    b = mesh.bounds
    mn = [float(v) for v in b[0]]
    mx = [float(v) for v in b[1]]
    sz = [mx[i] - mn[i] for i in range(3)]
    return {"min": mn, "max": mx, "size": sz}


def thickness(mesh, axis):
    """Return the part's extent along the given axis."""
    return bbox(mesh)["size"][_AXIS_INDEX[axis]]


def section_loops(mesh, axis, frac):
    """Return closed loops of the section plane cut as (N,2) arrays in the two remaining world coords."""
    b = bbox(mesh)
    idx = _AXIS_INDEX[axis]
    origin = [b["min"][i] + frac * b["size"][i] for i in range(3)]
    normal = _AXIS_NORMAL[axis]

    sec = mesh.section(plane_origin=origin, plane_normal=normal)
    if sec is None:
        return []

    ci = _AXIS_COORDS[axis]
    return [np.asarray(p, dtype=float)[:, ci] for p in sec.discrete]


def _kasa_fit(pts):
    """Algebraic Kasa circle fit; returns (center, radius) or (None, 0.0)."""
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones_like(x)])
    b = -(x * x + y * y)
    sol, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    D, E, F = sol
    cx, cy = -D / 2.0, -E / 2.0
    r2 = cx * cx + cy * cy - F
    if r2 <= 0:
        return None, 0.0
    return np.array([cx, cy]), float(np.sqrt(r2))


def section_circles(mesh, axis, frac, tol=0.02):
    """Return circles in the section, excluding the outer outline unless it is the only loop."""
    loops = section_loops(mesh, axis, frac)
    if not loops:
        return []

    fits = []
    for lp in loops:
        c, r = _kasa_fit(lp)
        if c is None:
            continue
        dists = np.sqrt((lp[:, 0] - c[0]) ** 2 + (lp[:, 1] - c[1]) ** 2)
        rms = float(np.sqrt(np.mean((dists - r) ** 2)))
        fits.append((c, r, rms, lp))

    if not fits:
        return []

    if len(fits) > 1:
        def _area(lp):
            x, y = lp[:, 0], lp[:, 1]
            return 0.5 * abs(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))
        max_i = max(range(len(fits)), key=lambda i: _area(fits[i][3]))
        fits = [f for i, f in enumerate(fits) if i != max_i]

    out = []
    for c, r, rms, _ in fits:
        if rms < tol * r:
            out.append({"c": [float(c[0]), float(c[1])], "d": float(2.0 * r)})
    return out


def count_holes(mesh, axis):
    """Return the number of circular holes along the given axis, cutting at several heights."""
    b = bbox(mesh)
    diag = float(np.linalg.norm(b["size"]))
    tol = 0.02 * diag
    centres = []
    for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        for c in section_circles(mesh, axis, frac):
            centres.append(c["c"])
    count = 0
    used = []
    for c in centres:
        if all(float(np.linalg.norm(np.array(c) - np.array(u))) > tol for u in used):
            count += 1
            used.append(c)
    return count


def revolve_axis(mesh):
    """Return the axis of revolution if the part is a solid of revolution, else None."""
    b = bbox(mesh)
    diag = float(np.linalg.norm(b["size"]))
    tol_c = 0.01 * diag

    for axis in ("X", "Y", "Z"):
        loops = section_loops(mesh, axis, 0.5)
        if not loops:
            continue
        centers = []
        ok = True
        for lp in loops:
            c, r = _kasa_fit(lp)
            if c is None:
                ok = False
                break
            dists = np.sqrt((lp[:, 0] - c[0]) ** 2 + (lp[:, 1] - c[1]) ** 2)
            rms = float(np.sqrt(np.mean((dists - r) ** 2)))
            if rms >= 0.02 * r:
                ok = False
                break
            centers.append(c)
        if not ok or not centers:
            continue
        ref = centers[0]
        if all(float(np.linalg.norm(c - ref)) < tol_c for c in centers):
            return axis
    return None


def normalize_plan(plan):
    """Return a deep copy of plan with undo sorted by stage and steps renumbered 1..n."""
    out = copy.deepcopy(plan)
    order = {"finish": 0, "subtractive": 1, "additive": 2}
    out["undo"].sort(key=lambda u: order.get(u.get("stage", ""), 3))
    for i, u in enumerate(out["undo"], 1):
        u["step"] = i
    return out
