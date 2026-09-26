"""Fewest-steps design search (the owner: 'in a human mind all the potential approaches are tested in parallel in a
fraction of second, and the approach with less number of steps is chosen').

Candidates are read off the mesh, never permuted blindly: on each principal axis, at each level (propose.wall_heights),
the section's pieces are pad elements, their holes and the missing regions are pocket elements, and arcs of >= 150 deg
are whole circles (the owner's 'half inscribed circle': a whole element, not an arc on another outline). Each element's
extent is the run of layers where the part covers it (pads) or leaves it empty (pockets). Candidates are scored on a
voxel grid, not in OCCT: a candidate's gain is one masked sum over prefix sums along its axis (microseconds), so a beam
of designs is grown in canonical order (pads, then pockets) and the design with the least mismatch + cost per step wins.
Only the winner is compiled; propose.edge_mods then adds rounds/chamfers (below the grid's resolution).

usage: search.py <mesh.stl> [out_tree.json]
"""
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import shapely
import trimesh
from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parent))
import propose as PR                                   # noqa: E402
import tree as T                                       # noqa: E402
from propose import AXN, PLANE, reverse                # noqa: E402

N = 128                                                # cells along the longest side
STEP = 0.004                                           # a step must fix this share of the part's volume
BEAM = 12
MAX_STEPS = 24


def voxels(m, n=N):
    """Occupancy on a cubic grid: [ix, iy, iz] bool, plus cell centres per axis and the pitch."""
    lo, hi = m.bounds
    h = float((hi - lo).max()) / n
    c = [lo[k] + h * (np.arange(max(1, int(np.ceil((hi[k] - lo[k]) / h)))) + 0.5) for k in range(3)]
    X, Y = np.meshgrid(c[0], c[1], indexing="ij")
    V = np.zeros((len(c[0]), len(c[1]), len(c[2])), bool)
    for k, z in enumerate(c[2]):
        r = T.section_region(m, "Z", float(z))         # tree uv of Z = (x, y)
        if not r.is_empty:
            V[:, :, k] = shapely.contains_xy(r, X, Y)
    return V, c, h


def _moved(A, a):
    """A viewed as [u, v, along a] with (u, v) = reverse.plane_axes(a)."""
    return np.moveaxis(A, a, 2)


class Cand:
    __slots__ = ("op", "a", "reg", "mask", "k0", "k1", "z0", "z1", "cost", "label", "circle")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _circles(piece, tol):
    """Whole circles behind the piece's long arcs (reverse.segment's fit): (centre, radius) in plane coords."""
    out = []
    P = np.asarray(piece.exterior.coords)[:-1]
    if len(P) < 8:
        return out
    try:
        _, prims = reverse.segment(P)
    except Exception:                                  # noqa: BLE001 -- a fit failure only costs this candidate
        return out
    for p in prims:
        if p[0] != "arc":
            continue
        c, r = np.asarray(p[3], float), float(p[4])
        seg = P[p[1]:min(p[2], len(P) - 1) + 1]
        if len(seg) < 3:
            continue
        ang = np.unwrap(np.arctan2(seg[:, 1] - c[1], seg[:, 0] - c[0]))
        if abs(ang[-1] - ang[0]) >= np.radians(150) or len(prims) == 1:
            out.append((c, r))
    return out


def candidates(m, V, c, h, tol):
    lo, hi = m.bounds
    out = []
    for a in range(3):
        u, v = reverse.plane_axes(a)
        U, W = np.meshgrid(c[u], c[v], indexing="ij")
        Vm = _moved(V, a)
        rect = box(lo[u] - 2 * tol, lo[v] - 2 * tol, hi[u] + 2 * tol, hi[v] + 2 * tol)
        elems = []                                     # (op, region, cost, label, circle)
        for z0, z1 in itertools.pairwise(PR.wall_heights(m, a)):
            sec = reverse._region(reverse.level_section(m, a, (z0 + z1) / 2))
            if sec is None or sec.is_empty:
                continue
            for g in PR._polys(sec):
                if g.area < 4 * tol * tol:
                    continue
                ext = shapely.Polygon(g.exterior)
                elems.append(("pad", ext, 1 + 0.01 * max(0, len(ext.exterior.coords) - 5), "outline", None))
                for ci, r in _circles(ext, tol):
                    elems.append(("pad", Point(ci).buffer(r, 64), 1.0, "circle", (ci, r)))
                for hole in g.interiors:
                    hp = shapely.Polygon(hole)
                    if hp.area < 4 * tol * tol:
                        continue
                    cs = _circles(hp, tol)
                    if cs:
                        ci, r = cs[0]
                        elems.append(("pocket", Point(ci).buffer(r, 64), 1.0, "hole", (ci, r)))
                    else:
                        elems.append(("pocket", hp, 1 + 0.01 * max(0, len(hole.coords) - 5), "cutout", None))
            for g in PR._polys(rect.difference(sec.buffer(tol / 4, join_style=2))):
                if g.area > 4 * tol * tol:
                    elems.append(("pocket", g, 1 + 0.01 * max(0, len(g.exterior.coords) - 5), "cut", None))
        holes = np.zeros(U.shape, bool)                # a pad's own holes are later cuts: not missing material
        for op, reg, cost, lab, circ in elems:
            if lab == "hole":
                holes |= shapely.contains_xy(reg, U, W)
        masks = []
        for op, reg, cost, lab, circ in elems:
            M = shapely.contains_xy(reg, U, W)
            if M.sum() < 4 or any(o == op and (M ^ Mo).sum() < 0.03 * M.sum() for o, Mo in masks):
                continue
            masks.append((op, M))
            Me = M & ~holes if op == "pad" and (M & ~holes).sum() >= 4 else M
            cov = Vm[Me].mean(axis=0)                  # share of the element filled, per layer along a
            runs = _runs(cov >= 0.9) if op == "pad" else _runs(cov <= 0.1)
            if op == "pad":                            # also extruded to the top of anything above it, for a later
                runs += [r for r in _runs(cov >= 0.02) if r not in runs]   # cut to trim (a rib's sloped top)
            for k0, k in runs:
                z0, z1 = lo[a] + h * k0, lo[a] + h * k
                if op == "pocket":                     # a cut opens to a face: through the end it touches
                    z0 = lo[a] - 2 * tol if k0 == 0 else z0
                    z1 = hi[a] + 2 * tol if k == len(cov) else z1
                out.append(Cand(op=op, a=a, reg=reg, mask=M, k0=k0, k1=k, z0=float(z0), z1=float(z1),
                                cost=cost, label=lab, circle=circ))
    return out


def _runs(want):
    out, k = [], 0
    while k < len(want):
        if not want[k]:
            k += 1
            continue
        k0 = k
        while k < len(want) and want[k]:
            k += 1
        out.append((k0, k))
    return out


def residual_cuts(V, cur, c, h, lo, hi, tol, min_cells=8):
    """Cuts read off what the design has too much of (the designer's 'extruded too far here, cut it back'): along
    each axis, the columns where extra material sits, split into connected regions; each region is cut over the
    longest run of layers in which it holds no real material (<= 2 %). Sketch = the region's cells, simplified."""
    from scipy import ndimage
    out = []
    extra = cur & ~V
    real = cur & V
    for a in range(3):
        u, v = reverse.plane_axes(a)
        E, R = _moved(extra, a), _moved(real, a)
        col = E.any(axis=2)
        lab, n = ndimage.label(col)
        for j in range(1, n + 1):
            M = lab == j
            if M.sum() < min_cells:
                continue
            e = E[M].sum(axis=0)
            r = R[M].sum(axis=0)
            ok = r <= 0.02 * M.sum()
            best, gain = None, 0
            for k0, k1 in _runs(ok):
                g = int(e[k0:k1].sum() - r[k0:k1].sum())
                if g > gain:
                    best, gain = (k0, k1), g
            if best is None or gain < min_cells:
                continue
            k0, k1 = best
            I, Jx = np.nonzero(M)
            cells = [box(c[u][i] - h / 2, c[v][jj] - h / 2, c[u][i] + h / 2, c[v][jj] + h / 2) for i, jj in zip(I, Jx)]
            reg = shapely.union_all(cells).simplify(h * 0.75, preserve_topology=True)
            for g in PR._polys(reg):
                if g.area < 4 * tol * tol:
                    continue
                Mg = shapely.contains_xy(g, *np.meshgrid(c[u], c[v], indexing="ij"))
                z0 = lo[a] - 2 * tol if k0 == 0 else lo[a] + h * k0
                z1 = hi[a] + 2 * tol if k1 == len(e) else lo[a] + h * k1
                out.append(Cand(op="pocket", a=a, reg=g, mask=Mg, k0=k0, k1=k1, z0=float(z0), z1=float(z1),
                                cost=1 + 0.01 * max(0, len(g.exterior.coords) - 5), label="profile cut", circle=None))
    return out


def search(V, cands, beam=BEAM, max_steps=MAX_STEPS, step=STEP, w_extra=0.3, grid=None):
    """Beam search: states (cur, picks, phase, cost, mismatch); J = mismatch / part cells + step * cost. While pads
    are still being chosen, extra material counts at w_extra: a later cut can take it away (extrude to the top, then
    cut the slope), so an over-extrusion is not thrown out of the beam before its cut is tried."""
    total = V.sum()
    pre = {}

    def prefix(D, a):
        Dm = _moved(D, a)
        return np.concatenate([np.zeros(Dm.shape[:2] + (1,), np.int32), np.cumsum(Dm, axis=2, dtype=np.int32)], axis=2)

    def J(mis, cost):
        return mis / total + step * cost

    def soft(cur):
        return float((V & ~cur).sum() + w_extra * (cur & ~V).sum())

    start = (np.zeros_like(V), (), "pad", 0.0, int(total))
    states, best = [start], start
    for _ in range(max_steps):
        kids = []
        for cur, picks, phase, cost, mis in states:
            gains = {}
            if grid is not None and cur.any():
                cands.extend(residual_cuts(V, cur, *grid))
            for op in ("pad", "pocket"):
                if phase == "pocket" and op == "pad":
                    continue
                D = (np.where(cur, 0, np.where(V, 1.0, -w_extra)) * 10).astype(np.int32) if op == "pad" else \
                    np.where(cur, np.where(V, -10, 10), 0).astype(np.int32)
                pre = {a: prefix(D, a) for a in range(3)}
                for i, cd in enumerate(cands):
                    if cd.op != op or i in picks:
                        continue
                    P = pre[cd.a]
                    g = int((P[:, :, cd.k1] - P[:, :, cd.k0])[cd.mask].sum()) / 10
                    if g > 0:
                        gains[i] = g
            base = soft(cur) if phase == "pad" else mis
            for i, g in sorted(gains.items(), key=lambda x: -x[1])[: 3 * beam]:
                cd = cands[i]
                kids.append((J(base - g, cost + cd.cost), i, cur, picks, cd, cost, mis))
        if not kids:
            break
        kids.sort(key=lambda x: x[0])
        nxt, seen = [], set()
        for _, i, cur, picks, cd, cost, mis in kids:
            key = tuple(sorted(picks + (i,)))
            if key in seen:
                continue
            seen.add(key)
            F = np.zeros_like(V)
            Fm = _moved(F, cd.a)
            Fm[cd.mask, cd.k0:cd.k1] = True
            new = (cur | F) if cd.op == "pad" else (cur & ~F)
            nxt.append((new, picks + (i,), cd.op, cost + cd.cost, int((new ^ V).sum())))
            if len(nxt) >= beam:
                break
        states = nxt
        top = min(states, key=lambda s: J(s[4], s[3]))
        if J(top[4], top[3]) < J(best[4], best[3]):
            best = top
        elif all(J(s[4], s[3]) >= J(best[4], best[3]) for s in states):
            break
    return best


def to_tree(cands, picks, tol):
    feats = []
    for i in picks:
        cd = cands[i]
        axis = AXN[cd.a]
        f = {"op": cd.op, "label": f"{'Sketch' if cd.op == 'pad' else 'Cut'} on {PLANE[axis]}: {cd.label}",
             "axis": axis, "at": round(cd.z0, 4), "length": PR._span(cd.z0, cd.z1)}
        if cd.circle is not None:
            ctr, r = cd.circle
            q = PR._uv(axis, [ctr])[0]
            f["loops"] = [[{"t": "circle", "c": [round(float(q[0]), 4), round(float(q[1]), 4)], "r": round(r, 4)}]]
        else:
            f["loops"] = PR.safe_loops(axis, cd.reg, tol, f)
        feats.append(f)
    t = {"units": "mm", "features": feats}
    PR._ids(t)
    return t


def run(m, tol):
    t0 = time.time()
    V, c, h = voxels(m)
    t1 = time.time()
    cands = candidates(m, V, c, h, tol)
    t2 = time.time()
    lo, hi = m.bounds
    best = search(V, cands, grid=(c, h, lo, hi, tol))
    t3 = time.time()
    tree = to_tree(cands, best[1], tol)
    info = {"grid": list(V.shape), "cands": len(cands), "steps": len(best[1]),
            "mismatch": round(best[4] / V.sum(), 4), "t_vox": round(t1 - t0, 2), "t_cands": round(t2 - t1, 2),
            "t_search": round(t3 - t2, 2)}
    return tree, info


if __name__ == "__main__":
    m = trimesh.load(sys.argv[1], force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree, info = run(m, tol)
    print(json.dumps(info))
    for f in tree["features"]:
        print(f["id"], f["op"], f["axis"], f["at"], f["length"], f["label"])
    if len(sys.argv) > 2:
        json.dump(tree, open(sys.argv[2], "w"), indent=1)
