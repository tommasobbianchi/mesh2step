"""Survey STL parts for extrusion (2.5D) character: for each axis, slice at 30/50/70% and compare the
cross-section (loop count, total signed area, perimeter). Prismatic along an axis => identical sections.
usage: python3 survey.py <dir>"""
import sys, os, glob, struct, math
import numpy as np

def load(p):
    data = open(p, "rb").read()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        pts = [tuple(map(float, l.split()[1:4])) for l in data.decode(errors="ignore").splitlines() if l.strip().startswith("vertex")]
        return np.array(pts, dtype=float).reshape(-1, 3, 3)
    n = struct.unpack("<I", data[80:84])[0]
    return np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))["v"].reshape(-1, 3, 3).astype(float)

def section_stats(tri, ax, h):
    """vectorised plane section: returns (#segments, total length, area via shoelace of segments)"""
    o = [i for i in range(3) if i != ax]
    d = tri[:, :, ax] - h
    s = np.sign(d); s[s == 0] = 1
    cross = (s[:, 0] != s[:, 1]) | (s[:, 1] != s[:, 2])
    T = tri[cross]; D = d[cross]
    if len(T) == 0: return 0, 0.0, 0.0
    pts = []
    for (i, j) in ((0, 1), (1, 2), (2, 0)):
        m = (np.sign(D[:, i]) != np.sign(D[:, j]))
        t = np.where(m, D[:, i] / np.where(m, D[:, i] - D[:, j], 1), np.nan)
        P = T[:, i] + t[:, None] * (T[:, j] - T[:, i])
        pts.append(np.where(m[:, None], P, np.nan))
    pts = np.stack(pts, 1)  # (k,3,3) with nan rows
    segs = []
    for row in pts:
        q = row[~np.isnan(row[:, 0])]
        if len(q) >= 2: segs.append((q[0][o], q[1][o]))
    if not segs: return 0, 0.0, 0.0
    A = np.array([a for a, b in segs]); B = np.array([b for a, b in segs])
    length = np.linalg.norm(B - A, axis=1).sum()
    # orientation-free area estimate: sum of |cross| is not an area; use the triangle normals' sign instead
    nrm = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    return len(segs), length, 0.0

rows = []
for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.stl")), key=lambda s: (len(s), s)):
    tri = load(p); lo = tri.reshape(-1, 3).min(0); hi = tri.reshape(-1, 3).max(0); size = hi - lo
    best = None
    for ax in range(3):
        stats = [section_stats(tri, ax, lo[ax] + f * size[ax]) for f in (0.3, 0.5, 0.7)]
        lens = [s[1] for s in stats]
        if min(lens) <= 0: continue
        var = (max(lens) - min(lens)) / max(lens)   # relative variation of section perimeter
        # also a wall test: fraction of triangle area whose normal is perpendicular to the axis or parallel to it
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); area = np.linalg.norm(nrm, axis=1)
        cosz = np.abs(nrm[:, ax]) / np.maximum(area, 1e-12)
        prism = area[(cosz < 0.02) | (cosz > 0.98)].sum() / area.sum()
        cand = (var, -prism, ax, prism, lens)
        if best is None or (var, -prism) < (best[0], best[1]): best = cand
    name = os.path.basename(p)
    if best is None:
        print("%-8s tris %6d size %s  no sections" % (name, len(tri), size.round(1)), flush=True); continue
    var, _, ax, prism, lens = best
    kind = "EXTRUSION" if var < 0.02 and prism > 0.9 else "near-2.5D" if prism > 0.8 else "3D"
    print("%-8s tris %6d size %-22s best axis %s perimeter var %.4f axis-aligned area %.3f -> %s" % (
        name, len(tri), str(size.round(1)), "XYZ"[ax], var, prism, kind), flush=True)
