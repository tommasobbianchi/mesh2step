"""Slice an STL at given heights and read each cross-section loop as lines and circular arcs.
usage: python3 slice.py <stl> z1 [z2 ...]"""
import sys, struct, math, collections
import numpy as np

def load(p):
    data = open(p, "rb").read()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        pts = [tuple(map(float, l.split()[1:4])) for l in data.decode(errors="ignore").splitlines() if l.strip().startswith("vertex")]
        return np.array(pts, dtype=float).reshape(-1, 3, 3)
    n = struct.unpack("<I", data[80:84])[0]
    return np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))["v"].reshape(-1, 3, 3).astype(float)

def section(tri, z):
    segs = []
    for t in tri:
        d = t[:, 2] - z
        pts = []
        for i in range(3):
            a, b = t[i], t[(i + 1) % 3]; da, db = d[i], d[(i + 1) % 3]
            if (da < 0) != (db < 0):
                s = da / (da - db); pts.append(a[:2] + s * (b[:2] - a[:2]))
        if len(pts) == 2:
            segs.append((pts[0], pts[1]))
    return segs

def loops(segs, q=1e-5):
    key = lambda p: (round(p[0] / q), round(p[1] / q))
    adj = collections.defaultdict(list)
    for i, (a, b) in enumerate(segs):
        adj[key(a)].append((i, 0)); adj[key(b)].append((i, 1))
    used = [False] * len(segs); out = []
    for i in range(len(segs)):
        if used[i]: continue
        used[i] = True; a, b = segs[i]; loop = [a, b]; cur = b
        while True:
            nxt = None
            for j, end in adj[key(cur)]:
                if not used[j]: nxt = (j, end); break
            if nxt is None: break
            j, end = nxt; used[j] = True
            cur = segs[j][1 - end]; loop.append(cur)
            if key(cur) == key(loop[0]): break
        out.append(np.array(loop))
    return out

def dedupe(P, tol=1e-4):
    keep = [P[0]]
    for p in P[1:]:
        if np.linalg.norm(p - keep[-1]) > tol: keep.append(p)
    return np.array(keep)

def circle3(a, b, c):
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12: return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return np.array([ux, uy]), math.hypot(ax - ux, ay - uy)

def fit_circle(P):
    A = np.c_[2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))]; bb = (P ** 2).sum(1)
    x, *_ = np.linalg.lstsq(A, bb, rcond=None); c = x[:2]; r = math.sqrt(x[2] + c @ c)
    return c, r, np.abs(np.linalg.norm(P - c, axis=1) - r).max()

def primitives(L, line_tol=0.02, arc_tol=0.03):
    """greedy: grow a run from each start; keep it a line while all points are within line_tol of the chord,
    else an arc while a circle fits within arc_tol; emit the longer of the two."""
    L = dedupe(L); closed = np.linalg.norm(L[0] - L[-1]) < 1e-4
    if closed: L = L[:-1]
    n = len(L); prims = []; i = 0
    # start at a sharp corner so runs do not straddle the loop seam
    if closed and n > 3:
        ang = []
        for k in range(n):
            u = L[k] - L[k - 1]; v = L[(k + 1) % n] - L[k]
            ang.append(abs(math.atan2(u[0] * v[1] - u[1] * v[0], u @ v)))
        s = int(np.argmax(ang)); L = np.r_[L[s:], L[:s]]; L = np.r_[L, L[:1]]; n = len(L)
    while i < n - 1:
        j = i + 1; best = ("line", j)
        while j + 1 < n:
            P = L[i:j + 2]; a, b = P[0], P[-1]; ab = b - a; lab = np.linalg.norm(ab)
            dline = np.abs((P[:, 0] - a[0]) * ab[1] - (P[:, 1] - a[1]) * ab[0]).max() / lab if lab > 0 else 1e9
            if dline <= line_tol:
                j += 1; best = ("line", j); continue
            if len(P) >= 4:
                c, r, dev = fit_circle(P)
                if dev <= arc_tol and r < 500:
                    j += 1; best = ("arc", j, c, r); continue
            break
        P = L[i:best[1] + 1]
        if best[0] == "line":
            prims.append(("line", P[0], P[-1], np.linalg.norm(P[-1] - P[0])))
        else:
            c, r, dev = fit_circle(P)
            a0 = math.atan2(*(P[0] - c)[::-1]); a1 = math.atan2(*(P[-1] - c)[::-1])
            span = sum(abs(math.atan2(*(np.cross(np.r_[P[k] - c, 0], np.r_[P[k + 1] - c, 0])[2:3].tolist() + [float((P[k] - c) @ (P[k + 1] - c))])))
                       for k in range(len(P) - 1))
            prims.append(("arc", c, r, math.degrees(span), dev, len(P)))
        i = best[1]
    return prims, closed

def merge_arcs(prims, tol_c=0.3, tol_r=0.3):
    out = []
    for p in prims:
        if out and p[0] == "arc" and out[-1][0] == "arc" and np.linalg.norm(p[1] - out[-1][1]) < tol_c and abs(p[2] - out[-1][2]) < tol_r:
            q = out[-1]; out[-1] = ("arc", (q[1] + p[1]) / 2, (q[2] + p[2]) / 2, q[3] + p[3], max(q[4], p[4]), q[5] + p[5])
        elif out and p[0] == "line" and out[-1][0] == "line":
            q = out[-1]; d1 = q[2] - q[1]; d2 = p[2] - p[1]
            cosang = abs(d1 @ d2) / (np.linalg.norm(d1) * np.linalg.norm(d2) + 1e-12)
            if cosang > 0.9999:
                out[-1] = ("line", q[1], p[2], np.linalg.norm(p[2] - q[1]))
            else:
                out.append(p)
        else:
            out.append(p)
    return out

if __name__ == "__main__":
    tri = load(sys.argv[1])
    for z in map(float, sys.argv[2:]):
        L = loops(section(tri, z))
        print("== z=%.3f loops %d" % (z, len(L)))
        for li, loop in enumerate(sorted(L, key=len, reverse=True)):
            prims, closed = primitives(loop)
            prims = merge_arcs(prims)
            area = 0.5 * abs(np.sum(loop[:-1, 0] * loop[1:, 1] - loop[1:, 0] * loop[:-1, 1]))
            arcs = [p for p in prims if p[0] == "arc"]; lines = [p for p in prims if p[0] == "line"]
            print("  loop %d points %d closed %s area %.1f -> %d lines, %d arcs" % (li, len(loop), closed, area, len(lines), len(arcs)))
            for p in arcs:
                print("    ARC  centre (%.3f, %.3f) R %.3f span %.1f deg maxdev %.4f pts %d" % (p[1][0], p[1][1], p[2], p[3], p[4], p[5]))
            lens = sorted(round(p[3], 2) for p in lines)
            print("    LINES lengths:", collections.Counter(lens).most_common(12))
