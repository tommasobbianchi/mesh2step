"""Mesh -> proposed feature tree, deterministically ($0). The LLM and the owner only confirm or correct it.

1. main extrusion (reverse.py): axis, outline sketch, holes, stacked levels, cap rounds;
2. cap modifier: round or chamfer, told apart by the section inset at half its depth (round 0.13 d, chamfer 0.5 d);
3. residual: compile, find the mesh the solid does not explain, fit cylinders on any principal axis -> holes
   (normals toward the axis) or bosses, coaxial pieces merged (a screw hole through two jaws is one hole).
usage: propose.py <mesh> <out_tree.json>
"""
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "recon"))
import reverse                                        # noqa: E402
import tree as T                                      # noqa: E402

AXN = "XYZ"
MAX_CUTS = 16                                          # orthogonal-scan cuts kept per tree, biggest bites first


def _uv(axis, P2):
    """reverse.py's 2D coords (its plane axes, sorted) -> this tree's right-handed (u, v)."""
    a = AXN.index(axis); ru, rv = reverse.plane_axes(a); mu, mv = T.UV[axis]
    P2 = np.asarray(P2, float)
    p3 = np.zeros((len(P2), 3)); p3[:, ru] = P2[:, 0]; p3[:, rv] = P2[:, 1]
    return np.c_[p3[:, mu], p3[:, mv]]


def loop_prims(axis, L, native=False):
    """Closed polyline -> exact lines / arcs / one circle (reverse.segment's fit), in tree coordinates.
    native: L is already in tree (u, v) coordinates, not reverse.py's."""
    conv = (lambda a, P: np.asarray(P, float)) if native else _uv
    L2, prims = reverse.segment(np.asarray(L, float))
    Q = conv(axis, L2)
    r2 = lambda p: [round(float(p[0]), 4), round(float(p[1]), 4)]
    if len(prims) == 1 and prims[0][0] == "arc":
        c = conv(axis, [prims[0][3]])[0]
        return [{"t": "circle", "c": r2(c), "r": round(float(prims[0][4]), 4)}]
    out = []
    for p in prims:
        i0, i1 = p[1], min(p[2], len(Q) - 1)
        if p[0] == "line" or i1 - i0 < 2:
            out.append({"t": "line", "p": [r2(Q[i0]), r2(Q[i1])]})
        else:
            out.append({"t": "arc", "p": [r2(Q[i0]), r2(Q[(i0 + i1) // 2]), r2(Q[i1])]})
    return out


def _name(loop):
    return f"Hole ⌀{2 * loop[0]['r']:.3g}" if len(loop) == 1 and loop[0]["t"] == "circle" else "Cutout"


def cap_kind(m, ax, lo, hi, sil, d, cap):
    """Round or chamfer on a cap edge of inset d: compare the section inset at depth d/2 with both models."""
    A_sil, P_sil = sil.area, sil.length
    ins = []
    for h in (0.25 * d, 0.5 * d, 0.75 * d):
        z = hi[ax] - h if cap > 0 else lo[ax] + h
        A, P = reverse.section_area_perimeter(m, ax, z)
        ins.append(max(0.0, 2 * (A_sil - A) / max(P + P_sil, 1e-9)))
    i_half = ins[1]
    if abs(i_half - 0.5 * d) < abs(i_half - 0.134 * d):
        return "chamfer", float(np.mean([i + h for i, h in zip(ins, (0.25 * d, 0.5 * d, 0.75 * d))]))
    return "round", float(d)


def sketch_axis(m):
    """The main extrusion's axis: most area aligned with it (walls parallel, caps across) PLUS its cap area, weighted
    by half. Aligned area alone picks X on a rim-chamfered 40x20x6 plate: the chamfers along its long sides are
    parallel to X, so X out-scores the real extrusion axis Z, whose flat caps are 60 % of the part."""
    n, w = m.face_normals, m.area_faces
    def score(k):
        c = np.abs(n[:, k])
        return (w[(c < 0.02) | (c > 0.999)].sum() + 0.5 * w[c > 0.999].sum()) / w.sum()
    return int(np.argmax([score(k) for k in range(3)]))


def main_extrusion(m, stl):
    R = reverse.reverse(stl, axis=sketch_axis(m))
    axis, ax = R["axis"], AXN.index(R["axis"])
    lo, hi = m.bounds
    feats = []
    if R["levels"]:
        for k, lv in enumerate(R["levels"]):
            for j, sh in enumerate(lv["shapes"]):
                feats.append({"op": "pad", "label": f"Level {k + 1}" + (f".{j + 1}" if len(lv["shapes"]) > 1 else ""),
                              "axis": axis, "at": round(lv["z0"], 4), "length": round(lv["z1"] - lv["z0"], 4),
                              "loops": [loop_prims(axis, sh["outer"])] + [loop_prims(axis, h) for h in sh["holes"]]})
        return feats
    feats.append({"op": "pad", "label": "Base extrusion", "axis": axis, "at": round(R["z0"], 4),
                  "length": round(R["height"], 4), "loops": [loop_prims(axis, R["outer"])]})
    for h in R["holes"]:
        lp = loop_prims(axis, h)
        feats.append({"op": "pocket", "label": _name(lp), "axis": axis, "at": round(R["z0"], 4),
                      "length": "through", "loops": [lp]})
    sil = reverse.silhouette(np.asarray(m.triangles, float), ax)
    if sil.geom_type != "Polygon":
        sil = max(sil.geoms, key=lambda g: g.area)
    mods = {}
    for cap, rr, name in ((+1, R["r_top"], "top"), (-1, R["r_bottom"], "bottom")):
        for which in ("outer", "holes"):
            d = min(float(rr[which]), R["height"] / 2 - 1e-3)
            if d > 1e-3 * R["height"]:
                kind, size = cap_kind(m, ax, lo, hi, sil, d, cap) if which == "outer" else ("round", d)
                mods.setdefault((kind, round(size, 3), which), []).append(name)
    for (kind, size, which), caps in mods.items():
        feats.append({"op": kind, "label": f"{'Rounded' if kind == 'round' else 'Chamfered'} "
                      f"{'rim' if which == 'outer' else 'hole'} edges", "size": size, "on": "F1",
                      "cap": "both" if len(caps) == 2 else caps[0], "loops": "outer" if which == "outer" else "inner"})
    return feats


def cylinders(m, faces, tol, smooth=None):
    """Cylindrical pieces among the given mesh faces: [(axis_name, centre_uv, r, lo, hi, is_hole, area)].
    smooth (degrees): split pieces at sharper edges too (needed when `faces` is the whole mesh)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    sel = np.zeros(len(m.faces), bool); sel[faces] = True
    keep = sel[m.face_adjacency[:, 0]] & sel[m.face_adjacency[:, 1]]
    if smooth:
        keep &= m.face_adjacency_angles < np.radians(smooth)
    adj = m.face_adjacency[keep]
    n = len(m.faces)
    _, lab = connected_components(coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(n, n)), directed=False)
    out = []
    for comp in np.unique(lab[sel]):
        idx = np.where((lab == comp) & sel)[0]
        w = m.area_faces[idx]
        if w.sum() < 2e-3 * m.area or len(idx) < 8:
            continue
        nrm0 = m.face_normals[idx]
        axis = np.linalg.svd(nrm0 * w[:, None], full_matrices=False)[2][-1]
        k = int(np.argmax(np.abs(axis)))
        if abs(axis[k]) < 0.995:                       # principal axes only
            continue
        cap = np.abs(nrm0[:, k]) > 0.9                 # a flat blind-hole bottom (or boss top): an exact end
        wall = np.abs(nrm0[:, k]) < 0.3
        if wall.sum() < 8 or w[wall].sum() < 0.7 * w.sum() * (1 - cap.mean()):
            continue
        ends = m.triangles_center[idx[cap]][:, k] if cap.any() else np.array([])
        idx, w = idx[wall], w[wall]
        nrm, pts = m.face_normals[idx], m.triangles_center[idx]
        name = AXN[k]; mu, mv = T.UV[name]
        p = np.c_[pts[:, mu], pts[:, mv]]
        sol = np.linalg.lstsq(np.c_[2 * p, np.ones(len(p))], (p ** 2).sum(1), rcond=None)[0]
        c = sol[:2]; r = float(np.sqrt(max(sol[2] + c @ c, 0)))
        if r <= 0 or np.abs(np.linalg.norm(p - c, axis=1) - r).max() > max(2 * tol, 0.05 * r):
            continue
        radial = np.c_[p - c]; radial /= np.linalg.norm(radial, axis=1)[:, None]
        hole = float(((np.c_[nrm[:, mu], nrm[:, mv]] * radial).sum(1) * w).sum()) < 0
        h = m.vertices[m.faces[idx].ravel()][:, k]
        lo, hi = float(h.min()), float(h.max())
        closed_lo = bool(len(ends)) and np.abs(ends - lo).min() < tol
        closed_hi = bool(len(ends)) and np.abs(ends - hi).min() < tol
        out.append((name, c, r, lo - (0 if closed_lo else 2 * tol), hi + (0 if closed_hi else 2 * tol), hole,
                    float(w.sum()), [[round(lo, 3), round(hi, 3)]]))
    merged = []                                        # coaxial, same radius, same kind: one feature
    for cy in sorted(out, key=lambda x: -x[6]):
        for mg in merged:
            if mg[0] == cy[0] and mg[5] == cy[5] and np.linalg.norm(mg[1] - cy[1]) < 2 * tol and abs(mg[2] - cy[2]) < 0.05 * mg[2]:
                mg[3], mg[4] = min(mg[3], cy[3]), max(mg[4], cy[4]); mg[6] += cy[6]; mg[7] += cy[7]; break
        else:
            merged.append(list(cy))
    return merged


def propose(stl):
    m = trimesh.load(stl, force="mesh")
    # 0.3 % of the diagonal, floored at 0.05: portal STLs are mm, and 0.05 mm is below what a printer resolves
    tol = max(3e-3 * float(np.linalg.norm(m.extents)), 0.05)
    tree = {"units": "mm", "features": main_extrusion(m, stl)}
    _ids(tree)
    finish(tree, m, tol)
    return tree, m, tol


def slab_region(m, a, z0, z1):
    """What the part covers seen along axis a within the slab z0..z1: one CT slice of the scan. The projection of the
    sliced triangles alone misses the walls parallel to a (zero area) and the cut ends, so the end sections are added:
    a closed slab's projection is its sides' plus its two caps'. A superset of the material: a cut outside it is safe."""
    import shapely
    from shapely.geometry import Polygon
    n = np.zeros(3)
    n[a] = 1.0
    sl = trimesh.intersections.slice_mesh_plane(m, n, n * (z0 + 1e-6))
    sl = trimesh.intersections.slice_mesh_plane(sl, -n, n * (z1 - 1e-6))
    g = Polygon()
    if len(sl.faces):                                  # reverse.silhouette, vectorised: its per-triangle loop was
        u, v = reverse.plane_axes(a)
        t2 = np.asarray(sl.triangles, float)[:, :, [u, v]]
        polys = shapely.polygons(np.concatenate([t2, t2[:, :1]], axis=1))
        polys = polys[shapely.area(polys) > 1e-9]
        eps = 1e-4 * float(np.linalg.norm(np.ptp(t2.reshape(-1, 2), axis=0)))
        g = shapely.union_all(polys).buffer(eps, join_style=2).buffer(-eps, join_style=2)
    for h in (z0 + 1e-4 * (z1 - z0), z1 - 1e-4 * (z1 - z0)):
        r = reverse._region(reverse.level_section(m, a, h))
        if r is not None:
            try:
                g = g.union(r.buffer(0))
            except shapely.errors.GEOSException:       # a self-touching section loop (parts 12, 20, 35): snap-rounded
                g = shapely.union(g.buffer(0), r.buffer(0), grid_size=1e-6 * float(np.linalg.norm(m.extents)))
    return g


def _polys(g):
    return [x for x in (g.geoms if hasattr(g, "geoms") else [g]) if x.geom_type == "Polygon"]


def _loops(axis, g, tol):
    return [loop_prims(axis, np.asarray(g.exterior.coords)[:-1])] + \
           [loop_prims(axis, np.asarray(r.coords)[:-1]) for r in g.interiors if Polygon_area(r) > 4 * tol * tol]


def ct_scan(tree, m, tol):
    """Three CT scans. A designer sketches on two or three planes, and the owner, grading, found the tree using one
    ('you completely missed a plane, orthogonal to the plane you used'). Once the main plane is known, the part is
    sliced along the two orthogonal axes too, at its level heights (flat faces across that axis); in each slab,
    whatever lies outside the slab's projection is a cut sketched on that plane, over that range. Every such cut
    is outside the material by construction, so they are all kept, unless they break a modifier or the match.
    A layer stack on the main axis is also tried rebuilt from slab projections, judged with the cuts applied.
    Edits tree in place."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    feats = tree["features"]
    main = next((f["axis"] for f in feats if f["op"] in ("pad", "pocket")), None)
    if main is None:
        return tree
    lo, hi = m.bounds
    tri = np.asarray(m.triangles, float)

    def fit(t, iou=False):
        sh, notes = T.compile_tree(t, tol)
        if sh is None:
            return (-1.0, 0.0, 99, 0.0) if iou else (-1.0, 0.0, 99)
        d = T.deviation(m, sh, tol)
        sc = d["explained"] - d["extra"], d["explained"], T.broken_steps(notes)
        return (*sc, T.volume_iou(m, sh, tol, occ) if occ is not None else 0.0) if iou else sc

    def scan(a):
        zs = reverse.level_heights(m, a, lo, hi, 1e-3 * reverse.silhouette(tri, a).area)
        return list(itertools.pairwise(zs))

    _t0 = __import__("time").time()

    def with_(t_feats, add):
        k = next((i for i, f in enumerate(t_feats) if f["op"] in ("round", "chamfer")), len(t_feats))
        t = {"units": tree.get("units", "mm"), "features": [*t_feats[:k], *add, *t_feats[k:]]}
        _ids(t, keep_refs=True)
        return t

    groups = []
    for a, axis in enumerate(AXN):
        if axis == main:
            continue
        u, v = reverse.plane_axes(a)
        rect = box(lo[u] - 2 * tol, lo[v] - 2 * tol, hi[u] + 2 * tol, hi[v] + 2 * tol)
        inner = box(lo[u] + tol, lo[v] + tol, hi[u] - tol, hi[v] - tol)
        lv = scan(a)
        prev = None
        for k, (z0, z1) in enumerate(lv):
            empty = rect.difference(slab_region(m, a, z0, z1).buffer(tol / 4, join_style=2))
            empty = empty.buffer(-tol / 2, join_style=2).buffer(tol / 2, join_style=2)
            cut = [g for g in _polys(empty) if g.intersection(inner).area > 4 * tol * tol]   # the margin ring cuts nothing
            e0 = z0 - (2 * tol if k == 0 else 0)
            e1 = z1 + (2 * tol if k == len(lv) - 1 else 0)
            if not cut:
                prev = None
                continue
            u_cut = unary_union(cut)
            if prev is not None and prev[0].symmetric_difference(u_cut).area < 0.1 * tol * max(u_cut.length, tol):
                for f in prev[1]:                        # the same sketch continues through this slab: one cut
                    f["length"] = round(e1 - f["at"], 4)
                continue
            fs = [({"op": "pocket", "label": f"Cut on {axis} plane", "axis": axis, "at": round(e0, 4),
                    "length": round(e1 - e0, 4)}, g) for g in cut]   # loops fitted only if kept
            groups.append((fs, a))
            prev = (u_cut, [f for f, _ in fs])
    cuts = [(f, a, g) for fs, a in groups for f, g in fs]

    def bite(sh, a, g, f):
        """How much material the model has that this cut takes away (0: none)? The mid-slab section of the solid, in reverse.py's
        plane axes, against the cut sketch. Most slabs cut only air the main stack already left out (the gate:
        109 cuts, a trial past 90 s); those are dropped before compiling."""
        z0, z1 = max(f["at"], lo[a]), min(f["at"] + f["length"], hi[a])
        key = (a, round((z0 + z1) / 2, 6))
        if key not in _sec:                            # the cuts of one slab share its section
            _sec[key] = T.sketch_section(sh, AXN[a], key[1])   # plane_axes order, as the cut sketches
        reg = _sec[key]
        if reg is None:
            return 1.0
        # a real bite, thicker than the modifiers: sections ignore rounds and chamfers, and a sliver along an
        # edge is theirs to take (the refine pass sizes them)
        thick = max([tol] + [float(x["size"]) for x in sh if x["op"] in ("round", "chamfer")])
        b = reg.intersection(g)
        return b.area * (min(f["length"], hi[a] - lo[a])) if b.buffer(-thick, join_style=2).area > 0 else 0.0
    stacks = [feats]
    ma = AXN.index(main)
    if 1 < sum(f["op"] == "pad" and f.get("label", "").startswith("Level") for f in feats) <= 12:
        # (a taller stack: its slab twin broke a step on the gate and cost 80 s to judge)
        # a sloped or rounded level is covered, not cut at its mid-height; alone it overfills, so judged with the cuts
        slabs = [{"op": "pad", "label": f"Level {k + 1}.{j + 1}", "axis": main, "at": round(z0, 4),
                  "length": round(z1 - z0, 4), "loops": _loops(main, g, tol)}
                 for k, (z0, z1) in enumerate(scan(ma)) for j, g in enumerate(_polys(slab_region(m, ma, z0, z1)))
                 if g.area > 4 * tol * tol]
        stacks.append(slabs + [f for f in feats if not (f["op"] == "pad" and f.get("label", "").startswith("Level"))])

    _sec = {}

    def measure(t):
        return fit(t, iou=True)

    def stack_trial(st):
        """One main stack with the cuts that bite on it: (score, explained, broken, iou, tree, kept cuts).
        The biggest bites only (MAX_CUTS): a trial's compile grows with its features, 72 on the gate cost 150 s."""
        import time
        c1 = time.time()
        bites = [(bite(st, a, g, f), i) for i, (f, a, g) in enumerate(cuts)]
        top = sorted(i for b, i in sorted(bites, reverse=True)[:MAX_CUTS] if b > 0)
        keep = [dict(cuts[i][0], loops=_loops(cuts[i][0]["axis"], cuts[i][2], tol)) for i in top]
        t = with_(st, keep)
        c2 = time.time()
        r = measure(t)
        print(f"[ct_scan trial] bites {c2 - c1:.1f} s ({len(_sec)} sections), {len(keep)} kept, "
              f"measure {time.time() - c2:.1f} s -> {r}", file=sys.stderr, flush=True)
        return (*r, t, keep)

    import time
    for i, st in enumerate(stacks):                    # compiled here once: the forked trials inherit the prefix
        c0 = time.time()                               # cache instead of each rebuilding the stack (gate: 120 s+)
        T.compile_tree(with_(st, []), tol)
        if i == 0 and time.time() - c0 > 30:           # a tree this heavy cannot afford the trials (part 14: the
            print(f"[ct_scan] base compile {time.time() - c0:.0f} s: scans skipped",   # compile alone, then three
                  file=sys.stderr, flush=True)                                          # 120 s trials, 408 s)
            return tree
        if i == 0 and time.time() - c0 > 10:
            stacks = stacks[:1]
            break
    occ = T.occupancy(m, m.bounds, n=60) if len(stacks) > 1 else None
    hb = _fork_start(measure, tree)                    # the base and every stack at once: independent trials
    hs = [_fork_start(stack_trial, st) for st in stacks]
    end = time.time() + 120.0
    base = _fork_collect(hb, end, default=(-1.0, 0.0, 99, 0.0))
    kb = base[3] if occ is not None else base[0]
    best, first = None, None
    for h in hs:
        r = _fork_collect(h, end)
        if r is None:
            continue
        first = first or r[5]
        key = r[3] if occ is not None else r[0]
        # volume overlap decides between stacks (a slope's slab projection fills the cavity, part 2)
        if r[2] <= base[2] and r[1] > base[1] - 0.005 and key > kb and (best is None or key > best[0]):
            best = (key, r[4])
    if best is not None:
        feats[:] = best[1]["features"]
    elif first:                                        # one cut at a time, each kept only if the match improves
        for f in first[:24]:
            trial = with_(feats, [f])
            sc = _forked(fit, trial, default=(-1.0, 0.0, 99))
            if sc[2] <= base[2] and sc[0] > base[0] + 0.001:
                feats[:] = trial["features"]
                base = (*sc, base[3])
    _ids(tree, keep_refs=True)
    print(f"[ct_scan] {__import__('time').time() - _t0:.1f} s, {len(cuts)} cuts scanned, "
          f"{sum(f.get('label', '').startswith('Cut on') for f in feats)} kept, {len(stacks)} stacks", file=sys.stderr, flush=True)
    return tree


def _fork_start(fn, *args):
    """fn(*args) in a forked child; returns a handle for _fork_collect. Children started together run in parallel."""
    import os
    import pickle
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        try:
            os.write(w, pickle.dumps(fn(*args)))
        finally:
            os._exit(0)
    os.close(w)
    return pid, r


def _fork_collect(handle, end, default=None):
    """The child's result, or `default` if it died or is still running at time `end` (then killed)."""
    import os
    import pickle
    import select
    import signal
    import time
    pid, r = handle
    data = b""
    with os.fdopen(r, "rb", buffering=0) as f:
        while (left := end - time.time()) > 0 and select.select([f], [], [], left)[0]:
            chunk = f.read(1 << 16)
            if not chunk:
                break
            data += chunk
        else:
            os.kill(pid, signal.SIGKILL)
            print("[propose] trial over its time: rejected", file=sys.stderr, flush=True)
            data = b""
    os.waitpid(pid, 0)
    return pickle.loads(data) if data else default


def _forked(fn, *args, default=None, timeout=90.0):
    """fn(*args) in a forked child: OCCT's fillet builder can SIGSEGV on a trial tree (part 23) or never return
    (the gate), and either must only reject that candidate."""
    import time
    return _fork_collect(_fork_start(fn, *args), time.time() + timeout, default)


def Polygon_area(ring):
    from shapely.geometry import Polygon
    return Polygon(ring).area


def finish(tree, m, tol):
    """The deterministic passes after the base bodies: the orthogonal-plane scans (ct_scan),
    partial-depth pockets/bosses on any plane, residual cylinders (holes/bosses on any principal
    axis), each kept only if the match improves, then modifier sizes fitted. Edits tree in place."""
    ct_scan(tree, m, tol)
    import plan as PL                                  # plan imports this module: import here
    # partial-depth features on any plane: where model and mesh volumes disagree, a pocket or boss
    # across the best axis over its own range (snapped to flat faces); ran only after the planner
    PL.residual_prisms(tree, m, PL.facts(m, tol), tol)
    feats = tree["features"]
    shape, _ = T.compile_tree(tree, tol)
    dev = T.deviation(m, shape, tol)
    far = np.where(dev["face_dist"] > tol)[0]
    extra = []
    for name, c, r, lo, hi, hole, _, _ in cylinders(m, far, tol):
        extra.append({"op": "pocket" if hole else "pad", "label": f"{'Hole' if hole else 'Boss'} ⌀{2 * r:.3g}",
                      "axis": name, "at": round(lo, 4), "length": round(hi - lo, 4),   # open ends already extended
                      "loops": [[{"t": "circle", "c": [round(float(c[0]), 4), round(float(c[1]), 4)], "r": round(r, 4)}]]})
    base = (dev["explained"], dev["extra"])
    for cand in extra:                                 # keep a candidate only if the mesh says it helps
        k = next((i for i, f in enumerate(feats) if f["op"] in ("round", "chamfer")), len(feats))
        trial = {"units": "mm", "features": feats[:k] + [dict(cand, id=f"R{k}")] + feats[k:]}
        sh, _ = T.compile_tree(trial, tol)
        if sh is None:
            continue
        d = T.deviation(m, sh, tol)
        if d["explained"] > base[0] + 0.003 and d["extra"] < base[1] + 0.003:
            feats.insert(k, dict(cand, id=f"R{k}")); base = (d["explained"], d["extra"])   # renumbered below
    _ids(tree, keep_refs=True)
    refine(tree, m, tol)
    return tree


def score(tree, m, tol):
    """How badly the tree's solid misses the mesh: mean face distance, capped at 3 tol (area-weighted)."""
    shape, _ = T.compile_tree(tree, tol)
    if shape is None:
        return 1e9
    d = T.deviation(m, shape, tol)
    return float((np.minimum(d["face_dist"], 3 * tol) * m.area_faces).sum() / m.area)


def refine(tree, m, tol, evals=7):
    """Fit each round/chamfer size to the mesh (golden section over 0.4x..2.5x the first estimate). The structure is
    fixed; only numbers move, and only by measurement."""
    g = (5 ** 0.5 - 1) / 2
    for f in tree["features"]:
        if f["op"] not in ("round", "chamfer"):
            continue
        s0 = float(f["size"]); a, b = 0.4 * s0, 2.5 * s0
        def at(x):
            f["size"] = round(x, 4); return score(tree, m, tol)
        c, d = b - g * (b - a), a + g * (b - a); fc, fd = at(c), at(d)
        for _ in range(evals - 2):
            if fc < fd:
                b, d, fd = d, c, fc; c = b - g * (b - a); fc = at(c)
            else:
                a, c, fc = c, d, fd; d = a + g * (b - a); fd = at(d)
        f["size"] = round(c if fc < fd else d, 4)
    return tree


def _ids(tree, keep_refs=False):
    old = {f.get("id"): f for f in tree["features"]}
    for i, f in enumerate(tree["features"]):
        f["id"] = f"F{i + 1}"
    if keep_refs:                                      # modifiers keep pointing at the same feature
        for f in tree["features"]:
            if "on" in f and f["on"] in old:
                f["on"] = old[f["on"]]["id"]


if __name__ == "__main__":
    t, m, tol = propose(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(t, indent=1))
    s, notes = T.compile_tree(t, tol)
    d = T.deviation(m, s, tol)
    print(json.dumps({"features": [(f["id"], f["op"], f["label"]) for f in t["features"]], "notes": notes,
                      "explained": round(d["explained"], 4), "extra": round(d["extra"], 4), "tol": round(tol, 4),
                      "volume": round(T.volume(s), 3), "mesh_volume": round(float(m.volume), 3)}))
