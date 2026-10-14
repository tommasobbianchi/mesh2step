"""The V-gauge (bd projects-vgj7.4): the user clicks near a sharp edge of a scan and declares it a 90-degree edge between
two flat faces. On a noisy scan the planes fitted near an edge are off, so the faces that should meet there do not
meet cleanly; the gauge fits the two sides on the raw scan and forces them exactly perpendicular.

gauge(mesh, triangle) -> two planes (normal, d with n.x = d, the mesh triangles of each side), the edge line, the
measured angle, rms, and the extent along the edge. ValueError (the user's to retry) when there are not two flat
sides or the measured angle is not within TOL_DEG of 90.
"""

import numpy as np
from scipy.spatial import cKDTree

RADIUS = 0.06     # default window radius around the click, fraction of the bbox diagonal
TOL_DEG = 15.0    # accepted |measured angle - 90|
DISTINCT_DEG = 30.0   # two sides closer than this in normal are one face
MODE_DEG = 12.0       # the sides' normals are the modes of the normals within this cone
SPREAD_DEG = 20.0     # a triangle this far in normal from its side's mean is edge blur, not the side
MIN_TRIS = 6
BAND = 1.0        # edge lengths: a scan blurs an edge over about one triangle each side; points this close to the
                  # other side's plane are dropped


def _two_means(N, w):
    """Area-weighted 2-means of unit normals: -> per-row side (0/1), the two unit means."""
    m = (N * w[:, None]).sum(0)
    a = N[np.argmin(N @ m)]
    c = np.array([a, N[np.argmin(N @ a)]])
    for _ in range(20):
        s = (N @ c[1] > N @ c[0]).astype(int)
        new = np.array([(N[s == k] * w[s == k, None]).sum(0) for k in (0, 1)])
        new /= np.maximum(np.linalg.norm(new, axis=1, keepdims=True), 1e-12)
        if np.allclose(new, c):
            break
        c = new
    for _ in range(5):   # mode, not mean: the edge blur between the sides pulls each mean toward the other
        for k in (0, 1):
            m = (s == k) & (N @ c[k] >= np.cos(np.radians(MODE_DEG)))
            if m.sum() >= 3:
                v = (N[m] * w[m, None]).sum(0)
                c[k] = v / np.linalg.norm(v)
    return s, c


def _plane(P, nref):
    """SVD plane of points P, normal oriented along nref: (unit normal, d, rms)."""
    c = P.mean(0)
    n = np.linalg.svd(P - c, full_matrices=False)[2][-1]
    n = n if n @ nref >= 0 else -n
    return n, float(n @ c), float(np.sqrt(np.mean(((P - c) @ n) ** 2)))


def gauge(mesh, triangle, raw=None, noise=None, radius=None):
    """mesh: what the user clicks (the scanprep mesh); raw: the scan before scanprep, fitted on as scanransac.fit does;
    noise: scanprep._noise of the mesh fitted on; radius: the window around the click (mm)."""
    from scanprep import _noise

    diag = float(np.linalg.norm(mesh.extents))
    r = float(radius) if radius else RADIUS * diag
    C, N, A = mesh.triangles_center, mesh.face_normals, mesh.area_faces
    p0, n0 = C[triangle], N[triangle]
    # the window: near the click, facing its side (a thin wall's far side is within reach but faces away)
    win = np.flatnonzero((np.linalg.norm(C - p0, axis=1) <= r) & (N @ n0 > -0.3))
    if len(win) < 2 * MIN_TRIS:
        raise ValueError("too few triangles around the click: click on an edge, or retry wider")
    s, c = _two_means(N[win], A[win])
    if np.degrees(np.arccos(np.clip(c[0] @ c[1], -1, 1))) < DISTINCT_DEG:
        raise ValueError("no edge here: the area around the click is one flat face; click on the edge itself")
    cos = np.cos(np.radians(SPREAD_DEG))
    sides = [win[(s == k) & (N[win] @ c[k] >= cos)] for k in (0, 1)]
    if min(map(len, sides)) < MIN_TRIS:
        raise ValueError("no two flat sides found around the click; retry wider or closer to the edge")
    fm = raw if raw is not None else mesh
    if raw is not None:   # the raw triangles under each side: nearest side within one edge length
        edge = float(mesh.edges_unique_length.mean())
        d = np.array([cKDTree(C[t]).query(raw.triangles_center, distance_upper_bound=edge)[0] for t in sides])
        own = np.argmin(d, axis=0)
        # and facing its side: a raw triangle of the other face lies within reach of this side's last triangle
        ok = raw.face_normals @ c.T >= np.cos(np.radians(30))
        rs = [np.flatnonzero((own == k) & np.isfinite(d[k]) & ok[:, k]) for k in (0, 1)]
    else:
        rs = sides
    V, F = np.asarray(fm.vertices, float), np.asarray(fm.faces)
    noise = _noise(V, F) if noise is None else noise
    band = BAND * float(fm.edges_unique_length.mean())
    P0 = [V[np.unique(F[t])] for t in rs]
    P = P0
    for _ in range(3):   # fit, drop the points within the blur band of the other side's plane, refit
        fits = [_plane(P[k], c[k]) for k in (0, 1)]
        keep = [np.abs(P0[k] @ fits[1 - k][0] - fits[1 - k][1]) > band for k in (0, 1)]
        if min(int(m.sum()) for m in keep) < 3 * MIN_TRIS:
            break
        P = [P0[k][keep[k]] for k in (0, 1)]
    fits = [_plane(P[k], c[k]) for k in (0, 1)]
    flat = 2 * noise + 1e-4 * diag
    for k in (0, 1):
        # a curved side bends away from its plane across the flange: the quadratic term of the residual across it
        t = P[k] @ fits[1 - k][0]
        q = np.polyfit(t, P[k] @ fits[k][0] - fits[k][1], 2)[0]
        sag = abs(q) * float(np.ptp(t)) ** 2 / 4
        if fits[k][2] > 1.5 * flat or sag > flat:
            raise ValueError(f"the sides are not flat (rms {fits[k][2]:.3f} mm, bow {sag:.3f} mm): "
                             "the gauge is for an edge between two planes")
    n1, n2 = fits[0][0], fits[1][0]
    ang = float(np.degrees(np.arccos(np.clip(n1 @ n2, -1, 1))))
    if abs(ang - 90) > TOL_DEG:
        raise ValueError(f"the faces meet at {ang:.0f} degrees, not 90 (+/- {TOL_DEG:.0f})")
    # exactly 90: rotate both normals symmetrically about their bisector, offsets by least squares with normals fixed
    b, e = (n1 + n2) / np.linalg.norm(n1 + n2), (n1 - n2) / np.linalg.norm(n1 - n2)
    ns = [(b + e) / np.sqrt(2), (b - e) / np.sqrt(2)]
    ds = [float(np.mean(P[k] @ ns[k])) for k in (0, 1)]
    rms = float(np.sqrt(np.mean(np.r_[P[0] @ ns[0] - ds[0], P[1] @ ns[1] - ds[1]] ** 2)))
    u = np.cross(ns[0], ns[1])
    pt = p0 + (ds[0] - ns[0] @ p0) * ns[0] + (ds[1] - ns[1] @ p0) * ns[1]   # the edge point nearest the click
    allp = np.vstack(P)
    h = (allp - pt) @ u
    # each flange runs from the edge into its side: direction in its plane, away from the other plane
    fl = [float(np.sign(np.median(P[k] @ ns[1 - k] - ds[1 - k])) or 1.0) * ns[1 - k] for k in (0, 1)]
    width = [float(np.percentile(np.abs(P[k] @ ns[1 - k] - ds[1 - k]), 95)) for k in (0, 1)]
    return {"planes": [{"normal": ns[k].tolist(), "d": ds[k], "triangles": sorted(int(t) for t in sides[k]),
                        "flange": fl[k].tolist(), "width": width[k]} for k in (0, 1)],
            "edge": {"point": pt.tolist(), "direction": u.tolist()},
            "angle_measured_deg": ang, "rms": rms, "extent": [float(h.min()), float(h.max())]}
