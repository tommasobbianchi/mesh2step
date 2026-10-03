"""Put a part in its own frame before anything looks at it: main axis on Z, base on z = 0 (owner, 2026-10-03).

The analyser models extrusions along X/Y/Z only; a scan arrives in any pose. Scan face normals are useless (median
25 deg off on a part 88 % axis-aligned), so everything works on 40k surface points:
  main axis - projection sharpness: points projected on the right axis pile into a few bins (one per flat face).
              Coarse sphere search, hill climb to 0.02 deg, polished by the median of the cap plane-fit normals.
  in-plane  - the mode of the wall plane-fit normals (mod 90 deg), then the best angle within +-2.5 deg of
              projection sharpness + 0.3 x area-weighted wall alignment: each alone has false maxima (sharpness on
              part 34, normals on 31), together they agree (Kimi, 2026-10-03; 28/28 fake scans).
  symmetry  - labels the part: revolution / C<n> about Z, else prismatic (rotate 4096 points, KD-tree distance).
X is the longer side across Z, signs by skew (heavy end down), Y = Z x X.

usage: orient.py <mesh> <out_dir>    writes oriented.stl, frame.json and photos/ (7 views, 3 mid sections)"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

SYM = 1.5                              # symmetric: moved points within 1.5x the sampling floor


def _sphere(n):
    i = np.arange(n) + 0.5; z = i / n; r = np.sqrt(1 - z * z); t = np.pi * (1 + 5 ** 0.5) * i
    return np.stack([r * np.cos(t), r * np.sin(t), z], 1)


def _basis(a):
    u = np.cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u)
    return u, np.cross(a, u)


def sharp(P, D, h):
    """Peakiness of P projected on each direction of D: sum of squared bin counts, bin h, averaged over two grids
    half a bin apart (one grid aliases: a peak split over two bins scores half)."""
    x = P @ D.T; x = x - x.min(0); r = 0
    for off in (0, 0.5):
        k = np.floor(x / h + off).astype(np.int64); nb = int(k.max()) + 1
        c = np.bincount((k + np.arange(len(D)) * nb).ravel(), minlength=nb * len(D)).reshape(len(D), nb)
        r = r + (c.astype(np.float64) ** 2).sum(1)
    return r


def _climb(P, d, size, step):
    """3x3 pattern search on the sphere; the step shrinks only when the centre wins."""
    G = np.array([(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1)], float)
    while step > np.radians(0.02):
        u, v = _basis(d); C = d + step * (G[:, :1] * u + G[:, 1:] * v); C /= np.linalg.norm(C, axis=1, keepdims=True)
        i = int(np.argmax(sharp(P, C, max(size * step, size * 5e-4)))); d = C[i]
        if i == 4:
            step *= 0.6
    return d


def _walls(P, a, size):
    """Points off the cap planes across a (a cap spreads over the outline and votes for its shape)."""
    z = P @ a; k = np.floor((z - z.min()) / (size * 2e-3)).astype(int); c = np.bincount(k)
    return P[c[k] < 4 * len(P) / len(c)]


def _pair(W, u, v, ts, h):
    D = np.concatenate([np.cos(ts)[:, None] * u + np.sin(ts)[:, None] * v, -np.sin(ts)[:, None] * u + np.cos(ts)[:, None] * v])
    s = sharp(W, D, h)
    return s[:len(ts)] + s[len(ts):]


def frame(P, k=48):
    """3x3 rotation, rows = the part's axes, main axis first. P: surface points, centred."""
    size = np.linalg.norm(np.ptp(P, 0))
    # main axis: the sharpest of 4 coarse candidates, each climbed and given its best in-plane pair
    D = _sphere(1500); step = np.radians(3.5); s = sharp(P[:6000], D, size * step)
    cands = []
    for i in np.argsort(-s)[:40]:
        if all(abs(D[i] @ c) < np.cos(np.radians(8)) for c in cands):
            cands.append(D[i])
        if len(cands) == 4:
            break
    best = None
    for a in cands:
        a = _climb(P, a, size, step); u, v = _basis(a); W = _walls(P, a, size)
        t = np.radians(np.arange(0, 90, 1.0)); t0 = t[np.argmax(_pair(W, u, v, t, size * np.radians(1)))]
        for st in np.radians([0.5, 0.25, 0.1, 0.05, 0.02]):
            ts = t0 + np.array([-st, 0, st]); t0 = ts[np.argmax(_pair(W, u, v, ts, max(size * st, size * 5e-4)))]
        b = np.cos(t0) * u + np.sin(t0) * v; R = np.array([a, b, np.cross(a, b)])
        sc = sharp(P, R, size * 2e-3).sum()
        if best is None or sc > best[0]:
            best = (sc, a)
    a = best[1]
    # plane-fit normals: smallest eigenvector of each point's k neighbours; eigenvalues give flatness and area
    Q = P[cKDTree(P).query(P, k)[1]]; Q = Q - Q.mean(1, keepdims=True)
    w, V = np.linalg.eigh(np.einsum('nki,nkj->nij', Q, Q)); lam = w / w.sum(1, keepdims=True); N = V[:, :, 0]
    for cone in (5, 2):                                  # polish: median of the cap normals
        c = N @ a; cap = np.abs(c) > np.cos(np.radians(cone))
        a = np.median(N[cap] * np.sign(c[cap])[:, None], 0); a /= np.linalg.norm(a)
    u, v = _basis(a)
    wall = np.abs(N @ a) < np.sin(np.radians(10))
    ang = np.arctan2(N[wall] @ v, N[wall] @ u); th = ang % (np.pi / 2)
    h = np.bincount((np.degrees(th) * 2).astype(int) % 180, minlength=180).astype(float)      # 0.5 deg bins
    h = h + np.roll(h, 1) + np.roll(h, -1) + np.roll(h, 2) + np.roll(h, -2)                   # 2.5 deg blur
    t0 = np.radians(np.argmax(h) / 2 + 0.25)
    d = (th - t0 + np.pi / 4) % (np.pi / 2) - np.pi / 4; t0 += np.median(d[np.abs(d) < np.radians(3)])
    ts = t0 + np.radians(np.arange(-2.5, 2.501, 0.05))
    ps = _pair(_walls(P, a, size), u, v, ts, size * 1e-3)
    dd = (ang[None] - ts[:, None] + np.pi / 4) % (np.pi / 2) - np.pi / 4
    A = (lam[wall, 1] * np.exp(-0.5 * (np.degrees(dd) / 1.5) ** 2)).sum(1)
    t0 = ts[int(np.argmax(ps / ps.max() + (0.3 * A / A.max() if A.max() > 0 else 0)))]
    b = np.cos(t0) * u + np.sin(t0) * v
    return np.array([a, b, np.cross(a, b)])


def _rot(a, t):
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K


def symmetry(m, z, c, n=4096, seed=0):
    """'revolution' | 'C<n>' | 'prismatic' about axis z through c, by median nearest-neighbour distance of the
    rotated points over the sampling floor (a second independent sample)."""
    P = trimesh.sample.sample_surface(m, n, seed=seed)[0] - c
    Q = trimesh.sample.sample_surface(m, n, seed=seed + 1)[0] - c
    kd = cKDTree(P); floor = float(np.median(kd.query(Q)[0])) or 1e-12
    e = lambda t: float(np.median(kd.query(Q @ _rot(z, t).T)[0]) / floor)
    if max(e(0.61), e(1.97)) < SYM:                      # two angles no n-fold symmetry shares
        return "revolution"
    for k in (8, 6, 5, 4, 3):
        if e(2 * np.pi / k) < SYM:
            return f"C{k}"
    return "prismatic"


def orient(mesh, n=40000, seed=0):
    """(T, info): T (4x4) maps the mesh into its frame - Z the main axis, X the longer side across it, base on
    z = 0, centred in x and y."""
    t0 = time.time()
    P = trimesh.sample.sample_surface(mesh, n, seed=seed)[0]; c = P.mean(0)
    R = frame(P - c)
    V = mesh.vertices - c
    ext = np.ptp(V @ R[1:].T, 0)
    x = R[1] if ext[0] >= ext[1] else R[2]
    sk = lambda d: d * (1 if ((V @ d) ** 3).mean() >= 0 else -1)   # heavy end toward the negative side
    z, x = sk(R[0]), sk(x)
    F = np.array([x, np.cross(z, x), z])
    T = np.eye(4); T[:3, :3] = F
    v = mesh.vertices @ F.T; lo, hi = v.min(0), v.max(0)
    T[:3, 3] = [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]
    return T, {"kind": symmetry(mesh, z, c), "seconds": round(time.time() - t0, 2)}


def prepare(mesh_path, out_dir):
    """Orient, write oriented.stl + frame.json, and the photos for the next step (7 views, 3 mid sections)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sections
    import tiles
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    m = trimesh.load(str(mesh_path), force="mesh")
    T, info = orient(m)
    m.apply_transform(T)
    m.export(out / "oriented.stl")
    res = {"main_axis": "Z", "T": T.tolist(), "T_back": np.linalg.inv(T).tolist(), **info}
    (out / "frame.json").write_text(json.dumps(res, indent=1))
    tiles.all_views(out / "oriented.stl", out / "photos", 1)
    sections.all_sections(out / "oriented.stl", out / "photos", 1)
    return res


if __name__ == "__main__":
    r = prepare(sys.argv[1], sys.argv[2])
    print(json.dumps({k: r[k] for k in ("kind", "seconds")}))
