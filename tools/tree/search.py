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
STEP = 0.0015                                          # a step must fix this share of the part's volume
BEAM = 12
MAX_STEPS = 24


def voxels(m, n=N, thin=24, cap=4_000_000):
    """Occupancy on a cubic grid: [ix, iy, iz] bool, plus cell centres per axis and the pitch. The thinnest side gets
    at least `thin` cells (part 27, a 13.9 mm plate 152 mm wide, had 12 through its thickness), within `cap` cells."""
    lo, hi = m.bounds
    ext = hi - lo
    h = min(float(ext.max()) / n, float(ext.min()) / thin)
    h = max(h, float(np.prod(ext) / cap) ** (1 / 3))
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
    __slots__ = ("op", "a", "reg", "mask", "k0", "k1", "z0", "z1", "cost", "label", "circle", "mirror", "feat")

    def __init__(self, **kw):
        self.mirror = None
        self.feat = None
        for k, v in kw.items():
            setattr(self, k, v)


def seed_cands(trees, V, c, h, tol):
    """Every pad/pocket another approach produced (proposal, three planes, planner) as a candidate, its feature kept
    verbatim: the search then combines all approaches' steps with its own and drops what does not earn its place
    (the owner: 'all the potential approaches are tested in parallel ... the approach with less number of steps is
    chosen')."""
    out, seen = [], set()
    for tree in trees:
        for f in tree.get("features", []):
            if f.get("op") not in ("pad", "pocket") or not isinstance(f.get("length"), (int, float)) or not f.get("loops"):
                continue
            key = json.dumps([f["op"], f["axis"], f["at"], f["length"], f["loops"]], sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            a = AXN.index(f["axis"])
            ru, rv = reverse.plane_axes(a)
            mu, mv = T.UV[f["axis"]]

            def to_rev(P):                             # tree (u, v) -> the search's plane coords (sorted axes)
                P = np.asarray(P, float)
                p3 = np.zeros((len(P), 3)); p3[:, mu] = P[:, 0]; p3[:, mv] = P[:, 1]
                return np.c_[p3[:, ru], p3[:, rv]]
            try:
                reg = shapely.Polygon(to_rev(T.loop_polygon(f["loops"][0])),
                                      [to_rev(T.loop_polygon(lp)) for lp in f["loops"][1:]]).buffer(0)
            except Exception:                          # noqa: BLE001 -- an unreadable sketch only costs this seed
                continue
            U, W = np.meshgrid(c[ru], c[rv], indexing="ij")
            M = shapely.contains_xy(reg, U, W)
            z0, z1 = sorted((float(f["at"]), float(f["at"]) + float(f["length"])))
            ks = np.nonzero((c[a] >= z0) & (c[a] <= z1))[0]
            if M.sum() < 4 or not len(ks):
                continue
            nseg = sum(len(lp) for lp in f["loops"])
            out.append(Cand(op=f["op"], a=a, reg=reg, mask=M, k0=int(ks[0]), k1=int(ks[-1]) + 1, z0=z0, z1=z1,
                            cost=1 + 0.01 * max(0, nseg - 4), label=f.get("label", "seed"), circle=None, feat=f))
    return out


MIRROR_COST = 0.35                                     # a mirror step: cheaper than drawing the copy again


def symmetry_axes(V, c, h, tol=0.03):
    """Axes the part is mirror-symmetric across (about the grid's middle): [(axis, mid coordinate)]."""
    out = []
    for s in range(3):
        if (V ^ np.flip(V, s)).sum() < tol * V.sum():
            out.append((s, float(c[s][0] - h / 2 + len(c[s]) * h / 2)))
    return out


def mirror_cands(cands, picks, sym):
    """A mirrored copy of every picked feature across every symmetry plane (the owner on part 2: 'then mirroring
    on the opposite side'), unless the copy would land on the feature itself."""
    import shapely.affinity as aff
    out = []
    for i in picks:
        cd = cands[i]
        if cd.mirror is not None:
            continue
        for s, mid in sym:
            if s == cd.a:
                n = cd.mask.shape and None
                k0, k1, M, reg = None, None, cd.mask, cd.reg
                z0, z1 = 2 * mid - cd.z1, 2 * mid - cd.z0
            else:
                u, v = reverse.plane_axes(cd.a)
                dim = 0 if s == u else 1
                M = np.flip(cd.mask, dim)
                if (M ^ cd.mask).sum() < 0.1 * cd.mask.sum():
                    continue                           # symmetric already: its mirror is itself
                reg = aff.scale(cd.reg, xfact=-1 if dim == 0 else 1, yfact=-1 if dim == 1 else 1, origin=(mid, mid))
                z0, z1 = cd.z0, cd.z1
            out.append((i, s, mid, M, reg, z0, z1))
    return out


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
        levels = PR.wall_heights(m, a)
        for z0, z1 in itertools.pairwise(levels):
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
                z0, z1 = _snap(lo[a] + h * k0, levels, h), _snap(lo[a] + h * k, levels, h)
                if op == "pocket":                     # a cut opens to a face: through the end it touches
                    z0 = lo[a] - 2 * tol if k0 == 0 else z0
                    z1 = hi[a] + 2 * tol if k == len(cov) else z1
                out.append(Cand(op=op, a=a, reg=reg, mask=M, k0=k0, k1=k, z0=float(z0), z1=float(z1),
                                cost=cost, label=lab, circle=circ))
    return out


def _snap(z, levels, h):
    """A grid boundary moved onto the part's true level within one cell (part 2's floor came out at 5.47, not 5)."""
    near = min(levels, key=lambda L: abs(L - z))
    return float(near) if abs(near - z) <= h else float(z)


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


def residual_cuts(V, cur, c, h, lo, hi, tol, m, seen, min_cells=8):
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
            key = (a, k0, k1, hash(M.tobytes()))
            if key in seen:
                continue
            seen.add(key)
            I, Jx = np.nonzero(M)
            cells = shapely.union_all([box(c[u][i] - h / 2, c[v][jj] - h / 2, c[u][i] + h / 2, c[v][jj] + h / 2)
                                       for i, jj in zip(I, Jx)])
            # the exact outline, not the cells': the empty space beside the part's projection over this run,
            # kept to the cells' neighbourhood (a sloped profile is one straight line, not a staircase)
            za, zb = max(lo[a], lo[a] + h * k0), min(hi[a], lo[a] + h * k1)
            proj = PR.slab_region(m, a, za, zb) if zb - za > tol else None
            reg = cells.buffer(h).difference(proj.buffer(tol / 4, join_style=2)) if proj is not None else cells
            reg = reg.intersection(cells.buffer(h))
            for g in PR._polys(reg):
                if g.area < 4 * tol * tol:
                    continue
                Mg = shapely.contains_xy(g, *np.meshgrid(c[u], c[v], indexing="ij"))
                levels = PR.wall_heights(m, a)
                z0 = lo[a] - 2 * tol if k0 == 0 else _snap(lo[a] + h * k0, levels, h)
                z1 = hi[a] + 2 * tol if k1 == len(e) else _snap(lo[a] + h * k1, levels, h)
                out.append(Cand(op="pocket", a=a, reg=g, mask=Mg, k0=k0, k1=k1, z0=float(z0), z1=float(z1),
                                cost=1 + 0.01 * max(0, len(g.exterior.coords) - 5), label="profile cut", circle=None))
    return out


def search(V, cands, beam=BEAM, max_steps=MAX_STEPS, step=STEP, w_extra=0.3, grid=None, sym=(), patience=3,
           stock=None):
    """Beam search: states (cur, picks, phase, cost, mismatch); J = mismatch / part cells + step * cost. While pads
    are still being chosen, extra material counts at w_extra: a later cut can take it away (extrude to the top, then
    cut the slope), so an over-extrusion is not thrown out of the beam before its cut is tried."""
    total = V.sum()
    pre, seen = {}, set()

    def prefix(D, a):
        Dm = _moved(D, a)
        return np.concatenate([np.zeros(Dm.shape[:2] + (1,), np.int32), np.cumsum(Dm, axis=2, dtype=np.int32)], axis=2)

    def J(mis, cost):
        return mis / total + step * cost

    def soft(cur):
        return float((V & ~cur).sum() + w_extra * (cur & ~V).sum())

    start = (np.zeros_like(V), (), "pad", 0.0, int(total))
    states = [start]
    if stock is not None:
        # the canister: the whole stock block, then only cuts flowing into the empty space round the part (the
        # owner: 'mimic water molecules filling a canister, in which your object is inside'); both starts share one
        # beam and one measure, so the additive and the subtractive design compete directly
        cands.append(stock)
        full = np.ones_like(V)
        states.append((full, (len(cands) - 1,), "pocket", stock.cost, int((full ^ V).sum())))
    best, stale = min(states, key=lambda s: J(s[4], s[3])), 0
    for _ in range(max_steps):
        kids = []
        for si, (cur, picks, phase, cost, mis) in enumerate(states):
            gains = {}
            if grid is not None and cur.any() and si < 3:
                cands.extend(residual_cuts(V, cur, *grid, seen))
            if sym:
                for i, sx, mid, M, reg, z0, z1 in mirror_cands(cands, picks, sym):
                    key = ("mirror", i, sx)
                    if key in seen:
                        continue
                    seen.add(key)
                    src = cands[i]
                    n_a = V.shape[src.a]
                    k0, k1 = (n_a - src.k1, n_a - src.k0) if sx == src.a else (src.k0, src.k1)
                    cands.append(Cand(op=src.op, a=src.a, reg=reg, mask=M, k0=k0, k1=k1, z0=z0, z1=z1,
                                      cost=MIRROR_COST, label=f"mirror of {src.label}", circle=None, mirror=(i, sx, mid)))
            for op in ("pad", "pocket"):
                if phase == "pocket" and op == "pad":
                    continue
                # one objective for every state and op, soft = missing + w_extra * extra: a cut's removed extra
                # counts at w_extra too (counted at 1 it made any wild over-extrusion look brilliant once cut back,
                # and those flooded the beam: part 15 lost its holes to them)
                D = (np.where(cur, 0, np.where(V, 1.0, -w_extra)) * 10).astype(np.int32) if op == "pad" else \
                    (np.where(cur, np.where(V, -1.0, w_extra), 0) * 10).astype(np.int32)
                pre = {a: prefix(D, a) for a in range(3)}
                for i, cd in enumerate(cands):
                    if cd.op != op or i in picks or (cd.mirror is not None and cd.mirror[0] not in picks):
                        continue
                    P = pre[cd.a]
                    g = int((P[:, :, cd.k1] - P[:, :, cd.k0])[cd.mask].sum()) / 10
                    if g > 0:
                        gains[i] = g
            base = soft(cur)
            for i, g in sorted(gains.items(), key=lambda x: -x[1])[: 3 * beam]:
                cd = cands[i]
                kids.append((J(base - g, cost + cd.cost), i, cur, picks, cd, cost, mis))
        if not kids:
            break
        kids.sort(key=lambda x: x[0])
        nxt, done = [], set()
        for _, i, cur, picks, cd, cost, mis in kids:
            key = tuple(sorted(picks + (i,)))
            if key in done:
                continue
            done.add(key)
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
            best, stale = top, 0
        else:                                          # a design often pays off two steps later (extrude, then
            stale += 1                                 # cut): stop only after `patience` steps without a better one
            if stale >= patience:
                break
    return best


def to_tree(cands, picks, tol):
    feats, fid = [], {}
    for n, i in enumerate(picks):
        cd = cands[i]
        axis = AXN[cd.a]
        fid[i] = f"F{n + 1}"
        lab = f"{'Sketch' if cd.op == 'pad' else 'Cut'} on {PLANE[axis]}: {cd.label}"
        if cd.mirror is not None:
            lab = f"Mirror of {fid.get(cd.mirror[0], '?')} across {PLANE[AXN[cd.mirror[1]]]}"
        f = {"op": cd.op, "label": lab, "axis": axis, "at": round(cd.z0, 4), "length": PR._span(cd.z0, cd.z1)}
        if cd.mirror is not None:
            f["mirror_of"] = fid.get(cd.mirror[0])
        if cd.feat is not None and cd.mirror is None:
            f = {k: v for k, v in cd.feat.items() if k != "id"}
            feats.append(f)
            continue
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


STRATEGIES = [                                         # (step weight, extra weight): how small a feature may be
    (0.001, 0.3), (0.003, 0.3), (0.008, 0.3),          # before it is left to the finishes, and how much temporary
    (0.003, 0.6),                                      # extra material a design may carry before its cut
]


def portfolio(m, tol, budget=240.0, strategies=STRATEGIES, seeds=()):
    """The elastic part (the owner: 'something elastic and adaptable, focused on result'): the search run under
    several strategies, each winner finished and measured on the real solid, the best by the choice's own measure
    (score - 0.001 per step) kept. Searches take seconds; finishing is the cost, so the raw designs are finished in
    order of their raw measure while the budget lasts. -> (tree, info)"""
    import copy
    t0 = time.time()
    V, c, h = voxels(m)
    base = candidates(m, V, c, h, tol) + seed_cands(seeds, V, c, h, tol)
    lo, hi = m.bounds
    sym = symmetry_axes(V, c, h)
    raw = []
    for k, sd in enumerate(seeds):                     # each other approach's own design competes as it is: the
        t = {"units": "mm", "features": [dict(f) for f in sd["features"]]}   # result is never worse than the best
        PR._ids(t, keep_refs=True)
        sc = PR._forked(PR.pick_score, t, m, tol, default=-1.0)
        raw.append((sc - 0.001 * len(t["features"]), ("seed", k), t, json.dumps(t["features"], sort_keys=True), None))
    a = PR.sketch_axis(m)                              # the stock block, extruded along the part's main axis
    u, v = reverse.plane_axes(a)
    stock = Cand(op="pad", a=a, reg=box(lo[u], lo[v], hi[u], hi[v]), mask=np.ones((len(c[u]), len(c[v])), bool),
                 k0=0, k1=len(c[a]), z0=float(lo[a]), z1=float(hi[a]), cost=1.0, label="stock", circle=None)
    for st, we in strategies:
        cands = list(base)
        b = search(V, cands, grid=(c, h, lo, hi, tol, m), sym=sym, step=st, w_extra=we, stock=stock)
        t = to_tree(cands, b[1], tol)
        sig = json.dumps([(f["op"], f["axis"], f["at"], f["length"]) for f in t["features"]])
        if any(sig == r[3] for r in raw):
            continue                                   # the same design from another strategy
        sc = PR._forked(PR.pick_score, t, m, tol, default=-1.0)
        raw.append((sc - 0.001 * len(t["features"]), (st, we), t, sig, round(b[4] / V.sum(), 4)))
    raw.sort(key=lambda r: -r[0])
    best, log = None, []
    for mr, strat, t, _, mis in raw:
        if best is not None and time.time() - t0 > budget:
            log.append({"strategy": strat, "raw_merit": round(mr, 4), "finished": False})
            continue
        t = copy.deepcopy(t)
        PR.edge_mods(t, m, tol)
        PR.prune(t, m, tol)
        sc = PR._forked(PR.pick_score, t, m, tol, default=-1.0)
        fm = sc - 0.001 * len(t["features"])
        log.append({"strategy": strat, "raw_merit": round(mr, 4), "merit": round(fm, 4), "steps": len(t["features"]),
                    "voxel_mismatch": mis})
        if best is None or fm > best[0]:
            best = (fm, t)
    return best[1], {"grid": list(V.shape), "cands": len(base), "strategies": log, "seconds": round(time.time() - t0, 1)}


def run(m, tol, finish=True):
    t0 = time.time()
    V, c, h = voxels(m)
    t1 = time.time()
    cands = candidates(m, V, c, h, tol)
    t2 = time.time()
    lo, hi = m.bounds
    best = search(V, cands, grid=(c, h, lo, hi, tol, m), sym=symmetry_axes(V, c, h))
    t3 = time.time()
    tree = to_tree(cands, best[1], tol)
    t4 = time.time()
    if finish:
        PR.edge_mods(tree, m, tol)                     # rounds/chamfers: below the grid's resolution
        PR.prune(tree, m, tol)
    info = {"t_finish": round(time.time() - t4, 1), "grid": list(V.shape), "cands": len(cands), "steps": len(best[1]),
            "mismatch": round(best[4] / V.sum(), 4), "t_vox": round(t1 - t0, 2), "t_cands": round(t2 - t1, 2),
            "t_search": round(t3 - t2, 2)}
    return tree, info


if __name__ == "__main__":
    m = trimesh.load(sys.argv[1], force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree, info = portfolio(m, tol)
    print(json.dumps(info))
    for f in tree["features"]:
        print(f["id"], f["op"], f.get("axis", ""), f.get("at", ""), f.get("length", f.get("size", "")), f["label"])
    if len(sys.argv) > 2:
        json.dump(tree, open(sys.argv[2], "w"), indent=1)
