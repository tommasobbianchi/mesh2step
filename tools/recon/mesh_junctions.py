"""Library part 2: take a triangle mesh (STL) apart into junctions and blends (docs/JUNCTIONS.md).

    mesh_junctions.extract(stl) -> {"junctions": [...], "blends": [...]}

Same record schema and `sig` strings as tools/recon/junctions.py. Fields that cannot be known
from a mesh are approximate; kinds, curve, state and round/fillet are the contract.

Pipeline: segment the mesh into planar and analytic (cylinder/cone/torus/sphere) regions, then
classify every region boundary as a junction, then a curved region tangent to two different
neighbours is a blend.
"""
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feature_recon"))
from slice import fit_circle, load

_BLEND_KINDS = ("cylinder", "cone", "torus", "sphere")
_SMOOTH = np.cos(np.radians(40.0))       # smooth component link: below this is a sharp edge
_PLANE_COS = np.cos(np.radians(0.8))     # coplanar neighbour link
_TANGENT_DEG = 2.0                       # docs: tangent == normals agree within 2 degrees
_TURN_DEG = 5.0                          # straight-segment split on a boundary polyline


# ---------------------------------------------------------------- mesh plumbing

def _topology(tri):
    """Unique vertices, triangles, manifold triangle adjacency, bounding diagonal."""
    diag = float(np.linalg.norm(tri.reshape(-1, 3).max(0) - tri.reshape(-1, 3).min(0)))
    diag = max(diag, 1e-9)
    keys = np.round(tri.reshape(-1, 3) / (diag * 1e-7)).astype(np.int64)
    _, vid = np.unique(keys, axis=0, return_inverse=True)
    F = vid.reshape(-1, 3)
    V = np.zeros((int(F.max()) + 1, 3))
    V[F.reshape(-1)] = tri.reshape(-1, 3)
    e = np.sort(np.stack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 1).reshape(-1, 2), 1)
    owner = np.repeat(np.arange(len(F)), 3)
    order = np.lexsort((e[:, 1], e[:, 0]))
    e, owner = e[order], owner[order]
    same = np.all(e[1:] == e[:-1], 1)
    nb = [[] for _ in range(len(F))]
    for i in np.where(same)[0]:
        if (i + 1 < len(same) and same[i + 1]) or (i > 0 and same[i - 1]):
            continue                          # non-manifold edge: no adjacency through it
        a, b = owner[i], owner[i + 1]
        nb[a].append(b)
        nb[b].append(a)
    return V, F, nb, diag


def _grow(seed, nb, ok, label, lab):
    stack = list(seed)
    region = []
    for t in seed:
        label[t] = lab
    while stack:
        t = stack.pop()
        region.append(t)
        for u in nb[t]:
            if label[u] < 0 and ok(u):
                label[u] = lab
                stack.append(u)
    return region


def _dry_grow(seed, nb, ok):
    region = set(seed)
    stack = list(seed)
    while stack:
        t = stack.pop()
        for u in nb[t]:
            if u not in region and ok(u):
                region.add(u)
                stack.append(u)
    return list(region)


# ---------------------------------------------------------------- planar regions

def _plane_regions(V, F, nb, n, area, diag, label, kinds):
    tol = max(1e-5 * diag, 1e-6)
    min_area = (0.04 * diag) ** 2     # a cluster this small is a facet of a curved surface
    for s in np.argsort(-area):
        if label[s] >= 0 or area[s] <= 0:
            continue
        ns = n[s].copy()
        ds = float(ns @ V[F[s, 0]])

        def ok(t, ns=ns, ds=ds):
            return bool(n[t] @ ns > _PLANE_COS and np.abs(V[F[t]] @ ns - ds).max() <= tol)

        reg = _grow([s], nb, ok, label, len(kinds))
        if area[reg].sum() < min_area:          # leave it for the curved segmentation
            for t in reg:
                label[t] = -1
            continue
        kinds.append({"kind": "plane", "tris": reg, "normal": ns, "point": ds})
    return kinds


# ---------------------------------------------------------------- surface of revolution

def _axis_residual(X, D, w, d):
    """Squared residual of `d` being a SOR axis: the normal lines must meet it.
    For each normal line (X, D) the closest point on the axis obeys (X - c).(D x d) = 0."""
    q = np.cross(D, d)
    good = np.linalg.norm(q, axis=1) > 1e-9
    if good.sum() < 2:
        return np.inf, None
    A = q[good] * np.sqrt(w[good])[:, None]
    b = np.einsum("ij,ij->i", X[good], q[good]) * np.sqrt(w[good])
    c = np.linalg.lstsq(A, b, rcond=None)[0]
    r = A @ c - b
    return float(r @ r), c


def _sor_axis(comp, V, F, n, area):
    """Robust SOR axis: the direction that makes all normal lines concurrent (Pottmann/Randrup).
    A coarse direction search plus a local refine avoids the degenerate line-complex solutions
    a plain eigen-solve returns for a pure cylinder."""
    from scipy.optimize import minimize
    X = V[F[comp]].mean(1)
    D = n[comp]
    w = area[comp]
    # the direction search is O(candidates * lines): subsample large components, refine, then
    # recover the axis offset on the full set.
    if len(X) > 4000:
        idx = np.linspace(0, len(X) - 1, 4000).astype(int)
        Xs, Ds, ws = X[idx], D[idx], w[idx]
    else:
        Xs, Ds, ws = X, D, w
    # candidates: normal-covariance axes (cylinder/cone) plus a Fibonacci sphere
    _, evec = np.linalg.eigh(np.cov(Ds.T, aweights=ws))
    cands = [evec[:, k] for k in range(3)]
    ga = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(120):
        z = 1.0 - 2.0 * (i + 0.5) / 120.0
        r = math.sqrt(max(0.0, 1.0 - z * z))
        t = ga * i
        cands.append(np.array([r * math.cos(t), r * math.sin(t), z]))
    best = None
    for d in cands:
        nd = np.linalg.norm(d)
        if nd < 1e-9:
            continue
        d = d / nd
        res, _ = _axis_residual(Xs, Ds, ws, d)
        if best is None or res < best[0]:
            best = (res, d)
    if best is None:
        return None
    _, d0 = best
    e1 = np.cross(d0, [0.0, 0.0, 1.0])
    if np.linalg.norm(e1) < 1e-6:
        e1 = np.cross(d0, [1.0, 0.0, 0.0])
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.cross(d0, e1)

    def obj(ab):
        d = d0 + ab[0] * e1 + ab[1] * e2
        d /= np.linalg.norm(d)
        return _axis_residual(X, D, w, d)[0]

    opt = minimize(obj, [0.0, 0.0], method="Nelder-Mead",
                   options={"xatol": 1e-6, "fatol": 1e-12, "maxiter": 400})
    d = d0 + opt.x[0] * e1 + opt.x[1] * e2
    d /= np.linalg.norm(d)
    res, c = _axis_residual(X, D, w, d)
    if c is None:
        return None
    return d, c - (c @ d) * d


def _fit_sphere(comp, V, F, n, area, diag):
    X = V[F[comp]].mean(1)
    D = n[comp]
    w = area[comp]
    M = np.eye(3)[None] - np.einsum("ij,ik->ijk", D, D)
    A = np.einsum("i,ijk->jk", w, M)
    b = np.einsum("i,ijk,ik->j", w, M, X)
    c = np.linalg.lstsq(A, b, rcond=None)[0]
    P = V[np.unique(F[comp])]
    R = float(np.median(np.linalg.norm(P - c, axis=1)))
    if np.abs(np.linalg.norm(P - c, axis=1) - R).max() <= 5e-3 * diag and R < diag:
        return c, R
    return None


def _meridian_models(hh, rr, diag, tol):
    """Analytic candidates for a meridian profile, best (most curved) first."""
    out = []
    line_ok = False
    if len(hh) >= 2 and float(np.ptp(hh)) > 1e-9:
        a, b = np.polyfit(hh, rr, 1)
        if np.abs(np.polyval([a, b], hh) - rr).max() <= tol:
            line_ok = True
            if abs(a) > 0.05:
                out.append({"kind": "cone", "a": float(a), "b": float(b)})
            else:
                out.append({"kind": "cylinder", "R": float(np.median(rr))})
    elif len(hh):
        out.append({"kind": "cylinder", "R": float(np.median(rr))})
    cc, r, dev = fit_circle(np.c_[hh, rr])
    if dev <= tol and 1e-2 * diag < r < diag:
        if abs(cc[1]) < max(tol, 1e-4 * diag):
            out.append({"kind": "sphere", "h0": float(cc[0]), "R": float(r)})
        else:
            out.append({"kind": "torus", "h0": float(cc[0]), "R0": float(cc[1]), "r": float(r)})
    if not line_ok:
        out.append({"kind": "cylinder", "R": float(np.median(rr))})
    return out


def _meridian_on(model, hh, rr):
    k = model["kind"]
    if k == "cylinder":
        return np.abs(rr - model["R"])
    if k == "cone":
        return np.abs(np.polyval([model["a"], model["b"]], hh) - rr)
    if k == "sphere":
        return np.abs(np.hypot(hh - model["h0"], rr) - model["R"])
    return np.abs(np.hypot(hh - model["h0"], rr - model["R0"]) - model["r"])


def _sor_regions(comp, ax, c, V, F, nb, n, area, diag, label, kinds):
    q = V - c
    h = q @ ax
    rad = q - np.outer(h, ax)
    rho = np.linalg.norm(rad, axis=1)
    compset = set(comp)
    tol = max(1e-3 * diag, 1e-5)
    assigned = set()
    tried = set()

    def ring(seed):
        r = [seed]
        seen = {seed}
        frontier = [seed]
        for _ in range(4):
            nxt = []
            for t in frontier:
                for u in nb[t]:
                    if u in compset and u not in seen:
                        seen.add(u)
                        nxt.append(u)
            r += nxt
            frontier = nxt
        return r

    def make_on(model):
        return lambda t: _meridian_on(model, h[F[t]], rho[F[t]]).max() <= tol

    for s in sorted(comp, key=lambda t: -area[t]):
        if s in assigned or s in tried:
            continue
        tried.add(s)
        pts = np.unique(F[ring(s)])
        models = _meridian_models(h[pts], rho[pts], diag, tol)
        best = None
        for model in models:
            on = make_on(model)
            start = [t for t in ring(s) if on(t)] or [s]
            start = [t for t in start if t not in assigned]
            if not start:
                continue
            reg = _dry_grow(start, nb,
                            lambda u, on=on: u in compset and u not in assigned and on(u))
            if best is None or len(reg) > len(best[1]):
                best = (model, reg)
        if best is None or len(best[1]) < 1:
            continue
        model, reg = best
        assigned.update(reg)
        for t in reg:
            label[t] = len(kinds)
        k = model["kind"]
        if k == "cylinder":
            kinds.append({"kind": "cylinder", "tris": reg, "radius": model["R"], "ax": ax, "c": c})
        elif k == "cone":
            ang = float(np.degrees(np.arctan(abs(model["a"]))))
            kinds.append({"kind": "cone", "tris": reg, "radius": None, "angle": ang,
                          "ax": ax, "c": c, "a": model["a"], "b": model["b"]})
        elif k == "sphere":
            kinds.append({"kind": "sphere", "tris": reg, "radius": model["R"],
                          "center": c + model["h0"] * ax, "ax": ax, "c": c, "h0": model["h0"]})
        else:
            kinds.append({"kind": "torus", "tris": reg, "radius": model["r"], "minor": model["r"],
                          "ax": ax, "c": c, "h0": model["h0"], "R0": model["R0"]})
    left = [t for t in comp if t not in assigned]
    if left:
        for t in left:
            label[t] = len(kinds)
        kinds.append({"kind": "other", "tris": left})
    return kinds


def _curved_regions(V, F, nb, n, area, diag, label, kinds):
    free = set(np.where(label < 0)[0])
    seen = set()
    for s0 in list(free):
        if s0 in seen:
            continue
        comp, stack = [], [s0]
        seen.add(s0)
        while stack:
            t = stack.pop()
            comp.append(t)
            for u in nb[t]:
                if u in free and u not in seen and n[t] @ n[u] > _SMOOTH:
                    seen.add(u)
                    stack.append(u)
        axc = _sor_axis(comp, V, F, n, area)
        if axc is not None:
            _sor_regions(comp, axc[0], axc[1], V, F, nb, n, area, diag, label, kinds)
            continue
        sph = _fit_sphere(comp, V, F, n, area, diag) if len(comp) >= 6 else None
        if sph is not None:
            for t in comp:
                label[t] = len(kinds)
            kinds.append({"kind": "sphere", "tris": comp, "radius": sph[1], "center": sph[0]})
        else:
            for t in comp:
                label[t] = len(kinds)
            kinds.append({"kind": "other", "tris": comp})
    return kinds


# ---------------------------------------------------------------- region geometry

def _centroid(reg, V, F, area):
    ts = reg["tris"]
    c = V[F[ts]].mean(1)
    w = area[ts]
    return (c * w[:, None]).sum(0) / max(w.sum(), 1e-30)


def _normal_at(reg, p):
    k = reg["kind"]
    if k == "plane":
        return reg["normal"]
    if k == "cylinder":
        q = p - reg["c"]
        r = q - (q @ reg["ax"]) * reg["ax"]
        nr = np.linalg.norm(r)
        if nr < 1e-12:
            return None
        return r / nr
    if k == "sphere":
        d = p - reg["center"]
        nd = np.linalg.norm(d)
        return d / nd if nd > 1e-12 else None
    if k == "torus":
        q = p - reg["c"]
        hh = q @ reg["ax"]
        rv = q - hh * reg["ax"]
        nr = np.linalg.norm(rv)
        if nr < 1e-12:
            return None
        s = reg["c"] + reg["h0"] * reg["ax"] + reg["R0"] * (rv / nr)
        d = p - s
        nd = np.linalg.norm(d)
        return d / nd if nd > 1e-12 else None
    if k == "cone":
        q = p - reg["c"]
        hh = q @ reg["ax"]
        rv = q - hh * reg["ax"]
        nr = np.linalg.norm(rv)
        if nr < 1e-12:
            return None
        ru = rv / nr
        a = reg["a"]
        return (ru - a * reg["ax"]) / np.sqrt(1.0 + a * a)
    return None


def _region_orientation(reg, V, F, n):
    if reg["kind"] == "plane":
        return reg["normal"], 1.0
    ts = reg["tris"][: min(len(reg["tris"]), 200)]
    pts = V[F[ts]].mean(1)
    acc = np.zeros(3)
    for p, mn in zip(pts, n[ts], strict=False):
        na = _normal_at(reg, p)
        if na is not None:
            acc += na * np.sign(na @ mn)
    if np.linalg.norm(acc) < 1e-9:
        return None, 1.0
    ref = acc / np.linalg.norm(acc)
    na = _normal_at(reg, pts[0])
    if na is None:
        return None, 1.0
    return ref, float(np.sign(ref @ na)) or 1.0


def _round_sign(reg, p, nrm, V, F, n):
    """True when the blend's defining curvature is convex (a round), False a fillet."""
    k = reg["kind"]
    ax = reg.get("ax")
    if k == "sphere":
        t = np.cross(nrm, [1.0, 0.0, 0.0])
        if np.linalg.norm(t) < 1e-6:
            t = np.cross(nrm, [0.0, 1.0, 0.0])
        w = t / np.linalg.norm(t)
    elif k == "cylinder":
        w = np.cross(ax, nrm)
        if np.linalg.norm(w) < 1e-9:
            return False
        w = w / np.linalg.norm(w)
    else:
        q = p - reg["c"]
        hh = q @ reg["ax"]
        rv = q - hh * reg["ax"]
        if np.linalg.norm(rv) < 1e-9:
            return False
        ru = rv / np.linalg.norm(rv)
        az = np.cross(reg["ax"], ru)
        w = np.cross(az, nrm)
        if np.linalg.norm(w) < 1e-9:
            return False
        w = w / np.linalg.norm(w)
    eps = max(1e-4, 1e-3 * float(np.linalg.norm(V.max(0) - V.min(0))))
    q = p + eps * w
    n0, nq = _normal_at(reg, p), _normal_at(reg, q)
    if nq is None or n0 is None:
        return False
    sign = 1.0 if float(n0 @ nrm) >= 0.0 else -1.0   # match the supplied outward normal
    return bool((sign * nq - nrm) @ (eps * w) > 0.0)


# ---------------------------------------------------------------- boundaries

def _pair_edges(F, nb, rlabel):
    pairs = defaultdict(dict)
    for t in range(len(F)):
        i = int(rlabel[t])
        if i < 0:
            continue
        ft = set(F[t].tolist())
        for u in nb[t]:
            j = int(rlabel[u])
            if j < 0 or j == i:
                continue
            sh = ft & set(F[u].tolist())
            if len(sh) != 2:
                continue
            a, b = sorted(sh)
            pairs[(min(i, j), max(i, j))][(a, b)] = (t, u) if i < j else (u, t)
    return pairs


def _trace(path_edges):
    inc = defaultdict(list)
    for idx, (a, b) in enumerate(path_edges):
        inc[a].append((b, idx))
        inc[b].append((a, idx))
    used = [False] * len(path_edges)
    paths = []
    for idx in range(len(path_edges)):
        if used[idx]:
            continue
        a, b = path_edges[idx]
        used[idx] = True
        path = [a, b]
        for forward in (True, False):
            cur, prev = (path[-1], path[-2]) if forward else (path[0], path[1])
            while True:
                nxt = None
                for v, j in inc[cur]:
                    if not used[j] and v != prev:
                        nxt = (v, j)
                        break
                if nxt is None:
                    break
                v, j = nxt
                used[j] = True
                if forward:
                    path.append(v)
                else:
                    path.insert(0, v)
                prev, cur = cur, v
        paths.append(path)
    return paths


def _circle3d(P):
    c0 = P.mean(0)
    _, sv, vt = np.linalg.svd(P - c0, full_matrices=False)
    if sv[0] < 1e-12:
        return None
    u, v = vt[0], vt[1]
    cc, r, dev = fit_circle(np.c_[(P - c0) @ u, (P - c0) @ v])
    axis = np.cross(u, v)
    center = c0 + cc[0] * u + cc[1] * v
    return center, axis / np.linalg.norm(axis), float(r), float(dev), float(sv[2] / sv[0])


def _split_straight(P):
    """Split a polyline into maximal straight runs (corner at a direction change)."""
    if len(P) < 3:
        return [P]
    segs = []
    start = 0
    for i in range(1, len(P) - 1):
        d1 = P[i] - P[i - 1]
        d2 = P[i + 1] - P[i]
        n1, n2 = np.linalg.norm(d1), np.linalg.norm(d2)
        if n1 < 1e-12 or n2 < 1e-12:
            continue
        ang = np.degrees(np.arccos(np.clip((d1 / n1) @ (d2 / n2), -1, 1)))
        if ang > _TURN_DEG:
            segs.append(P[start:i + 1])
            start = i
    segs.append(P[start:])
    return [s for s in segs if len(s) >= 2]


def _classify_curve(P, closed, diag):
    """Return list of (curve, radius, center, axis) pieces for one boundary polyline."""
    length = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
    if length < 1e-9:
        return []
    cres = _circle3d(P) if len(P) >= 3 else None
    if closed:
        if cres and cres[3] <= 0.05 * cres[2] and cres[2] < diag:
            return [("circle", cres[2], P[len(P) // 2], cres[1])]
        return [("other", None, P[len(P) // 2], None)]
    # open: straight?
    c0 = P.mean(0)
    _, sv, _ = np.linalg.svd(P - c0, full_matrices=False)
    line_dev = float(sv[1] / np.sqrt(len(P))) if len(P) >= 2 else 0.0
    if line_dev <= 0.01 * length:
        return [("line", None, P[len(P) // 2], None)]
    if cres and cres[3] <= 0.05 * cres[2] and cres[2] < diag:
        return [("circle", cres[2], P[len(P) // 2], cres[1])]
    out = []
    for seg in _split_straight(P):
        if len(seg) >= 2:
            out.append(("line", None, seg[len(seg) // 2], None))
    return out


def _pair_tangent(ra, rb, diag):
    """Geometric tangency of two fitted surfaces: exact where the kinds allow it, None otherwise.
    (At a mesh split the boundary sits a tolerance off the true tangent line, so the measured
    normal jump overstates the angle; the surfaces themselves tell the truth.)"""
    ka, kb = ra["kind"], rb["kind"]
    if ka == "plane" and kb == "plane":
        return False
    tol = max(2e-3 * diag, 1e-4)
    par = 0.02                       # fitted axes are parallel to ~1 deg

    def plane_cyl(pl, cy):
        if abs(float(pl["normal"] @ cy["ax"])) > par:
            return False
        d = abs(float(pl["point"]) - float(pl["normal"] @ cy["c"]))
        return abs(d - cy["radius"]) <= tol

    def plane_torus(pl, to):
        if abs(abs(float(pl["normal"] @ to["ax"])) - 1.0) > par:
            return False
        hp = float(pl["point"]) * float(pl["normal"] @ to["ax"]) - float(to["c"] @ to["ax"])
        return abs(abs(hp - to["h0"]) - to["radius"]) <= tol

    def cyl_torus(cy, to):
        if abs(float(cy["ax"] @ to["ax"])) < 1.0 - par:
            return False
        off = np.linalg.norm((cy["c"] - to["c"]) - ((cy["c"] - to["c"]) @ cy["ax"]) * cy["ax"])
        d = min(abs(cy["radius"] - (to["R0"] - to["radius"])),
                abs(cy["radius"] - (to["R0"] + to["radius"])))
        return off <= tol and d <= tol

    if {ka, kb} == {"plane", "cylinder"}:
        pl, cy = (ra, rb) if ka == "plane" else (rb, ra)
        return plane_cyl(pl, cy)
    if {ka, kb} == {"plane", "torus"}:
        pl, to = (ra, rb) if ka == "plane" else (rb, ra)
        return plane_torus(pl, to)
    if {ka, kb} == {"cylinder", "torus"}:
        cy, to = (ra, rb) if ka == "cylinder" else (rb, ra)
        return cyl_torus(cy, to)
    return None


def _axis_matches(caxis, region):
    ax = region.get("ax")
    if ax is None or caxis is None:
        return None
    if abs(float(caxis @ ax)) < 1.0 - 1e-4:
        return False
    return True


# ---------------------------------------------------------------- junctions

def _boundary_rec(regionA, regionB, path, owner_edges, V, F, n, diag, nA_dir, nB_dir, tang=None):
    P = V[path]
    closed = path[0] == path[-1]
    pieces = _classify_curve(P, closed, diag)
    recs = []
    for curve, radius, centre, caxis in pieces:
        mid = centre
        na = _normal_at(regionA, mid)
        nb_ = _normal_at(regionB, mid)
        if na is None or nb_ is None:
            continue
        if nA_dir is not None:
            na = na * nA_dir
        if nB_dir is not None:
            nb_ = nb_ * nB_dir
        measured = float(np.degrees(np.arccos(np.clip(na @ nb_, -1, 1))))
        tangent = (measured <= _TANGENT_DEG) if tang is None else tang
        angle = 0.0 if tangent else measured
        if tangent:
            state, convex = "tangent", None
        else:
            vals = []
            for idx in range(len(path) - 1):
                key = tuple(sorted((int(path[idx]), int(path[idx + 1]))))
                oe = owner_edges.get(key)
                if oe is None:
                    continue
                tA, _ = oe
                sh = sorted(set(F[tA].tolist()) & set(F[oe[1]].tolist()))
                if len(sh) != 2:
                    continue
                m = (V[sh[0]] + V[sh[1]]) / 2.0
                pB = V[next(v for v in F[oe[1]] if v not in sh)]
                vals.append(float((pB - m) @ n[tA]))
            convex = (np.median(vals) < 0) if vals else True
            state = "convex" if convex else "concave"
        ka, kb = regionA["kind"], regionB["kind"]
        a, b = (ka, kb) if ka <= kb else (kb, ka)
        coaxial = None
        if curve == "circle" and caxis is not None:
            c1 = _axis_matches(caxis, regionA)
            c2 = _axis_matches(caxis, regionB)
            coaxial = True if (c1 or c2) else (None if c1 is None and c2 is None else False)
        length = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
        recs.append({
            "a": a, "b": b, "curve": curve, "tangent": tangent, "convex": convex,
            "angle": angle, "radius": radius, "coaxial": coaxial,
            "centre": [float(x) for x in centre],
            "length": length,
            "sig": f"{a}|{b}|{curve}|{state}",
        })
    return recs


def _blend_records(kinds, pairs, V, F, n, area, label, diag, tang_pairs):
    # tangent neighbours per region id, with one boundary point on the blend
    tang = defaultdict(dict)
    for (i, j), owned in pairs.items():
        ri, rj = kinds[i], kinds[j]
        key = next(iter(owned))
        p = (V[key[0]] + V[key[1]]) / 2.0
        is_tang = tang_pairs.get((i, j))
        if is_tang is None:
            na = _normal_at(ri, p)
            nb_ = _normal_at(rj, p)
            if na is None or nb_ is None:
                continue
            angle = float(np.degrees(np.arccos(np.clip(na @ nb_, -1, 1))))
            is_tang = angle <= _TANGENT_DEG
        if is_tang:
            tang[i][j] = p
            tang[j][i] = p
    blends = []
    for i, reg in enumerate(kinds):
        if reg["kind"] not in _BLEND_KINDS or "radius" not in reg or reg["radius"] is None:
            continue
        nbrs = list(tang.get(i, {}).keys())
        if len(nbrs) < 2:
            continue
        j1, j2 = nbrs[0], nbrs[1]
        p = tang[i][j1]
        nrm = _normal_at(reg, p)
        if nrm is None:
            continue
        _, sgn = _region_orientation(reg, V, F, n)
        nrm = nrm * sgn
        is_round = _round_sign(reg, p, nrm, V, F, n)
        between = "+".join(sorted((kinds[j1]["kind"], kinds[j2]["kind"])))
        centre = _centroid(reg, V, F, area)
        blends.append({
            "blend": reg["kind"], "between": between, "round": bool(is_round),
            "radius": float(reg["radius"]), "centre": [float(x) for x in centre],
            "sig": f"blend:{reg['kind']}|{between}|{'round' if is_round else 'fillet'}",
        })
    return blends


# ---------------------------------------------------------------- entry point

def extract(stl_path):
    tri = load(stl_path)
    V, F, nb, diag = _topology(tri)
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(nrm, axis=1) / 2.0
    n = nrm / np.maximum(2.0 * area[:, None], 1e-30)

    label = -np.ones(len(F), int)
    kinds = []
    _plane_regions(V, F, nb, n, area, diag, label, kinds)
    _curved_regions(V, F, nb, n, area, diag, label, kinds)

    # orient each region's analytic normal to agree with its mesh normals
    for reg in kinds:
        ref, sgn = _region_orientation(reg, V, F, n)
        if ref is not None:
            reg["_ref"] = ref
            reg["_sgn"] = sgn
        else:
            reg["_ref"] = reg.get("normal")
            reg["_sgn"] = 1.0

    pairs = _pair_edges(F, nb, label)
    tang_pairs = {key: _pair_tangent(kinds[key[0]], kinds[key[1]], diag) for key in pairs}
    junctions = []
    for (i, j), owned in pairs.items():
        ra, rb = kinds[i], kinds[j]
        paths = _trace(list(owned.keys()))
        for path in paths:
            junctions += _boundary_rec(ra, rb, path, owned, V, F, n, diag,
                                       ra.get("_sgn"), rb.get("_sgn"), tang_pairs.get((i, j)))
    blends = _blend_records(kinds, pairs, V, F, n, area, label, diag, tang_pairs)
    return {"junctions": junctions, "blends": blends}


if __name__ == "__main__":
    import json
    import sys as _sys
    for p in _sys.argv[1:]:
        r = extract(p)
        print(json.dumps(r, indent=2))
