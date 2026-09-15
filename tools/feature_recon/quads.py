"""Quad pairing + normal-line intersection classifier (idea: Davide Albertini, 2026-09-13).
1. a triangle whose ONLY parallel edge-neighbour is one triangle forms a quad with it (a strip cell of a tessellated
   curved surface; flat regions have many parallel neighbours and are skipped);
2. for edge-adjacent quads with non-parallel normals, the normal lines (almost) intersect: record the closest point;
3. per connected quad patch, the intersection points classify the surface:
   on a line, normals perpendicular to it -> cylinder; on a line, constant angle -> cone;
   one point -> sphere; a circle -> torus (fillet on a round edge).
usage: python3 quads.py <stl> [...]"""
import collections, math, os, sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load, fit_circle

PAR = math.cos(math.radians(0.5))


def classify(tri):
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0); diag = float(np.linalg.norm(hi - lo))
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); a = np.linalg.norm(n, axis=1)
    ok = a > 1e-12; n[ok] /= a[ok, None]
    keys = np.round(tri / (diag * 1e-7)).astype(np.int64)
    own = collections.defaultdict(list)
    for t in np.where(ok)[0]:
        k = [tuple(keys[t, i]) for i in range(3)]
        for i, j in ((0, 1), (1, 2), (2, 0)):
            own[(k[i], k[j]) if k[i] < k[j] else (k[j], k[i])].append(t)
    nb = collections.defaultdict(set)
    for ow in own.values():
        if len(ow) == 2:
            nb[ow[0]].add(ow[1]); nb[ow[1]].add(ow[0])
    # 1. quads
    quad = {}
    for t, s in nb.items():
        par = [u for u in s if n[t] @ n[u] > PAR]
        if len(par) == 1 and len(s) == 3:
            u = par[0]
            if sum(1 for w in nb[u] if n[u] @ n[w] > PAR) == 1:
                quad[t] = min(t, u)
    qid = sorted(set(quad.values())); qn, qc = {}, {}
    for t, q in quad.items():
        qn.setdefault(q, []).append(t)
    for q, ts in qn.items():
        w = a[ts]; qc[q] = (tri[ts].mean(1) * w[:, None]).sum(0) / w.sum()
        v = (n[ts] * w[:, None]).sum(0); qn[q] = v / np.linalg.norm(v)
    # 2. quad adjacency + normal-line closest points
    qadj = collections.defaultdict(set)
    for t, q in quad.items():
        for u in nb[t]:
            if u in quad and quad[u] != q:
                qadj[q].add(quad[u])
    parent = {q: q for q in qid}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    hits = collections.defaultdict(list)
    for q, s in qadj.items():
        for r in s:
            if r < q:
                continue
            d1, d2, w0 = qn[q], qn[r], qc[q] - qc[r]
            b = d1 @ d2
            if b > PAR:           # parallel normals: a tangent joint as often as a ruling -- never merge through it
                continue
            den = 1 - b * b
            s1 = (b * (d2 @ w0) - (d1 @ w0)) / den; s2 = ((d2 @ w0) - b * (d1 @ w0)) / den
            p1, p2 = qc[q] + s1 * d1, qc[r] + s2 * d2
            gap = float(np.linalg.norm(p1 - p2))
            # same surface only if both quads see the same curvature radius (a fillet meeting a cylinder does not)
            if gap > 1e-3 * diag or abs(s1) > diag or abs(s1 - s2) > 0.02 * max(abs(s1), abs(s2)) + 1e-4 * diag:
                continue
            parent[find(q)] = find(r)
            hits[q].append(((p1 + p2) / 2, -s1, q)); hits[r].append(((p1 + p2) / 2, -s2, r))
    # pairwise radius agreement still lets a long chain drift (p9: one patch spanning R 2..80). Split every patch
    # whose per-quad radii spread by > 5% at gaps in the sorted radii, then regrow connectivity inside each band.
    qr = {q: float(np.median([abs(h[1]) for h in hits[q]])) for q in qid if hits[q]}
    comps0 = collections.defaultdict(list)
    for q in qid:
        comps0[find(q)].append(q)
    comps = collections.defaultdict(list)
    for root, qs in comps0.items():
        rq = sorted((qr[q], q) for q in qs if q in qr)
        band, prev = 0, None
        label = {}
        for r_, q in rq:
            if prev is not None and r_ > prev * 1.05 + 1e-4 * diag:
                band += 1
            label[q] = band; prev = r_
        sub = {q: q for q in label}
        def f2(x):
            while sub[x] != x:
                sub[x] = sub[sub[x]]; x = sub[x]
            return x
        for q in label:
            for r in qadj[q]:
                if r in label and label[r] == label[q] and find(r) == root:
                    sub[f2(q)] = f2(r)
        for q in label:
            comps[(root, f2(q))].append(q)
    tris_of = collections.defaultdict(list)
    for t, q in quad.items():
        tris_of[q].append(t)
    out = []
    for qs in comps.values():
        pt = [t for q in qs for t in tris_of[q]]
        keep = set(qs)
        P = np.array([h[0] for q in qs for h in hits[q]]); R = np.array([h[1] for q in qs for h in hits[q]])
        if len(qs) < 4 or len(P) < 4:
            continue
        N = np.array([qn[q] for q in qs]); c0 = P.mean(0); tol = 2e-3 * diag
        # normals at a constant angle to one axis: the covariance of the normals has a null direction.
        # Constant 90 deg = cylinder, any other constant = cone. Checked BEFORE the point test: a full-height
        # cylinder strip puts every intersection at mid-height, which looks like a sphere centre.
        w, v = np.linalg.eigh(np.cov(N.T)); ax = v[:, 0]; dots = N @ ax
        # EB_RIM_CYL (edgebuild only): a full-ring cylinder patch carrying its near-tangent fillet bands tilts its normals
        # by up to 0.112 (washer: sqrt(w0) 0.092) and read as "other", so no cylinder was ever seeded
        rim_ = os.environ.get("EB_RIM_CYL")
        if math.sqrt(max(w[0], 0)) < (0.15 if rim_ else 0.01):
            if (np.abs(dots).max() < 0.15) if rim_ else (abs(dots.mean()) < 0.02):
                out.append(("cylinder", len(qs), float(np.median(np.abs(R))), ax, pt))
            else:
                out.append(("cone", len(qs), float(np.degrees(np.arccos(min(1.0, abs(dots.mean()))))), ax, pt))
            continue
        _, sv, vt = np.linalg.svd(P - c0, full_matrices=False)
        if sv[0] / math.sqrt(len(P)) < tol:
            out.append(("sphere", len(qs), float(np.median(np.abs(R))), c0, pt)); continue
        if sv[2] / math.sqrt(len(P)) < tol:   # planar spine -> torus if the centres lie on a circle
            u, vv = vt[0], vt[1]; cc, rr, dev = fit_circle(np.c_[(P - c0) @ u, (P - c0) @ vv])
            if dev < 3 * tol:
                out.append(("torus", len(qs), float(np.median(np.abs(R))), rr, pt)); continue
        out.append(("other", len(qs), float(math.sqrt(max(w[0], 0))), (float(np.median(np.abs(R))), float(np.percentile(np.abs(R), 90) - np.percentile(np.abs(R), 10)), np.round(v[:, 0], 2).tolist(), float(sv[0] / math.sqrt(len(P))), float(sv[2] / math.sqrt(len(P)))), pt))
    return len(tri), len(quad), out


if __name__ == "__main__":
    for p in sys.argv[1:]:
        nt, nq, out = classify(load(p))
        cnt = collections.Counter(o[0] for o in out)
        print(f"{p.rsplit('/', 1)[-1]}: tris {nt} in-quads {nq} patches {dict(cnt)}")
        for o in sorted(out, key=lambda o: -o[1])[:8]:
            extra = f"R={o[2]:.3f}" if o[0] in ("cylinder", "sphere") else f"angle={o[2]:.2f}" if o[0] == "cone" else \
                f"tube r={o[2]:.3f} ring R={o[3]:.3f}" if o[0] == "torus" else ""
            print(f"   {o[0]:8} quads {o[1]:5} {extra}")
