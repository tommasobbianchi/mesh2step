"""Feature map of a mesh: connected patches of triangles that are NOT on the part's primary envelope,
each classified as plane or cylinder with size, direction, convexity and radius. Diagnostic for the
subtractive-feature step (turned parts C, multi-axis blocks E).
Envelope test: turned parts use the radial envelope around the spin axis (as autorev); for other parts every
triangle is mapped (envelope test off).
usage: python3 featmap.py <stl> [turned]"""
import sys, collections, math
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, fit_circle, loops, dedupe
from auto2d import section2d

tri = load(sys.argv[1]); turned = len(sys.argv) > 2 and sys.argv[2] == "turned"
lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0); diag = float(np.linalg.norm(hi - lo)); TOL = max(0.05, 2e-4 * diag)
cent = tri.mean(1); nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); area = np.linalg.norm(nrm, axis=1) / 2
nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
sel = np.ones(len(tri), bool)
if turned:
    best = None
    for ax in range(3):
        cs = []
        for f in np.linspace(0.1, 0.9, 9):
            segs = section2d(tri, ax, lo[ax] + f * (hi[ax] - lo[ax]))
            Ls = [dedupe(l) for l in loops(segs) if len(l) > 3] if len(segs) >= 8 else []
            if not Ls: continue
            P = max(Ls, key=lambda L: abs(0.5 * np.sum(L[:-1, 0] * L[1:, 1] - L[1:, 0] * L[:-1, 1])))
            c, r, dev = fit_circle(P); cs.append((c, r))
        if len(cs) < 5: continue
        C = np.array([c for c, r in cs]); score = np.median(np.linalg.norm(C - np.median(C, 0), axis=1)) / max(np.median([r for c, r in cs]), 1e-9)
        if best is None or score < best[0]: best = (score, ax, np.median(C, 0))
    _, ax, cen = best; o = [i for i in range(3) if i != ax]
    zs = np.linspace(lo[ax], hi[ax], 801); rmax = []
    for z in zs[1:-1]:
        segs = section2d(tri, ax, z)
        rmax.append(np.max(np.linalg.norm(np.array([p for s in segs for p in s]) - cen, axis=1)) if segs else 0.0)
    rmax = np.array([rmax[0]] + rmax + [rmax[-1]])
    rc = np.linalg.norm(cent[:, o] - cen, axis=1); env_r = np.interp(cent[:, ax], zs, rmax)
    radial = np.zeros_like(cent); radial[:, o] = (cent[:, o] - cen) / np.maximum(rc[:, None], 1e-9)
    radial_n = np.abs(np.einsum("ij,ij->i", nrm, radial)); axial_n = np.abs(nrm[:, ax])
    # a triangle belongs to the turned envelope if it lies on the max radius (outer turned surface) or its normal is
    # radial/axial AND it is rotationally consistent (on the envelope radius); everything else is a feature surface
    on_env = (np.abs(rc - env_r) <= TOL * 2) | ((radial_n > 0.995) & (np.abs(rc - env_r) <= TOL * 20)) | (axial_n > 0.995)
    sel = ~on_env
    print("turned axis %s centre (%.3f, %.3f); feature triangles %d of %d" % ("XYZ"[ax], cen[0], cen[1], sel.sum(), len(tri)))
# adjacency by shared edges (rounded vertex keys)
Q = max(1e-6, TOL * 1e-3)
keys = np.round(tri / Q).astype(np.int64)
edge_owner = collections.defaultdict(list)
idx = np.where(sel)[0]
for t in idx:
    k = [tuple(keys[t, i]) for i in range(3)]
    for a, b in ((0, 1), (1, 2), (2, 0)):
        e = (k[a], k[b]) if k[a] < k[b] else (k[b], k[a]); edge_owner[e].append(t)
parent = {t: t for t in idx}
def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a
for owners in edge_owner.values():
    if len(owners) == 2:
        a, b = owners
        # join only if the dihedral is smooth (same surface): normals within 20 deg
        if nrm[a] @ nrm[b] > math.cos(math.radians(20)):
            parent[find(a)] = find(b)
comps = collections.defaultdict(list)
for t in idx: comps[find(t)].append(t)
tot = area[idx].sum()
rows = []
for root, ts in comps.items():
    ts = np.array(ts); A = area[ts].sum()
    if A < 0.005 * tot: continue
    P = tri[ts].reshape(-1, 3); c0 = P.mean(0); U, Sv, Vt = np.linalg.svd(P - c0, full_matrices=False)
    pn = Vt[2]; plan_res = np.abs((P - c0) @ pn).max()
    mean_n = (nrm[ts] * area[ts, None]).sum(0); mean_n /= max(np.linalg.norm(mean_n), 1e-12)
    kind = "plane"; info = ""
    if plan_res > TOL * 3:
        w, v = np.linalg.eigh((nrm[ts] * area[ts, None]).T @ nrm[ts]); axd = v[:, 0]
        u = np.cross(axd, [1, 0, 0] if abs(axd[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u); vv = np.cross(axd, u)
        c2, rr, dev = fit_circle(np.c_[P @ u, P @ vv])
        axis_pt = c2[0] * u + c2[1] * vv
        # concave (hole) if normals point toward the axis
        to_axis = (axis_pt - (cent[ts] - (cent[ts] @ axd)[:, None] * axd))
        to_axis = to_axis - (to_axis @ axd)[:, None] * axd
        conc = float(np.mean(np.einsum("ij,ij->i", nrm[ts], to_axis) > 0))
        span = float((P @ axd).max() - (P @ axd).min())
        kind = "cylinder" if dev < max(3 * TOL, 0.03 * rr) else "other"
        info = "axis %s R %.3f dev %.3f %s span %.2f" % (np.round(axd, 2).tolist(), rr, dev, "HOLE" if conc > 0.5 else "BOSS", span)
    else:
        info = "normal %s offset %.3f" % (np.round(mean_n, 2).tolist(), float(c0 @ mean_n))
    rows.append((A, len(ts), kind, info))
rows.sort(reverse=True)
print("patches (>=0.5%% of feature area): %d" % len(rows))
for A, n, kind, info in rows[:30]:
    print("  %-8s area %10.2f tris %5d  %s" % (kind, A, n, info))
print("summary:", dict(collections.Counter(r[2] for r in rows)), "holes:", sum(1 for r in rows if "HOLE" in r[3]), "bosses:", sum(1 for r in rows if "BOSS" in r[3]))
