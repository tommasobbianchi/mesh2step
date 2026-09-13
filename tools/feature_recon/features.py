"""Connected feature patches of a triangle subset, classified as plane / cylinder (with axis point, radius, extent,
hole-vs-boss), with the two half-patches of one cylinder merged. Shared by the subtractive-feature builders."""
import collections, math
import numpy as np
from slice import fit_circle

def patches(tri, sel, TOL, min_share=0.005):
    cent = tri.mean(1); nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); area = np.linalg.norm(nrm, axis=1) / 2
    nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    idx = np.where(sel)[0]
    Q = max(1e-6, TOL * 1e-3); keys = np.round(tri / Q).astype(np.int64)
    owners = collections.defaultdict(list)
    for t in idx:
        k = [tuple(keys[t, i]) for i in range(3)]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            owners[(k[a], k[b]) if k[a] < k[b] else (k[b], k[a])].append(t)
    parent = {t: t for t in idx}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for ow in owners.values():
        if len(ow) == 2 and nrm[ow[0]] @ nrm[ow[1]] > math.cos(math.radians(20)):
            parent[find(ow[0])] = find(ow[1])
    comps = collections.defaultdict(list)
    for t in idx: comps[find(t)].append(t)
    tot = area[idx].sum(); out = []
    for ts in comps.values():
        ts = np.array(ts); A = area[ts].sum()
        if A < min_share * tot: continue
        P = tri[ts].reshape(-1, 3); c0 = P.mean(0)
        _, _, Vt = np.linalg.svd(P - c0, full_matrices=False); pn = Vt[2]
        mean_n = (nrm[ts] * area[ts, None]).sum(0); mean_n /= max(np.linalg.norm(mean_n), 1e-12)
        if np.abs((P - c0) @ pn).max() <= TOL * 3:
            out.append(dict(kind="plane", area=A, tris=ts, normal=mean_n, offset=float(c0 @ mean_n), points=P)); continue
        w, v = np.linalg.eigh((nrm[ts] * area[ts, None]).T @ nrm[ts]); axd = v[:, 0]
        u = np.cross(axd, [1, 0, 0] if abs(axd[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u); vv = np.cross(axd, u)
        c2, rr, dev = fit_circle(np.c_[P @ u, P @ vv])
        if dev > max(3 * TOL, 0.03 * rr):
            out.append(dict(kind="other", area=A, tris=ts)); continue
        axis_pt = c2[0] * u + c2[1] * vv
        radial = (cent[ts] - axis_pt); radial -= (radial @ axd)[:, None] * axd
        hole = float(np.mean(np.einsum("ij,ij->i", nrm[ts], -radial) > 0)) > 0.5
        tt = P @ axd
        out.append(dict(kind="cylinder", area=A, tris=ts, axis=axd, axis_pt=axis_pt, radius=rr, tmin=float(tt.min()), tmax=float(tt.max()), hole=hole))
    # merge the half-patches of the same cylinder (same axis line, same radius)
    cyl = [p for p in out if p["kind"] == "cylinder"]; merged = []; taken = set()
    for i, a in enumerate(cyl):
        if i in taken: continue
        grp = [a]
        for j in range(i + 1, len(cyl)):
            if j in taken: continue
            b = cyl[j]
            if abs(abs(a["axis"] @ b["axis"]) - 1) < 1e-3 and abs(a["radius"] - b["radius"]) < 2 * TOL and a["hole"] == b["hole"]:
                d = b["axis_pt"] - a["axis_pt"]; d -= (d @ a["axis"]) * a["axis"]
                if np.linalg.norm(d) < 2 * TOL:
                    grp.append(b); taken.add(j)
        axd = grp[0]["axis"]
        if axd @ np.array([1.0, 1.0, 1.0]) < 0: axd = -axd
        ts_all = np.concatenate([g["tris"] for g in grp]); P = tri[ts_all].reshape(-1, 3); tt = P @ axd
        merged.append(dict(kind="cylinder", area=sum(g["area"] for g in grp), tris=ts_all, axis=axd, axis_pt=grp[0]["axis_pt"],
                           radius=float(np.mean([g["radius"] for g in grp])), tmin=float(tt.min()), tmax=float(tt.max()),
                           hole=grp[0]["hole"], halves=len(grp)))
    return [p for p in out if p["kind"] != "cylinder"] + merged
