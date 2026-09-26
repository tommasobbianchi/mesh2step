"""Minimal pad/pocket program by cell decomposition and set cover (docs/ENGINE.md findings: alternating sum of
volumes, Shapiro-Vossler B-rep to CSG). No thresholds: J decides.

Candidates, per axis and per interval between the solid's exact cap levels on that axis:
  pad    = a connected region that is material in every band of the interval (maximal prism of material)
  pocket = a connected region that is air in every band of the interval, inside the box (maximal prism of air)
Cells  = voxels grouped by which candidates cover them (the arrangement the candidates induce), weighted.
Program form: (union of chosen pads) - (union of chosen pockets). The ILP (HiGHS via scipy.optimize.milp) picks
the pads and pockets that minimise  mismatch / |part| + STEP_COST * ops,  i.e. J on the grid.

usage: cells.py <solid.step or part.stl> [out_tree.json]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tree"))
import search as SE                                    # noqa: E402

PR = SE.PR
STEP_COST = 0.001


def levels_of(bm, a, tol):
    """Exact cap heights on axis a: the mesh's flat faces across a, plus its two ends."""
    n = bm.face_normals[:, a]
    z = bm.triangles_center[flat := np.abs(np.abs(n) - 1) < 1e-4][:, a]
    w = bm.area_faces[flat]
    lo, hi = bm.bounds
    zs = [float(lo[a]), float(hi[a])]
    for zz in np.unique(np.round(z / (tol / 4)) * (tol / 4)):
        if w[np.abs(z - zz) <= tol / 4].sum() > 0:
            zs.append(float(zz))
    out = []
    for q in sorted(zs):
        if not out or q - out[-1] > tol:
            out.append(q)
    return out


def candidates(bm, tol, axes=(0, 1, 2)):
    lo, hi = bm.bounds
    out = []
    for a in axes:
        u, v = SE.reverse.plane_axes(a)
        lv = levels_of(bm, a, tol)
        frame = box(lo[u] - tol, lo[v] - tol, hi[u] + tol, hi[v] + tol)
        secs = [PR.slab_region(bm, a, (z0 + z1) / 2 - tol / 4, (z0 + z1) / 2 + tol / 4) for z0, z1 in zip(lv, lv[1:])]
        for i in range(len(secs)):
            mat, air = secs[i], frame.difference(secs[i])
            for j in range(i, len(secs)):
                if j > i:
                    mat = mat.intersection(secs[j])
                    air = air.difference(secs[j])
                z0, z1 = lv[i], lv[j + 1]
                for op, reg in (("pad", mat), ("pocket", air)):
                    for g in PR._polys(reg):
                        if g.area > 4 * tol * tol:
                            zz0 = z0 - 2 * tol if (op == "pocket" and i == 0) else z0
                            zz1 = z1 + 2 * tol if (op == "pocket" and j == len(secs) - 1) else z1
                            out.append(SE.Cand(op=op, a=a, reg=g, mask=None, k0=0, k1=0, z0=float(zz0),
                                               z1=float(zz1), cost=1, label=f"{op} {'XYZ'[a]} [{z0:.2f},{z1:.2f}]",
                                               circle=None))
    return out


def masks(cands, c):
    """Each candidate's voxel set, as a flat bool vector."""
    shape = tuple(len(x) for x in c)
    M = np.zeros((len(cands), int(np.prod(shape))), bool)
    for k, cd in enumerate(cands):
        a = cd.a
        u, v = SE.reverse.plane_axes(a)
        U, W = np.meshgrid(c[u], c[v], indexing="ij")
        m2 = shapely.contains_xy(cd.reg, U, W)
        ks = (c[a] >= cd.z0) & (c[a] <= cd.z1)
        blk = np.zeros((len(c[u]), len(c[v]), len(c[a])), bool)
        blk[:, :, ks] = m2[:, :, None]
        M[k] = np.transpose(blk, np.argsort([u, v, a])).ravel()
    return M


def solve(V, cands, M, time_limit=60.0):
    """ILP over cells -> indices of the chosen candidates (pads first, then pockets)."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix
    vox = V.ravel()
    covered = M.any(axis=0)
    keep = covered | vox                                 # voxels no candidate touches are fixed empty
    sig = np.packbits(M[:, keep].T, axis=1)
    cells, inv, cnt = np.unique(sig, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    nin = np.bincount(inv, weights=vox[keep].astype(float), minlength=len(cells))
    nout = cnt - nin
    member = np.unpackbits(cells, axis=1)[:, :len(cands)].astype(bool)   # cell x candidate
    P = np.array([cd.op == "pad" for cd in cands])
    nc, nk = len(cells), len(cands)
    tot = float(vox.sum())
    # variables: x_k (nk), u_c (nc: some pad covers c), w_c (nc: some pocket covers c), o_c (nc: c is material)
    nvar = nk + 3 * nc
    cost = np.zeros(nvar)
    cost[:nk] = STEP_COST
    cost[nk + 2 * nc:] = (nout - nin) / tot              # mismatch = sum nin (1 - o) + nout o ; constant dropped
    A = lil_matrix((0, nvar))
    rows, lb, ub = [], [], []

    def add(coefs, lo, hi):
        rows.append(coefs)
        lb.append(lo)
        ub.append(hi)

    for ci in range(nc):
        pads = np.nonzero(member[ci] & P)[0]
        pocks = np.nonzero(member[ci] & ~P)[0]
        uc, wc, oc = nk + ci, nk + nc + ci, nk + 2 * nc + ci
        add({uc: 1, **{k: -1 for k in pads}}, -np.inf, 0)             # u <= sum pads
        for k in pads:
            add({uc: 1, k: -1}, 0, np.inf)                               # u >= x_k
        add({wc: 1, **{k: -1 for k in pocks}}, -np.inf, 0)
        for k in pocks:
            add({wc: 1, k: -1}, 0, np.inf)
        add({oc: 1, uc: -1}, -np.inf, 0)                                  # o <= u
        add({oc: 1, wc: 1}, -np.inf, 1)                                   # o <= 1 - w
        add({oc: 1, uc: -1, wc: 1}, 0, np.inf)                            # o >= u - w
    A = lil_matrix((len(rows), nvar))
    for r, coefs in enumerate(rows):
        for k, val in coefs.items():
            A[r, k] = val
    res = milp(cost, constraints=LinearConstraint(A.tocsr(), lb, ub), integrality=np.ones(nvar),
               bounds=Bounds(0, 1), options={"time_limit": time_limit, "disp": False})
    if res.x is None:
        return None, {"status": res.message}
    x = res.x[:nk] > 0.5
    chosen = [k for k in range(nk) if x[k] and P[k]] + [k for k in range(nk) if x[k] and not P[k]]
    mism = float(res.fun - STEP_COST * len(chosen)) + nin.sum() / tot
    return chosen, {"cells": nc, "cands": nk, "ops": len(chosen), "mismatch": round(mism, 4),
                    "status": res.message[:60]}


def program(bm, tol, time_limit=60.0):
    V, c, h = SE.voxels(bm)
    cands = candidates(bm, tol)
    M = masks(cands, c)
    chosen, info = solve(V, cands, M, time_limit)
    if chosen is None:
        return None, info
    return SE.to_tree(cands, chosen, tol), info


if __name__ == "__main__":
    import trimesh
    src = sys.argv[1]
    if src.endswith(".step"):
        import evidence as E
        import solve as S
        shape = E.read(src)
        lo_hi = None
        bm = S.mesh_of(shape, 0.05)
    else:
        bm = trimesh.load(src, force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(bm.extents)), 0.05)
    t0 = time.time()
    tree, info = program(bm, tol)
    info["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(info))
    for f in (tree or {}).get("features", []):
        print(f["id"], f["op"], f["axis"], f["at"], f["length"], f["label"])
    if tree is not None and len(sys.argv) > 2:
        json.dump(tree, open(sys.argv[2], "w"), indent=1)
