"""What are the surfaces region growing could not name? Per unassigned smooth component (largest first):
triangles, area share, normal-cone sigma (0 = cylinder/cone family), sphere fit deviation, and the torus test
(closest points of adjacent facet normal lines lie on a planar circle = the tube centre circle).
usage: python3 unassigned_diag.py <stl> [top]"""
import math, sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from regions import regions, SMOOTH
from slice import load, fit_circle

r = regions(load(sys.argv[1])); top = int(sys.argv[2]) if len(sys.argv) > 2 else 10
label = r["label"]; V, F, nb, n, area, tol = r["topology"]; tot = area.sum()
free = set(np.where(label < 0)[0]); seen = set(); comps = []
for s in free:
    if s in seen:
        continue
    comp, st = [], [s]; seen.add(s)
    while st:
        t = st.pop(); comp.append(t)
        for u in nb[t]:
            if u in free and u not in seen and n[t] @ n[u] > SMOOTH:
                seen.add(u); st.append(u)
    comps.append(comp)
comps.sort(key=lambda c: -area[c].sum())
print(f"unassigned {r['unassigned_pct']}% in {len(comps)} smooth components; counts {r['counts']}")
for comp in comps[:top]:
    X = V[F[comp]].mean(1); N = n[comp]; w = area[comp]
    sig = math.sqrt(max(np.linalg.eigh(np.cov(N.T, aweights=w))[0][0], 0)) if len(comp) > 3 else float("nan")
    P, R = [], []
    cs = set(comp)
    for t in comp:
        for u in nb[t]:
            if u in cs and u > t:
                d1, d2, w0 = n[t], n[u], X[comp.index(t)] - X[comp.index(u)] if False else (V[F[t]].mean(0) - V[F[u]].mean(0))
                b = d1 @ d2
                if b > 0.99999:
                    continue
                s1 = (b * (d2 @ w0) - (d1 @ w0)) / (1 - b * b); s2 = ((d2 @ w0) - b * (d1 @ w0)) / (1 - b * b)
                p1 = V[F[t]].mean(0) + s1 * d1; p2 = V[F[u]].mean(0) + s2 * d2
                if np.linalg.norm(p1 - p2) < 1e-3 * tol * 1e4:
                    P.append((p1 + p2) / 2); R.append(abs(s1))
    msg = ""
    if len(P) >= 6:
        P = np.array(P); c0 = P.mean(0); _, sv, vt = np.linalg.svd(P - c0, full_matrices=False)
        cc, rr, dev = fit_circle(np.c_[(P - c0) @ vt[0], (P - c0) @ vt[1]])
        msg = (f"spine planar {sv[2] / math.sqrt(len(P)) / tol:.1f}tol circle R {rr:.3f} dev {dev / tol:.1f}tol "
               f"tube r median {np.median(R):.3f} spread {np.percentile(R, 90) - np.percentile(R, 10):.3f}")
    print(f"  tris {len(comp):6} area {100 * w.sum() / tot:5.2f}%  normal-sigma {sig:.3f}  {msg}")
