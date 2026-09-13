"""Recursive region growing into CAD faces (planar merge: Tommaso Bianchi; quad seeds: Davide Albertini;
hierarchy after Attene et al. 2006). No vertex is ever removed: triangles are only GROUPED.
1. curved seeds = quads.py cylinder patches; each is refit on its vertices (tessellation vertices lie ON the
   true surface), rejected if they do not, and grown over neighbours whose 3 vertices sit on the cylinder;
2. planar regions = grown from the largest unassigned triangle over coplanar neighbours (seed plane, no drift);
   a 1-2 triangle "plane" meeting every neighbour at a smooth angle is a facet of a curved surface, not a face;
3. leftover smooth facets (fan-tessellated cones, spheres, cylinders) are grouped by smooth adjacency and
   fitted on their vertices: normals at a constant angle to an axis -> cylinder / cone; normal lines through
   one point -> sphere. Accepted only if every vertex lies on the fitted surface.
usage: python3 regions.py <stl> [...]"""
import collections, math, os, sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import fit_circle, load
from quads import classify

SMOOTH = math.cos(math.radians(40))   # a 45 deg chamfer edge is sharp


def mesh_topology(tri):
    diag = float(np.linalg.norm(tri.reshape(-1, 3).max(0) - tri.reshape(-1, 3).min(0)))
    keys = np.round(tri.reshape(-1, 3) / (diag * 1e-7)).astype(np.int64)
    _, vid = np.unique(keys, axis=0, return_inverse=True)
    F = vid.reshape(-1, 3)
    V = np.zeros((F.max() + 1, 3)); V[F.reshape(-1)] = tri.reshape(-1, 3)
    e = np.sort(np.stack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 1).reshape(-1, 2), 1)
    owner = np.repeat(np.arange(len(F)), 3)
    order = np.lexsort((e[:, 1], e[:, 0])); e, owner = e[order], owner[order]
    same = np.all(e[1:] == e[:-1], 1)
    nb = [[] for _ in range(len(F))]
    for i in np.where(same)[0]:
        if (i + 1 < len(same) and same[i + 1]) or (i > 0 and same[i - 1]):
            continue          # non-manifold edge: no adjacency through it
        a, b = owner[i], owner[i + 1]; nb[a].append(b); nb[b].append(a)
    return V, F, nb, diag


def grow(seed, nb, ok, label, lab):
    stack = list(seed); region = []
    for t in seed:
        label[t] = lab
    while stack:
        t = stack.pop(); region.append(t)
        for u in nb[t]:
            if label[u] < 0 and ok(u):
                label[u] = lab; stack.append(u)
    return region


def dry_grow(seed, nb, ok):
    """grow() without writing labels: the region a candidate surface WOULD claim."""
    region = set(seed); stack = list(seed)
    while stack:
        t = stack.pop()
        for u in nb[t]:
            if u not in region and ok(u):
                region.add(u); stack.append(u)
    return list(region)


def frame(ax):
    u = np.cross(ax, [1, 0, 0] if abs(ax[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u)
    return u, np.cross(ax, u)


def fit_smooth(ts, V, F, n, area, tol):
    """Cylinder / cone / sphere from a smooth facet group, with the geometry to test more facets against;
    None unless every vertex is on the surface. Tried before the torus fit: for these three the line-complex
    fit has a multi-dimensional solution space and its axis is arbitrary."""
    ts = list(ts)
    P = V[np.unique(F[ts])]; N = n[ts]; w = area[ts]
    if len(ts) < 3:
        return None
    evm, vecm = np.linalg.eigh((N * w[:, None]).T @ N / w.sum())
    if math.sqrt(max(evm[0], 0)) < 0.02:
        ax = vecm[:, 0]; u, v = frame(ax); c2, R, dev = fit_circle(np.c_[P @ u, P @ v])
        if dev <= 5 * tol:
            return ("cylinder", round(float(R), 4), (ax, c2[0] * u + c2[1] * v))
    # cone: n.axis is constant -> a null direction of the centred covariance; a small patch has a second one
    # (its mean normal), so every null candidate is tried against the vertices
    ev, evec = np.linalg.eigh(np.cov(N.T, aweights=w))
    C = np.einsum("i,ij,ik->jk", w, N, N); X = V[F[ts]].mean(1)
    apex = np.linalg.lstsq(C, np.einsum("i,ij,i->j", w, N, np.einsum("ij,ij->i", N, X)), rcond=None)[0]
    for j in range(3):
        if math.sqrt(max(ev[j], 0)) >= 0.02:
            break
        ax = evec[:, j]
        if abs(np.average(N @ ax, weights=w)) < 0.02 or abs(np.average(N @ ax, weights=w)) > 0.999:
            continue
        q = P - apex; h = q @ ax; rho = np.linalg.norm(q - np.outer(h, ax), axis=1)
        k = np.polyfit(h, rho, 1)
        if np.abs(np.polyval(k, h) - rho).max() <= 5 * tol and np.linalg.norm(apex) < 1e5 * tol:
            return ("cone", round(float(math.degrees(math.atan(abs(k[0])))), 2), (ax, apex, k))
    # sphere: facet normal lines meet at the centre
    X = V[F[ts]].mean(1); A = np.zeros((3, 3)); b_ = np.zeros(3)
    for x, m, wt in zip(X, N, w):
        M = np.eye(3) - np.outer(m, m); A += wt * M; b_ += wt * M @ x
    c = np.linalg.lstsq(A, b_, rcond=None)[0]; d = np.linalg.norm(P - c, axis=1); R = float(np.median(d))
    diag = tol * 1e4
    if np.abs(d - R).max() <= 5 * tol and R < diag:
        return ("sphere", round(R, 4), (None, c))
    return None

def fit_revolution(ts, V, F, n, area, tol):
    """Surface of revolution through the facets' normal lines (Pottmann and Randrup 1998): every normal line
    of such a surface meets its axis, i.e. belongs to a linear line complex of pitch 0. The meridian profile
    (height, radius) then names it: constant radius = cylinder, line = cone, circle on the axis = sphere,
    circle off the axis = torus. None unless every vertex lies on the named surface."""
    ts = list(ts)
    X = V[F[ts]].mean(1); D = n[ts]; w = area[ts]
    L = np.c_[np.cross(X, D), D]
    ev, evec = np.linalg.eigh((L * w[:, None]).T @ L)
    abar, ax = evec[:3, 0], evec[3:, 0]
    na = np.linalg.norm(ax)
    if na < 1e-6:
        return None
    ax, abar = ax / na, abar / na
    if abs(ax @ abar) > 1e-3 * np.linalg.norm(abar) + 1e-6:      # pitch != 0: helical, not a revolution
        return None
    c = np.cross(ax, abar)
    P = V[np.unique(F[ts])]; q = P - c; h = q @ ax; rho = np.linalg.norm(q - np.outer(h, ax), axis=1)
    lim = 5 * tol; diag = tol * 1e4
    cc, r, dev = fit_circle(np.c_[h, rho])
    if dev <= lim and lim < abs(cc[1]) < diag and r < diag:
        return ("torus", (round(float(cc[1]), 4), round(float(r), 4)), (ax, c, cc))
    return None


def surface_test(model, V, F, n, tol):
    tol = 5 * tol          # the same limit the fit was accepted with
    kind, par, geo = model
    ax, c = geo[0], geo[1]
    if kind == "sphere":
        return lambda t: np.abs(np.linalg.norm(V[F[t]] - c, axis=1) - par).max() <= tol

    def meridian(t):
        q = V[F[t]] - c; h = q @ ax
        return h, np.linalg.norm(q - np.outer(h, ax), axis=1)

    if kind == "cylinder":
        return lambda t: np.abs(meridian(t)[1] - par).max() <= tol
    if kind == "cone":
        k = geo[2]
        def on_cone(t):
            h, rho = meridian(t)
            return np.abs(np.polyval(k, h) - rho).max() <= tol
        return on_cone
    if kind == "sphere":
        return lambda t: np.abs(np.linalg.norm(V[F[t]] - c, axis=1) - par).max() <= tol
    cc = geo[2]
    def on_torus(t):
        h, rho = meridian(t)
        return np.abs(np.hypot(h - cc[0], rho - cc[1]) - par[1]).max() <= tol
    return on_torus


def regions(tri):
    V, F, nb, diag = mesh_topology(tri)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); area = np.linalg.norm(n, axis=1) / 2
    n = n / np.maximum(2 * area[:, None], 1e-30)
    tol = float(os.environ.get("REGION_TOL", "1e-4")) * diag   # vertex-on-surface limit, share of diagonal
    label = -np.ones(len(F), int); kinds = []
    _, _, patches = classify(tri)
    # 1. cylinders from quad seeds
    for o in sorted((o for o in patches if o[0] == "cylinder"), key=lambda o: -o[1]):
        seed = [t for t in o[4] if label[t] < 0]
        if len(seed) < 4:
            continue
        ax = np.asarray(o[3], float); ax /= np.linalg.norm(ax); u, w = frame(ax)
        P = V[np.unique(F[seed])]
        c2, R, dev = fit_circle(np.c_[P @ u, P @ w])
        if dev > 5 * tol:
            continue
        c = c2[0] * u + c2[1] * w
        def on_cyl(t, ax=ax, c=c, R=R):
            q = V[F[t]] - c; rad = q - np.outer(q @ ax, ax)
            if np.abs(np.linalg.norm(rad, axis=1) - R).max() > tol or abs(n[t] @ ax) > 0.02:
                return False
            m = rad.mean(0); return abs(abs(n[t] @ m) / max(np.linalg.norm(m), 1e-12) - 1) < 0.02
        reg = grow(seed, nb, on_cyl, label, len(kinds))
        # a designed prism (hexagon, octagon, box walls) also has quads whose normal lines meet on an axis
        # at one radius. A tessellated cylinder turns by small steps; a prism by 360/sides >= 45 degrees.
        # ponytail: fixed 36 deg (>= 10 sides) cut-off; a 12-gon prism still reads as a cylinder.
        rs = set(reg)
        steps = [n[t] @ n[u] for t in reg for u in nb[t] if u in rs and u > t and n[t] @ n[u] < 0.99999]
        if steps and np.median(steps) < math.cos(math.radians(36)):
            label[reg] = -1
            continue
        kinds.append(("cylinder", reg, round(float(R), 4)))
    # 2. planes
    held = []
    for s in np.argsort(-area):
        if label[s] >= 0 or area[s] <= 0:
            continue
        ns, ds = n[s], n[s] @ V[F[s, 0]]
        def on_plane(t, ns=ns, ds=ds):
            return n[t] @ ns > 0.9999 and np.abs(V[F[t]] @ ns - ds).max() <= tol
        reg = grow([s], nb, on_plane, label, len(kinds))
        # possibly one facet of a curved surface (a cone generator strip can hold 10+ coplanar triangles):
        # most of its boundary LENGTH curves away smoothly. Held back, not discarded: if no curved fit in
        # step 3 claims it and it stood alone, it is restored as the plane it is (a face between fillets).
        rs = set(reg); smooth_len = total_len = 0.0
        for t in reg:
            ft = set(F[t].tolist())
            for u in nb[t]:
                if u in rs:
                    continue
                sh = list(ft & set(F[u].tolist()))
                if len(sh) != 2:
                    continue
                L_ = float(np.linalg.norm(V[sh[0]] - V[sh[1]])); total_len += L_
                if n[t] @ n[u] > SMOOTH:
                    smooth_len += L_
        smooth_edges = sum(1 for t in reg for u in nb[t] if u not in rs and n[t] @ n[u] > SMOOTH)
        if (len(reg) <= 8 and smooth_edges >= 2) or (total_len > 0 and smooth_len >= 0.5 * total_len):
            label[reg] = -2
            held.append(reg)
            continue
        kinds.append(("plane", reg, None))
    # 3a. whole smooth components that are ONE cylinder / cone / sphere
    free = set(np.where(label < 0)[0]); seen = set(); comp_size = {}
    for s0 in list(free):
        if s0 in seen:
            continue
        comp, stack = [], [s0]; seen.add(s0)
        while stack:
            t = stack.pop(); comp.append(t)
            for u in nb[t]:
                if u in free and u not in seen and n[t] @ n[u] > SMOOTH:
                    seen.add(u); stack.append(u)
        fit = fit_smooth(comp, V, F, n, area, tol) if len(comp) >= 6 else None
        if fit:
            label[comp] = len(kinds); kinds.append((fit[0], comp, fit[1]))
    # 3b. seeded growth on the rest: a smooth chain of several surfaces is split where the surface changes
    free = set(np.where(label < 0)[0]); tried = set()
    for s0 in sorted(free, key=lambda t: -area[t]):
        if label[s0] >= 0 or s0 in tried:
            continue
        ring, frontier = {s0}, [s0]
        for _ in range(3):
            frontier = [u for t in frontier for u in nb[t]
                        if u not in ring and label[u] < 0 and n[t] @ n[u] > SMOOTH]
            ring.update(frontier)
        ring = list(ring)
        best = None
        if len(ring) >= 8:
            for fit in (fit_smooth, fit_revolution):
                model = fit(ring, V, F, n, area, tol)
                if model is None:
                    continue
                on = surface_test(model, V, F, n, tol)
                start = [t for t in ring if on(t)] or [s0]
                reg = dry_grow(start, nb, lambda u, on=on: u in free and label[u] < 0 and on(u))
                if best is None or len(reg) > len(best[1]):
                    best = (model, reg)
        if best is None or len(best[1]) < 6:
            tried.add(s0); continue
        model, reg = best
        label[reg] = len(kinds)
        kinds.append((model[0], reg, model[1]))
    for reg in held:
        if np.all(label[reg] == -2):
            rs = set(reg)
            alone = all(label[u] >= 0 or u in rs for t in reg for u in nb[t])
            comp_size[reg[0]] = len(reg) if alone else -1
    # a held region is restored as a plane only when it stood ALONE (its smooth neighbours were already
    # recognised surfaces, e.g. a face between fillets). A chain of unfitted facets is a surface we cannot
    # name yet (torus, blend, freeform): it stays unassigned, never becomes thousands of planes.
    for reg in held:
        if np.all(label[reg] == -2) and comp_size.get(reg[0], 0) == len(reg):
            label[reg] = len(kinds); kinds.append(("plane", reg, None))
    cov = collections.Counter(); cnt = collections.Counter()
    for k, reg, _ in kinds:
        cov[k] += area[reg].sum(); cnt[k] += 1
    tot = area.sum()
    return {"tris": len(F), "counts": dict(cnt),
            "coverage": {k: round(float(100 * v / tot), 2) for k, v in cov.items()},
            "unassigned_pct": round(float(100 * area[label < 0].sum() / tot), 2),
            "params": {k: sorted(p for kk, _, p in kinds if kk == k) for k in ("cylinder", "cone", "sphere", "torus")},
            "label": label, "topology": (V, F, nb, n, area, tol)}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = regions(load(p)); print(p.rsplit("/", 1)[-1], {k: v for k, v in r.items() if k not in ("label", "topology")}, flush=True)
