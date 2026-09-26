"""Reverse design search (the owner: 'take the object and calculate the sequence of steps to return to 1 or 2 planes,
then choose the shortest').

The object is undone one operation at a time on a voxel grid until what is left is a trivial base:
  - one plane: every column along an axis is one interval, each distinct interval one differential extrusion
    ('single 2d elements that extrude differentially');
  - two planes: the intersection of two prisms (a profile extruded on one plane, cut through from another).
Undo moves, read off the current state, never guessed:
  - fill a cut: a connected piece of (prism hull along a) - (state), filled back;
  - remove an addition: a connected piece of the state sticking out of its dominant slab along an axis, removed.
A move is legal along an axis c when its piece is a union of prisms along c that neither cuts material nor adds air
(one step per distinct column interval, a differential cut or pad). Undoing is exact by construction: re-applying
the moves in reverse order rebuilds the state. Residues below FINISH are the finishes' (rounds/chamfers), left to
propose.edge_mods. The shortest total (undos + base) wins.

usage: reverse_steps.py <mesh.stl> [out_tree.json]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import search as SE                                    # noqa: E402

FINISH = 0.10          # (the current level of LEVELS) share of the volume a base may miss or overfill, all of it thin (the finishes' residue)
THIN = 2               # a finish's residue is gone after this many erosions (a round's wedge is 0.29 r thick)
SOLID = 0.005          # share of the volume allowed to survive them (a missing pocket survives)
MIN_PIECE = 0.002      # a piece smaller than this share of the volume is finish residue, not a feature
LEAK = 0.03            # share of a move's prisms allowed to cut material / add air (staircase of the grid)
BEAM = 8
DEPTH = 10
MOVES = 24             # largest undos tried per state: a feature is found by its big pieces first


def _intervals(A):
    """Per column along the last axis: (present, contiguous, first, last)."""
    n = A.shape[2]
    has = A.any(axis=2)
    first = np.where(has, A.argmax(axis=2), -1)
    last = np.where(has, n - 1 - A[:, :, ::-1].argmax(axis=2), -1)
    cont = A.sum(axis=2) == np.where(has, last - first + 1, 0)
    return has, cont, first, last


def _groups(first, last, sel, min_cols):
    """Distinct column intervals (clustered within one cell) among the selected columns -> [(k0, k1, mask)]."""
    out = []
    pairs, cnt = np.unique(np.stack([first[sel], last[sel]], 1), axis=0, return_counts=True)
    order = np.argsort(-cnt)
    taken = []
    for i in order:
        k0, k1 = pairs[i]
        for g in taken:
            if abs(g[0] - k0) <= 1 and abs(g[1] - k1) <= 1:
                break
        else:
            taken.append((int(k0), int(k1)))
    lab = np.full(first.shape, -1)
    for j, (k0, k1) in enumerate(taken):
        hit = sel & (np.abs(first - k0) <= 1) & (np.abs(last - k1) <= 1) & (lab < 0)
        lab[hit] = j
    for j, (k0, k1) in enumerate(taken):
        M = lab == j
        if _flat(M, min_cols):
            out.append((k0, k1 + 1, M))
    return out


def _flat(M, min_cols):
    """A sketch element is a flat face: its columns survive a one-cell erosion. The bands a round, chamfer or
    slope leaves (one level per cell of staircase) do not."""
    return ndimage.binary_erosion(M).sum() >= max(min_cols, 0.25 * M.sum())


def as_prisms(P, V, want, min_cols):
    """P (a piece) as prisms along each axis: the cheapest axis where every column of P is one interval and the
    prisms leak into the wrong side (`want`=False: material, a cut; True: air, a pad) by <= LEAK.
    -> (steps, axis, [(k0, k1, mask)]) or None."""
    best = None
    for a in range(3):
        Pa, Va = SE._moved(P, a), SE._moved(V, a)
        has, cont, first, last = _intervals(Pa)
        if has.sum() == 0 or cont[has].mean() < 0.97:
            continue
        gs = _groups(first, last, has & cont, min_cols)
        if not gs:
            continue
        vol = leak = 0
        for k0, k1, M in gs:
            slab = Va[:, :, k0:k1][M]
            vol += slab.size
            leak += int((slab if not want else ~slab).sum())
        covered = sum(int(Pa[:, :, k0:k1][M].sum()) for k0, k1, M in gs)
        if vol == 0 or leak > LEAK * vol or covered < 0.9 * P.sum():
            continue
        if best is None or len(gs) < best[0]:
            best = (len(gs), a, gs)
    return best


def _residue_ok(X, V, tot):
    R = X ^ V
    n = int(R.sum())
    return n <= FINISH * tot and (n <= SOLID * tot or ndimage.binary_erosion(R, iterations=THIN).sum() <= SOLID * tot)


def hulls(V):
    return [np.broadcast_to(V.any(axis=a, keepdims=True), V.shape) for a in range(3)]


def bases(V, tot, min_cols):
    """Trivial bases that reproduce V within FINISH -> [(steps, kind, data)]."""
    out = []
    H = hulls(V)
    for a in range(3):                                 # one plane: differential extrusions along a
        Va = SE._moved(V, a)
        has, cont, first, last = _intervals(Va)
        if cont[has].mean() < 0.97:
            continue
        gs = _groups(first, last, has, min_cols)
        if not gs:
            continue
        # one sketch plane: the extrusions share their start face (the bottom, or else the top)
        side = [[g for g in gs if abs(g[e] - gs[0][e]) <= 1] for e in (0, 1)]
        gs = max(side, key=lambda q: sum(int(g[2].sum()) for g in q))
        # every column to its nearest flat element: the staircase bands become the finishes' residue
        G = np.array([(k0, k1 - 1) for k0, k1, _ in gs])
        near = (np.abs(first[..., None] - G[:, 0]) + np.abs(last[..., None] - G[:, 1])).argmin(axis=-1)
        X = np.zeros_like(Va)
        for j, (k0, k1, _) in enumerate(gs):
            X[:, :, k0:k1] |= (has & (near == j))[:, :, None]
        if _residue_ok(X, Va, tot):
            out.append((len(gs), "extrude", (a, gs)))
    for a in range(3):                                 # two planes: prism along a cut by the prism along b
        for b in range(a + 1, 3):
            if _residue_ok(H[a] & H[b], V, tot):
                out.append((2, "intersect", (a, b)))
    return out


def _clusters(K):
    """Values of K grouped within one cell round the commonest -> [(centre, member mask)]."""
    vals, cnt = np.unique(K, return_counts=True)
    free = np.ones(len(vals), bool)
    out = []
    for g in np.argsort(-cnt):
        if not free[g]:
            continue
        near = free & (np.abs(vals - vals[g]) <= 1)
        free &= ~near
        out.append((int(vals[g]), np.isin(K, vals[near])))
    return out


def pieces(A, a, min_cols, starts=3):
    """A as prisms along axis a -> [(k0, k1, mask2d, piece3d)], each a prism by construction (one step). The runs of
    A along a are grouped by one shared end face; the prism starts where the commonest runs start, so a cut through
    air that is already there (a lateral cut running into a slope) is one piece, not one per staircase level. Runs
    that start later are left for other moves. Same from the start face."""
    Aa = SE._moved(A, a)
    pad = np.zeros(Aa.shape[:2] + (1,), bool)
    d = np.diff(np.concatenate([pad, Aa, pad], axis=2).astype(np.int8), axis=2)
    I, J, K0 = np.nonzero(d == 1)                      # run starts and ends come in the same column order
    K1 = np.nonzero(d == -1)[2]
    out, seen = [], set()
    if not len(I):
        return out
    for face, other, sign in ((K1, K0, 1), (K0, K1, -1)):
        for e, sel in _clusters(face):
            ks = [k for k, _ in _clusters(other[sel])][:starts]
            for k in ks:                               # runs reaching past k (sign 1: starting at or before it)
                inner = sel & ((other <= k + 1) if sign > 0 else (other >= k - 1))
                k0, k1 = (k, e) if sign > 0 else (e, k)
                if k1 - k0 < 1:
                    continue
                M = np.zeros(Aa.shape[:2], bool)
                M[I[inner], J[inner]] = True
                lab, n = ndimage.label(M)
                for q in range(1, n + 1):
                    Mq = lab == q
                    if not _flat(Mq, min_cols):
                        continue
                    key = (k0, k1, hash(np.packbits(Mq).tobytes()))
                    if key in seen:
                        continue
                    seen.add(key)
                    P = np.zeros_like(Aa)
                    P[:, :, k0:k1] = Mq[:, :, None]
                    out.append((k0, k1, Mq, np.moveaxis(P, 2, a)))
    return out


def moves(V, tot, min_cols):
    """Legal undos from V -> [(steps, kind, axis, groups, piece)]: fill a prism of air inside the visual hull (undo
    a cut), or remove a prism of material that sticks out of a dominant slab (undo a pad). A pad may overlap the
    body, so the whole prism goes, found along any axis (part 4's arms: prisms along X standing on a Z plate)."""
    out, seen = [], set()
    thr = max(8, MIN_PIECE * tot)
    H = hulls(V)
    air = H[0] & H[1] & H[2] & ~V
    stick = np.zeros_like(V)
    for a in range(3):
        Va = SE._moved(V, a)
        has, _, first, last = _intervals(Va)
        pairs, cnt = np.unique(np.stack([first[has], last[has]], 1), axis=0, return_counts=True)
        k0, k1 = pairs[cnt.argmax()]
        st = Va.copy()
        st[:, :, max(0, k0 - 1):k1 + 2] = False
        stick |= np.moveaxis(st, 2, a)

    def keep(kind, a, p0, p1, M, P):
        key = hash(np.packbits(P).tobytes())
        if key not in seen:
            seen.add(key)
            out.append((1, kind, a, [(p0, p1, M)], P))

    for a in range(3):
        for p0, p1, M, P in pieces(air, a, min_cols):
            if P.sum() >= thr and (P & V).sum() <= LEAK * P.sum():
                keep("cut", a, p0, p1, M, P & ~V)
        for p0, p1, M, P in pieces(V, a, min_cols):
            n = P.sum()
            if thr <= n <= 0.8 * tot and (P & stick).sum() >= 0.3 * n:
                keep("add", a, p0, p1, M, P)
    return out


def estimate(S, tot, min_cols):
    """Steps still needed from S, optimistic: its cheapest base, or per axis its column intervals plus one step per
    share of columns not yet one interval (each needs at least one more undo)."""
    b = bases(S, tot, min_cols)
    if b:
        return min(x[0] for x in b)
    est = []
    for a in range(3):
        has, cont, first, last = _intervals(SE._moved(S, a))
        est.append(len(_groups(first, last, has & cont, min_cols)) + int(np.ceil(10 * (~cont[has]).mean())))
    return min(est)


def reverse(V):
    """Beam search over undo sequences -> (total steps, undos in undo order, base)."""
    tot = int(V.sum())
    min_cols = max(3, int(0.001 * tot ** (2 / 3)))
    best = (np.inf, [], None)
    beam, seen = [(0, V, [])], set()
    for _ in range(DEPTH + 1):
        nxt = []
        for g, S, hist in beam:
            for bs in bases(S, tot, min_cols):
                if g + bs[0] < best[0]:
                    best = (g + bs[0], hist, bs)
            if g + 1 >= best[0]:
                continue
            mvs = sorted(moves(S, tot, min_cols), key=lambda x: -int(x[4].sum()))[:MOVES]
            for mv in mvs:
                if g + mv[0] >= best[0]:
                    continue
                S2 = S | mv[4] if mv[1] == "cut" else S & ~mv[4]
                key = hash(np.packbits(S2).tobytes())
                if key in seen:
                    continue
                seen.add(key)
                nxt.append((g + mv[0], S2, hist + [mv[:4]], estimate(S2, tot, min_cols)))
        if not nxt:
            break
        nxt.sort(key=lambda s: (s[0] + s[3], s[0]))
        beam = [s[:3] for s in nxt[:BEAM]]
    return best


def describe(best):
    total, hist, bs = best
    AX = "XYZ"
    lines = []
    if bs is not None:
        if bs[1] == "extrude":
            a, gs = bs[2]
            lines.append(f"base: sketch on plane normal {AX[a]}, {len(gs)} differential extrusion(s) "
                         + ", ".join(f"[{k0},{k1})" for k0, k1, _ in gs))
        else:
            lines.append(f"base: prism along {AX[bs[2][0]]} cut by prism along {AX[bs[2][1]]}")
    for st, kind, a, gs in reversed(hist):             # forward order: last undo is the first operation
        lines.append(f"{'cut' if kind == 'cut' else 'pad'} along {AX[a]}: {st} step(s) "
                     + ", ".join(f"[{k0},{k1})" for k0, k1, _ in gs))
    return total, lines


def to_tree(m, V, c, h, best, tol):
    """The undo sequence, reversed, as a tree: base pads, then each undone cut/addition. Outlines come from the mesh,
    not the cells: a pad's from a thin slab mid-way up its own band (clear of the finishes at its top), a cut's from
    the empty space beside the part's projection over its run, kept to the cells' neighbourhood."""
    import shapely
    from shapely.geometry import box
    _, hist, bs = best
    lo, hi = m.bounds
    levels = {}

    def z(a, k):
        if k <= 0:
            return float(lo[a])
        if k >= V.shape[a]:
            return float(hi[a])
        if a not in levels:
            levels[a] = SE.PR.wall_heights(m, a)
        return SE._snap(lo[a] + h * k, levels[a], h)

    def cells(a, M):
        u, v = SE.reverse.plane_axes(a)
        I, J = np.nonzero(M)
        return shapely.union_all([box(c[u][i] - h / 2, c[v][j] - h / 2, c[u][i] + h / 2, c[v][j] + h / 2)
                                  for i, j in zip(I, J)])

    cands = []

    def add(op, a, reg, z0, z1, label):
        for g in SE.PR._polys(reg):
            if g.area > 4 * tol * tol:
                cands.append(SE.Cand(op=op, a=a, reg=g, mask=None, k0=0, k1=0, z0=z0, z1=z1, cost=1, label=label,
                                     circle=None))

    moves_out = []                                     # the undone operations, forward order, exact outlines
    for _, kind, b, gs in reversed(hist):
        k0, k1, M = gs[0]
        z0, z1 = z(b, k0), z(b, k1)
        proj = SE.PR.slab_region(m, b, z0, z1)
        if kind == "cut":                              # cutting air is free: reach 3 cells, the material bounds it
            near = cells(b, M).buffer(3 * h, join_style=2)
            z0 = z0 - 2 * tol if k0 == 0 else z0
            z1 = z1 + 2 * tol if k1 >= V.shape[b] else z1
            reg = near.difference(proj.buffer(tol / 4, join_style=2))
        else:
            reg = proj.intersection(cells(b, M).buffer(h))
        moves_out.append((kind, b, reg, z0, z1))

    def across(a, zm=None):
        """What the undone moves filled (cuts) and removed (additions) in the plane across a: at height zm, or
        seen along a (zm None). The base is the filled state, not the part: its outline is the part's plus the
        fills minus the removals, or the cuts would find nothing left to cut."""
        ua, va = SE.reverse.plane_axes(a)
        fill, rem = [], []
        for kind, b, reg, z0, z1 in moves_out:
            if b == a:
                piece = reg if zm is None or z0 <= zm <= z1 else None
            else:
                ub, vb = SE.reverse.plane_axes(b)
                w = vb if ub == a else ub              # the plane-b axis that is also in plane a
                parts = []
                for g in SE.PR._polys(reg):
                    if zm is None:                     # the prism's shadow along a
                        x0, y0, x1, y1 = g.bounds
                        spans = [(y0, y1)] if ub == a else [(x0, x1)]
                    else:                              # the prism's slice at a = zm
                        big = 1e6
                        line = box(zm - 1e-9, -big, zm + 1e-9, big) if ub == a else box(-big, zm - 1e-9, big, zm + 1e-9)
                        cut = g.intersection(line)
                        spans = [(q.bounds[1], q.bounds[3]) if ub == a else (q.bounds[0], q.bounds[2])
                                 for q in (cut.geoms if hasattr(cut, "geoms") else [cut]) if not q.is_empty]
                    for w0, w1 in spans:
                        parts.append(box(w0, z0, w1, z1) if ua == w else box(z0, w0, z1, w1))
                piece = shapely.union_all(parts) if parts else None
            if piece is not None and not piece.is_empty:
                (fill if kind == "cut" else rem).append(piece)
        return shapely.union_all(fill) if fill else None, shapely.union_all(rem) if rem else None

    def state(a, reg, zm=None):
        f, r = across(a, zm)
        if f is not None:
            reg = reg.union(f)
        if r is not None:
            reg = reg.difference(r)
        return reg

    if bs[1] == "extrude":
        a, gs = bs[2]
        bottom = len({g[0] for g in gs}) <= len({g[1] for g in gs}) or len(gs) == 1
        gs = sorted(gs, key=lambda g: g[1] if bottom else -g[0])
        prev = None
        for k0, k1, _ in gs:                           # tallest last; each pad's outline from its own band
            z0, z1 = z(a, k0), z(a, k1)
            if bottom:
                zm = (max(z0, prev) + z1) / 2 if prev is not None else (z0 + z1) / 2
                prev = z1
            else:
                zm = (z0 + min(z1, prev)) / 2 if prev is not None else (z0 + z1) / 2
                prev = z0
            add("pad", a, state(a, SE.PR.slab_region(m, a, zm - h / 4, zm + h / 4), zm), z0, z1,
                "differential extrusion")
    else:
        a, b = bs[2]
        add("pad", a, state(a, SE.PR.slab_region(m, a, float(lo[a]), float(hi[a]))), float(lo[a]), float(hi[a]),
            "profile")
        u, v = SE.reverse.plane_axes(b)
        outside = box(lo[u] - tol, lo[v] - tol, hi[u] + tol, hi[v] + tol).difference(
            state(b, SE.PR.slab_region(m, b, float(lo[b]), float(hi[b]))).buffer(tol / 4, join_style=2))
        add("pocket", b, outside, float(lo[b]) - 2 * tol, float(hi[b]) + 2 * tol, "second profile, cut through")
    for kind, b, reg, z0, z1 in moves_out:
        add("pocket" if kind == "cut" else "pad", b, reg, z0, z1, "cut" if kind == "cut" else "boss")
    return SE.to_tree(cands, list(range(len(cands))), tol)


LEVELS = (0.10, 0.02)   # FINISH levels tried: whether a thin residue is a finish or a slope is the real score's call


def run(m, tol, finish=True):
    """reverse() at each residue level, each distinct result emitted, finished and scored on the real solid; the
    best merit (score - 0.001 per step) kept. -> (tree, info)"""
    global FINISH
    t0 = time.time()
    V, c, h = SE.voxels(m)
    best, info, seen = None, {"grid": list(V.shape), "levels": []}, set()
    for lv in LEVELS:
        FINISH = lv
        r = reverse(V)
        if r[2] is None:
            info["levels"].append({"finish": lv, "undo_steps": None})
            continue
        sig = "|".join(describe(r)[1])
        if sig in seen:
            continue
        seen.add(sig)
        tree = to_tree(m, V, c, h, r, tol)
        if finish:
            SE.PR.edge_mods(tree, m, tol)              # rounds/chamfers: the residue the bases left
            SE.PR.prune(tree, m, tol)
        sc = SE.PR._forked(SE.PR.pick_score, tree, m, tol, default=-1.0)
        mr = sc - 0.001 * len(tree["features"])
        info["levels"].append({"finish": lv, "undo_steps": int(r[0]), "score": round(sc, 4),
                               "steps": len(tree["features"]), "merit": round(mr, 4)})
        if best is None or mr > best[0]:
            best = (mr, tree, sc)
    FINISH = LEVELS[0]
    info["t_total"] = round(time.time() - t0, 1)
    if best is None:
        return None, info
    info.update(score=round(best[2], 4), steps=len(best[1]["features"]), merit=round(best[0], 4))
    return best[1], info


if __name__ == "__main__":
    import trimesh
    m = trimesh.load(sys.argv[1], force="mesh")
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree, info = run(m, tol, finish="--raw" not in sys.argv)
    print(json.dumps(info))
    for f in (tree or {}).get("features", []):
        print(f["id"], f["op"], f.get("axis", ""), f.get("at", ""), f.get("length", f.get("size", "")), f["label"])
    out = [x for x in sys.argv[2:] if not x.startswith("--")]
    if tree is not None and out:
        json.dump(tree, open(out[0], "w"), indent=1)
