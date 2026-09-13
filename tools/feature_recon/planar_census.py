"""Upper bound of the planar recursive merge (idea: Tommaso Bianchi): how many triangles an EXACT merge of
coplanar edge-connected triangles, re-triangulated with boundary vertices kept (no cracks against neighbours),
would remove. A region with n boundary vertices and h holes needs n + 2h - 2 triangles.
usage: python3 planar_census.py <stl> [...]"""
import collections, math, sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from slice import load

COS = math.cos(math.radians(0.01))


def census(tri):
    diag = float(np.linalg.norm(tri.reshape(-1, 3).max(0) - tri.reshape(-1, 3).min(0)))
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); a = np.linalg.norm(n, axis=1)
    ok = a > 1e-12; n[ok] /= a[ok, None]
    keys = np.round(tri / (diag * 1e-7)).astype(np.int64)
    vk = [[tuple(keys[t, i]) for i in range(3)] for t in range(len(tri))]
    own = collections.defaultdict(list)
    for t in np.where(ok)[0]:
        k = vk[t]
        for i, j in ((0, 1), (1, 2), (2, 0)):
            own[(k[i], k[j]) if k[i] < k[j] else (k[j], k[i])].append(t)
    parent = list(range(len(tri)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    tol = 1e-6 * diag
    for ow in own.values():
        if len(ow) == 2:
            s, t = ow
            if n[s] @ n[t] > COS and abs(n[s] @ (tri[t, 0] - tri[s, 0])) < tol:
                parent[find(s)] = find(t)
    regions = collections.defaultdict(list)
    for t in np.where(ok)[0]:
        regions[find(t)].append(t)
    before = after = 0
    for ts in regions.values():
        if len(ts) < 3:
            continue
        cnt = collections.Counter()
        adj = collections.defaultdict(list)
        for t in ts:
            k = vk[t]
            for i, j in ((0, 1), (1, 2), (2, 0)):
                cnt[(k[i], k[j]) if k[i] < k[j] else (k[j], k[i])] += 1
        bnd = [e for e, c in cnt.items() if c == 1]
        verts = set(v for e in bnd for v in e)
        for u, v in bnd:
            adj[u].append(v); adj[v].append(u)
        seen, loops = set(), 0
        for v in verts:
            if v in seen:
                continue
            loops += 1; stack = [v]
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x); stack.extend(adj[x])
        need = len(verts) + 2 * max(loops - 1, 0) - 2
        if need < len(ts):
            before += len(ts); after += need
    return len(tri), before, after


if __name__ == "__main__":
    for p in sys.argv[1:]:
        nt, b, a = census(load(p))
        print(f"{p.rsplit('/', 1)[-1]}: tris {nt}  planar-mergeable {b} -> {a}  total after {nt - b + a} "
              f"({100 * (nt - b + a) / nt:.1f}% of input)", flush=True)
